"""TimescaleDB OHLCV mirror writer (asyncpg).

Writes the same OHLCV that the strategy persists locally as Parquet into the
strategy-owned ``db_tfex_s50_multi_tf_swing`` database. Tables:

* ``ohlcv_raw (time, contract, timeframe, open, high, low, close, volume, open_interest)``
* ``ohlcv_continuous (time, timeframe, open, high, low, close, volume,
  contract_at_time, adjustment_factor)``

Both writes are full ``INSERT … ON CONFLICT … DO UPDATE`` so re-running the
strategy's refresh path for the same date range is idempotent — same data in,
same row count out, same field values.

Phase 4 (feature-market-data-engine): when ``OHLCV_SOURCE='engine'`` the shared
``quant-marketdata-engine`` (canonical ``market_data.*`` schema) is the source
of truth and this 09 mirror (``db_tfex_s50_multi_tf_swing.ohlcv_raw`` /
``.ohlcv_continuous``) is demoted to a **derived local cache** materialised from
engine-sourced bars — never a parallel ingest. The physical drop/migration of
the 09 tables is a separate ``quant-infra-db`` PR, deferred until the engine
source is the validated default (no behaviour change here).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import asyncpg
import polars as pl

from tfex_s50_multi_tf_swing.data.errors import DbWriterError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger: logging.Logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _SQL:
    """Centralised SQL — no string-formatted queries in adapter methods."""

    UPSERT_OHLCV_RAW: str = (
        "INSERT INTO ohlcv_raw "
        "(time, contract, timeframe, open, high, low, close, volume, open_interest) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) "
        "ON CONFLICT (time, contract, timeframe) DO UPDATE SET "
        "open = EXCLUDED.open, "
        "high = EXCLUDED.high, "
        "low = EXCLUDED.low, "
        "close = EXCLUDED.close, "
        "volume = EXCLUDED.volume, "
        "open_interest = EXCLUDED.open_interest"
    )
    UPSERT_OHLCV_CONTINUOUS: str = (
        "INSERT INTO ohlcv_continuous "
        "(time, timeframe, open, high, low, close, volume, "
        "contract_at_time, adjustment_factor) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) "
        "ON CONFLICT (time, timeframe) DO UPDATE SET "
        "open = EXCLUDED.open, "
        "high = EXCLUDED.high, "
        "low = EXCLUDED.low, "
        "close = EXCLUDED.close, "
        "volume = EXCLUDED.volume, "
        "contract_at_time = EXCLUDED.contract_at_time, "
        "adjustment_factor = EXCLUDED.adjustment_factor"
    )


_SQL_STMTS = _SQL()


class OhlcvDbWriter:
    """Async TimescaleDB writer for the OHLCV mirror.

    Owns its own asyncpg pool. Construct via :meth:`from_dsn` or pass an
    existing pool for testing.
    """

    def __init__(self, *, pool: asyncpg.Pool) -> None:
        self._pool: asyncpg.Pool = pool

    @classmethod
    @asynccontextmanager
    async def from_dsn(
        cls, dsn: str, *, min_size: int = 1, max_size: int = 4
    ) -> AsyncIterator[OhlcvDbWriter]:
        """Async context manager owning an asyncpg pool.

        Example::

            async with OhlcvDbWriter.from_dsn(settings.pg_dsn) as writer:
                await writer.upsert_raw_frame(frame, contract="S50M2026", timeframe="5m")
        """
        try:
            pool = await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)
        except Exception as exc:
            raise DbWriterError(f"failed to open asyncpg pool: {exc!r}") from exc
        try:
            yield cls(pool=pool)
        finally:
            await pool.close()

    async def close(self) -> None:
        """Close the pool. Safe to call multiple times."""
        if self._pool is not None:
            await self._pool.close()

    # ------------------------------------------------------------------
    # Raw OHLCV
    # ------------------------------------------------------------------

    async def upsert_raw_frame(
        self,
        df: pl.DataFrame,
        *,
        contract: str,
        timeframe: str,
    ) -> int:
        """Upsert a per-contract raw frame; returns rows written."""
        rows = list(_iter_raw_rows(df, contract=contract, timeframe=timeframe))
        if not rows:
            return 0
        try:
            async with self._pool.acquire() as conn, conn.transaction():
                await conn.executemany(_SQL_STMTS.UPSERT_OHLCV_RAW, rows)
        except (asyncpg.PostgresError, OSError) as exc:
            raise DbWriterError(
                f"upsert_raw_frame failed contract={contract} tf={timeframe}: {exc!r}"
            ) from exc
        logger.info(
            "db_writer: upserted %d ohlcv_raw rows contract=%s tf=%s",
            len(rows),
            contract,
            timeframe,
        )
        return len(rows)

    async def upsert_continuous_frame(
        self,
        df: pl.DataFrame,
        *,
        timeframe: str,
    ) -> int:
        """Upsert a continuous frame; returns rows written."""
        rows = list(_iter_continuous_rows(df, timeframe=timeframe))
        if not rows:
            return 0
        try:
            async with self._pool.acquire() as conn, conn.transaction():
                await conn.executemany(_SQL_STMTS.UPSERT_OHLCV_CONTINUOUS, rows)
        except (asyncpg.PostgresError, OSError) as exc:
            raise DbWriterError(f"upsert_continuous_frame failed tf={timeframe}: {exc!r}") from exc
        logger.info(
            "db_writer: upserted %d ohlcv_continuous rows tf=%s",
            len(rows),
            timeframe,
        )
        return len(rows)


# ---------------------------------------------------------------------------
# Row builders (pure, testable without asyncpg)
# ---------------------------------------------------------------------------


def _iter_raw_rows(
    df: pl.DataFrame,
    *,
    contract: str,
    timeframe: str,
) -> Iterable[tuple[Any, ...]]:
    needed = ("time", "open", "high", "low", "close", "volume")
    missing = set(needed) - set(df.columns)
    if missing:
        raise DbWriterError(f"raw frame missing columns: {sorted(missing)}")
    has_oi = "open_interest" in df.columns
    for row in df.iter_rows(named=True):
        yield (
            row["time"],
            contract,
            timeframe,
            _to_decimal(row["open"]),
            _to_decimal(row["high"]),
            _to_decimal(row["low"]),
            _to_decimal(row["close"]),
            _to_decimal(row["volume"]),
            _to_decimal(row["open_interest"]) if has_oi else None,
        )


def _iter_continuous_rows(
    df: pl.DataFrame,
    *,
    timeframe: str,
) -> Iterable[tuple[Any, ...]]:
    needed = (
        "time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "contract_at_time",
        "adjustment_factor",
    )
    missing = set(needed) - set(df.columns)
    if missing:
        raise DbWriterError(f"continuous frame missing columns: {sorted(missing)}")
    for row in df.iter_rows(named=True):
        yield (
            row["time"],
            timeframe,
            _to_decimal(row["open"]),
            _to_decimal(row["high"]),
            _to_decimal(row["low"]),
            _to_decimal(row["close"]),
            _to_decimal(row["volume"]),
            row["contract_at_time"],
            _to_decimal(row["adjustment_factor"]),
        )


def _to_decimal(v: object) -> Decimal | None:
    """Coerce a frame cell to Decimal; forbid float silently crossing the boundary."""
    if v is None:
        return None
    if isinstance(v, Decimal):
        return v
    if isinstance(v, float):
        raise DbWriterError(
            "float values are forbidden across the DB boundary; "
            "all OHLCV columns must be Decimal-typed (decimal(18,4)/decimal(18,8))"
        )
    # int and str round-trip cleanly through Decimal(str(...))
    return Decimal(str(v))


__all__: list[str] = ["OhlcvDbWriter"]
