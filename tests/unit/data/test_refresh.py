"""Unit tests for :func:`tfex_s50_multi_tf_swing.data.refresh.refresh_all`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from tfex_s50_multi_tf_swing.config.settings import Settings
from tfex_s50_multi_tf_swing.data.errors import DataError
from tfex_s50_multi_tf_swing.data.refresh import refresh_all
from tfex_s50_multi_tf_swing.data.session import SessionCalendar
from tfex_s50_multi_tf_swing.data.store import ParquetStore

_START = datetime(2026, 3, 2, tzinfo=UTC)
_END = datetime(2026, 6, 1, tzinfo=UTC)


def _frame(days: int, start: datetime, base: float) -> pl.DataFrame:
    rows = []
    for i in range(days):
        t = start + timedelta(days=i)
        rows.append(
            {
                "time": t,
                "open": Decimal(f"{base + i * 0.1:.4f}"),
                "high": Decimal(f"{base + i * 0.1 + 0.5:.4f}"),
                "low": Decimal(f"{base + i * 0.1 - 0.5:.4f}"),
                "close": Decimal(f"{base + i * 0.1:.4f}"),
                "volume": Decimal("1000.0000"),
            }
        )
    return pl.DataFrame(rows).with_columns(pl.col("time").dt.replace_time_zone("UTC"))


class _FakeFetcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def fetch_contract(
        self,
        *,
        contract_code: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> pl.DataFrame:
        self.calls.append((contract_code, timeframe))
        if contract_code == "S50H2026":
            return _frame(30, datetime(2026, 3, 2, tzinfo=UTC), 800.0)
        return _frame(30, datetime(2026, 3, 28, tzinfo=UTC), 820.0)

    async def fetch_continuous_reference(
        self,
        *,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> pl.DataFrame:
        # Return identical-shape continuous data so the cross-check passes.
        return _frame(60, datetime(2026, 3, 2, tzinfo=UTC), 820.0)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        public_mode=False,
        db_write_enabled=False,
        data_dir=tmp_path,
        roll_offset_days=5,
        data_fetch_concurrency=2,
    )


async def test_refresh_writes_parquet_and_returns_summary(tmp_path: Path) -> None:
    fetcher = _FakeFetcher()
    settings = _settings(tmp_path)
    store = ParquetStore(tmp_path)

    summary = await refresh_all(
        settings=settings,
        contracts=["S50H2026", "S50M2026"],
        timeframes=["4h"],
        start=_START,
        end=_END,
        fetcher=fetcher,
        store=store,
        calendar=SessionCalendar(roll_offset_days=5),
    )
    assert summary.raw_rows_written == 60  # 2 contracts × 30 bars
    assert summary.continuous_rows_written > 0
    assert len(summary.rolls) == 1
    assert summary.db_raw_rows_upserted == 0  # no db_writer injected

    # Parquet files exist.
    assert store.raw_path("S50H2026", "4h").exists()
    assert store.raw_path("S50M2026", "4h").exists()
    assert store.continuous_path("4h").exists()
    assert store.reference_path("4h").exists()


async def test_refresh_idempotent_second_run_same_counts(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = ParquetStore(tmp_path)
    fetcher = _FakeFetcher()
    first = await refresh_all(
        settings=settings,
        contracts=["S50H2026", "S50M2026"],
        timeframes=["4h"],
        start=_START,
        end=_END,
        fetcher=fetcher,
        store=store,
    )
    fetcher2 = _FakeFetcher()
    second = await refresh_all(
        settings=settings,
        contracts=["S50H2026", "S50M2026"],
        timeframes=["4h"],
        start=_START,
        end=_END,
        fetcher=fetcher2,
        store=store,
    )
    assert first.raw_rows_written == second.raw_rows_written
    assert first.continuous_rows_written == second.continuous_rows_written


async def test_refresh_rejects_empty_contracts(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(DataError):
        await refresh_all(
            settings=settings,
            contracts=[],
            timeframes=["4h"],
            start=_START,
            end=_END,
            fetcher=_FakeFetcher(),
            store=ParquetStore(tmp_path),
        )


async def test_refresh_rejects_empty_timeframes(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(DataError):
        await refresh_all(
            settings=settings,
            contracts=["S50H2026"],
            timeframes=[],
            start=_START,
            end=_END,
            fetcher=_FakeFetcher(),
            store=ParquetStore(tmp_path),
        )


async def test_refresh_rejects_naive_window(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(DataError):
        await refresh_all(
            settings=settings,
            contracts=["S50H2026"],
            timeframes=["4h"],
            start=datetime(2026, 3, 2),  # naive
            end=_END,
            fetcher=_FakeFetcher(),
            store=ParquetStore(tmp_path),
        )


class _EmptyFetcher:
    async def fetch_contract(self, **_kw: object) -> pl.DataFrame:
        return pl.DataFrame(
            schema={
                "time": pl.Datetime("us", "UTC"),
                "open": pl.Decimal(18, 4),
                "high": pl.Decimal(18, 4),
                "low": pl.Decimal(18, 4),
                "close": pl.Decimal(18, 4),
                "volume": pl.Decimal(18, 4),
            }
        )

    async def fetch_continuous_reference(self, **_kw: object) -> pl.DataFrame:
        return pl.DataFrame(
            schema={
                "time": pl.Datetime("us", "UTC"),
                "open": pl.Decimal(18, 4),
                "high": pl.Decimal(18, 4),
                "low": pl.Decimal(18, 4),
                "close": pl.Decimal(18, 4),
                "volume": pl.Decimal(18, 4),
            }
        )


async def test_refresh_empty_data_does_not_write(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = ParquetStore(tmp_path)
    summary = await refresh_all(
        settings=settings,
        contracts=["S50H2026"],
        timeframes=["4h"],
        start=_START,
        end=_END,
        fetcher=_EmptyFetcher(),
        store=store,
    )
    assert summary.raw_rows_written == 0
    assert summary.continuous_rows_written == 0
    assert not store.raw_path("S50H2026", "4h").exists()
