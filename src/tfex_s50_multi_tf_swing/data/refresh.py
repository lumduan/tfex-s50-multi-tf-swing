"""End-to-end refresh orchestrator.

Wires fetcher → store → validator → continuous builder → store + DB writer.
Idempotent on re-run: same inputs → identical Parquet files and identical DB
state (UPSERT on conflict).

The orchestrator is deliberately small. It does not own the asyncpg pool or
the tvkit client lifecycle; both are injected so unit tests can swap stubs.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

import polars as pl

from tfex_s50_multi_tf_swing.config.settings import Settings
from tfex_s50_multi_tf_swing.data.continuous import ContinuousBuilder
from tfex_s50_multi_tf_swing.data.db_writer import OhlcvDbWriter
from tfex_s50_multi_tf_swing.data.errors import DataError
from tfex_s50_multi_tf_swing.data.models import (
    TIMEFRAMES,
    RollRecord,
    Timeframe,
    ValidationReport,
)
from tfex_s50_multi_tf_swing.data.session import SessionCalendar
from tfex_s50_multi_tf_swing.data.store import ParquetStore
from tfex_s50_multi_tf_swing.data.validator import Validator

logger: logging.Logger = logging.getLogger(__name__)


class FetcherProtocol(Protocol):
    """Structural type the orchestrator depends on.

    :class:`OhlcvFetcher` satisfies this; unit-test fakes can too without
    inheriting from the concrete class.
    """

    async def fetch_contract(
        self,
        *,
        contract_code: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> pl.DataFrame: ...

    async def fetch_continuous_reference(
        self,
        *,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> pl.DataFrame: ...


@dataclass
class RefreshSummary:
    """Aggregate result of one refresh invocation."""

    as_of: datetime
    contracts: list[str] = field(default_factory=list)
    timeframes: list[Timeframe] = field(default_factory=list)
    raw_rows_written: int = 0
    continuous_rows_written: int = 0
    db_raw_rows_upserted: int = 0
    db_continuous_rows_upserted: int = 0
    rolls: list[RollRecord] = field(default_factory=list)
    reports: list[ValidationReport] = field(default_factory=list)


async def refresh_all(
    *,
    settings: Settings,
    contracts: Sequence[str],
    timeframes: Sequence[Timeframe] = TIMEFRAMES,
    start: datetime,
    end: datetime,
    fetcher: FetcherProtocol | None = None,
    store: ParquetStore | None = None,
    db_writer: OhlcvDbWriter | None = None,
    calendar: SessionCalendar | None = None,
) -> RefreshSummary:
    """Run one end-to-end refresh.

    ``fetcher`` / ``store`` / ``db_writer`` / ``calendar`` are injectable for
    tests; in production callers pass nothing and the orchestrator constructs
    defaults from ``settings``.

    Args:
        settings: Strategy settings. Drives data_dir, auth, concurrency.
        contracts: Quarterly contract codes to refresh, in any order. Callers
            typically derive these via
            :func:`tfex_s50_multi_tf_swing.data.contracts.iter_contracts`.
        timeframes: Subset of ``{"5m", "1h", "4h"}``. Defaults to all three.
        start: Inclusive UTC start of the refresh window.
        end: Exclusive UTC end of the refresh window.
        fetcher / store / db_writer / calendar: Optional injectables.

    Returns:
        :class:`RefreshSummary` with counts and roll metadata.
    """
    _require_utc(start, "start")
    _require_utc(end, "end")
    if not contracts:
        raise DataError("contracts must be non-empty")
    if not timeframes:
        raise DataError("timeframes must be non-empty")

    store = store or ParquetStore(_resolve_data_dir(settings.data_dir))
    calendar = calendar or SessionCalendar(roll_offset_days=settings.roll_offset_days)
    if fetcher is None:
        # Lazy import avoids a circular import (sources → refresh for the
        # FetcherProtocol type) and keeps the unused branch's deps unloaded.
        from tfex_s50_multi_tf_swing.data.sources import build_ohlcv_fetcher

        fetcher = build_ohlcv_fetcher(settings)
    validator = Validator(calendar=calendar)
    continuous = ContinuousBuilder(calendar=calendar, roll_offset_days=settings.roll_offset_days)

    summary = RefreshSummary(
        as_of=datetime.now(UTC),
        contracts=list(contracts),
        timeframes=list(timeframes),
    )

    for tf in timeframes:
        per_contract = {}
        for code in contracts:
            df = await fetcher.fetch_contract(
                contract_code=code, timeframe=tf, start=start, end=end
            )
            if df.height == 0:
                logger.info("refresh: 0 bars for %s %s; skipping store write", code, tf)
                continue
            store.write_raw(code, tf, df)
            summary.raw_rows_written += df.height
            if db_writer is not None:
                summary.db_raw_rows_upserted += await db_writer.upsert_raw_frame(
                    df, contract=code, timeframe=tf
                )
            per_contract[code] = df
            summary.reports.append(
                validator.validate(df, timeframe=tf, contract=code, as_of=summary.as_of)
            )

        # Continuous + reference cross-check happen once per timeframe.
        if per_contract:
            cont_frame, rolls = continuous.build(per_contract=per_contract, timeframe=tf)
            store.write_continuous(tf, cont_frame)
            summary.continuous_rows_written += cont_frame.height
            summary.rolls.extend(rolls)
            if db_writer is not None:
                summary.db_continuous_rows_upserted += await db_writer.upsert_continuous_frame(
                    cont_frame, timeframe=tf
                )

            ref_frame = await fetcher.fetch_continuous_reference(timeframe=tf, start=start, end=end)
            if ref_frame.height > 0:
                store.write_reference(tf, ref_frame)
                # Cross-check is informational; attach to the latest report list.
                cross = validator.validate_continuous_against_reference(
                    our_continuous=cont_frame.select(["time", "close"]),
                    s501_reference=ref_frame.select(["time", "close"]),
                    timeframe=tf,
                )
                # Mutate the most recent report for this timeframe to include the cross-check.
                if summary.reports:
                    last = summary.reports[-1]
                    summary.reports[-1] = last.model_copy(update={"cross_check": cross})

    # Persist a single aggregate report keyed by today's date.
    for report in summary.reports:
        store.write_validation_report(report)

    logger.info(
        "refresh: complete contracts=%s tfs=%s raw_rows=%d continuous_rows=%d rolls=%d",
        summary.contracts,
        summary.timeframes,
        summary.raw_rows_written,
        summary.continuous_rows_written,
        len(summary.rolls),
    )
    return summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_utc(dt: datetime, name: str) -> None:
    if dt.tzinfo is None:
        raise DataError(f"{name} must be timezone-aware UTC")
    if dt.utcoffset() != timedelta(0):
        raise DataError(f"{name} must be UTC; got {dt.tzinfo}")


def _resolve_data_dir(raw: Path) -> Path:
    if isinstance(raw, Path):
        return raw
    return Path(raw)


__all__: list[str] = ["RefreshSummary", "refresh_all"]
