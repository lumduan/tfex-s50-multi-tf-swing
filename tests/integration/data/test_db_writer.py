"""Integration tests for :class:`OhlcvDbWriter` against a real Postgres+Timescale.

Self-skips when ``TFEX_S50_MULTI_TF_SWING_PG_DSN`` is unset. The test database
must be ``db_tfex_s50_multi_tf_swing`` with schema 08 + 09 already provisioned
(``ohlcv_raw`` and ``ohlcv_continuous`` hypertables).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import asyncpg
import polars as pl
import pytest
import pytest_asyncio

from tfex_s50_multi_tf_swing.data.db_writer import OhlcvDbWriter

pytestmark = pytest.mark.infra_db

_DSN_ENV: str = "TFEX_S50_MULTI_TF_SWING_PG_DSN"


def _dsn_or_skip() -> str:
    dsn = os.environ.get(_DSN_ENV)
    if not dsn:
        pytest.skip(f"{_DSN_ENV} not set; skipping infra_db tests")
    return dsn


@pytest_asyncio.fixture()
async def writer() -> AsyncIterator[OhlcvDbWriter]:
    dsn = _dsn_or_skip()
    async with OhlcvDbWriter.from_dsn(dsn) as w:
        # Wipe any residue from prior runs so counts are deterministic.
        async with w._pool.acquire() as conn: 
            await conn.execute("DELETE FROM ohlcv_raw WHERE contract LIKE 'S50TEST%'")
            await conn.execute(
                "DELETE FROM ohlcv_continuous WHERE contract_at_time LIKE 'S50TEST%'"
            )
        yield w


def _raw_frame(n: int = 5) -> pl.DataFrame:
    start = datetime(2026, 5, 27, 2, 45, tzinfo=UTC)
    rows = []
    for i in range(n):
        t = start + timedelta(minutes=5 * i)
        rows.append(
            {
                "time": t,
                "open": Decimal(f"{800 + i:.4f}"),
                "high": Decimal(f"{801 + i:.4f}"),
                "low": Decimal(f"{799 + i:.4f}"),
                "close": Decimal(f"{800.5 + i:.4f}"),
                "volume": Decimal("1000.0000"),
                "open_interest": Decimal("500.0000"),
            }
        )
    return pl.DataFrame(rows)


def _continuous_frame(n: int = 5) -> pl.DataFrame:
    return _raw_frame(n).with_columns(
        [
            pl.lit("S50TEST_M2026").alias("contract_at_time"),
            pl.lit(Decimal("1.02500000")).cast(pl.Decimal(18, 8)).alias("adjustment_factor"),
        ]
    )


async def test_upsert_raw_then_idempotent_reupsert(writer: OhlcvDbWriter) -> None:
    df = _raw_frame(5)
    rows1 = await writer.upsert_raw_frame(df, contract="S50TEST_M2026", timeframe="5m")
    rows2 = await writer.upsert_raw_frame(df, contract="S50TEST_M2026", timeframe="5m")
    assert rows1 == 5
    assert rows2 == 5  # writer reports rows attempted, not rows changed
    async with writer._pool.acquire() as conn: 
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM ohlcv_raw WHERE contract = 'S50TEST_M2026'"
        )
        assert count == 5  # ON CONFLICT collapsed to one row per (time,contract,tf)


async def test_upsert_continuous_then_idempotent_reupsert(writer: OhlcvDbWriter) -> None:
    df = _continuous_frame(5)
    await writer.upsert_continuous_frame(df, timeframe="5m")
    await writer.upsert_continuous_frame(df, timeframe="5m")
    async with writer._pool.acquire() as conn: 
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM ohlcv_continuous WHERE contract_at_time = 'S50TEST_M2026'"
        )
        assert count == 5


async def test_hypertables_registered() -> None:
    """Sanity-check schema 09 is applied: ohlcv_raw + ohlcv_continuous are hypertables."""
    dsn = _dsn_or_skip()
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            "SELECT hypertable_name FROM timescaledb_information.hypertables "
            "WHERE hypertable_name LIKE 'ohlcv%' ORDER BY hypertable_name"
        )
        names = [r["hypertable_name"] for r in rows]
        assert "ohlcv_raw" in names
        assert "ohlcv_continuous" in names
    finally:
        await conn.close()


async def test_upsert_raw_empty_is_noop(writer: OhlcvDbWriter) -> None:
    # ``head(0)`` keeps the schema while emptying the data.
    empty = _raw_frame(1).head(0)
    assert await writer.upsert_raw_frame(empty, contract="S50TEST_X", timeframe="5m") == 0


async def test_upsert_continuous_empty_is_noop(writer: OhlcvDbWriter) -> None:
    empty = _continuous_frame(1).head(0)
    assert await writer.upsert_continuous_frame(empty, timeframe="5m") == 0
