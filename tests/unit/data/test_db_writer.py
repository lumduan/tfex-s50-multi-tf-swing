"""Unit tests for :class:`tfex_s50_multi_tf_swing.data.db_writer.OhlcvDbWriter`.

Pure-row-construction tests use the module-private helpers directly. The
asyncpg pool is exercised in the integration suite (``tests/integration/data/``)
under the ``@pytest.mark.infra_db`` marker.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import polars as pl
import pytest

from tfex_s50_multi_tf_swing.data.db_writer import (
    _iter_continuous_rows,
    _iter_raw_rows,
)
from tfex_s50_multi_tf_swing.data.errors import DbWriterError


def _raw_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "time": [datetime(2026, 5, 27, 2, 45, tzinfo=UTC)],
            "open": [Decimal("800.0000")],
            "high": [Decimal("800.5000")],
            "low": [Decimal("799.5000")],
            "close": [Decimal("800.2000")],
            "volume": [Decimal("1000.0000")],
        }
    )


def test_raw_rows_basic_columns() -> None:
    rows = list(_iter_raw_rows(_raw_frame(), contract="S50M2026", timeframe="5m"))
    assert len(rows) == 1
    row = rows[0]
    # (time, contract, timeframe, o, h, l, c, v, oi)
    assert row[1] == "S50M2026"
    assert row[2] == "5m"
    assert row[3] == Decimal("800.0000")
    assert row[8] is None  # no open_interest column → NULL


def test_raw_rows_with_open_interest() -> None:
    df = _raw_frame().with_columns(
        pl.lit(Decimal("123.0000")).cast(pl.Decimal(18, 4)).alias("open_interest")
    )
    rows = list(_iter_raw_rows(df, contract="S50M2026", timeframe="5m"))
    assert rows[0][8] == Decimal("123.0000")


def test_raw_rows_rejects_missing_columns() -> None:
    df = pl.DataFrame({"time": [datetime(2026, 5, 27, tzinfo=UTC)], "close": [Decimal("1.0")]})
    with pytest.raises(DbWriterError):
        list(_iter_raw_rows(df, contract="S50M2026", timeframe="5m"))


def test_raw_rows_rejects_float() -> None:
    df = _raw_frame().with_columns(pl.lit(1.0).alias("open"))
    with pytest.raises(DbWriterError):
        list(_iter_raw_rows(df, contract="S50M2026", timeframe="5m"))


def test_continuous_rows_basic() -> None:
    df = _raw_frame().with_columns(
        [
            pl.lit("S50M2026").alias("contract_at_time"),
            pl.lit("1.02500000").cast(pl.Decimal(18, 8)).alias("adjustment_factor"),
        ]
    )
    rows = list(_iter_continuous_rows(df, timeframe="1h"))
    assert len(rows) == 1
    row = rows[0]
    # (time, timeframe, o, h, l, c, v, contract_at_time, adjustment_factor)
    assert row[1] == "1h"
    assert row[7] == "S50M2026"
    assert row[8] == Decimal("1.02500000")


def test_continuous_rows_rejects_missing_columns() -> None:
    df = _raw_frame()  # no contract_at_time, no adjustment_factor
    with pytest.raises(DbWriterError):
        list(_iter_continuous_rows(df, timeframe="1h"))


# ---------------------------------------------------------------------------
# Writer-level tests with a fake asyncpg pool.
# ---------------------------------------------------------------------------


import asyncpg  # noqa: E402

from tfex_s50_multi_tf_swing.data.db_writer import OhlcvDbWriter  # noqa: E402


class _FakeConn:
    def __init__(self, captured: list[tuple[str, list[tuple[object, ...]]]]) -> None:
        self.captured = captured

    async def __aenter__(self) -> _FakeConn:
        return self

    async def __aexit__(self, *_e: object) -> None:
        return None

    def transaction(self) -> _FakeConn:
        return self

    async def executemany(self, sql: str, rows: list[tuple[object, ...]]) -> None:
        self.captured.append((sql, list(rows)))


class _FakePool:
    def __init__(self) -> None:
        self.captured: list[tuple[str, list[tuple[object, ...]]]] = []

    def acquire(self) -> _FakeConn:
        return _FakeConn(self.captured)

    async def close(self) -> None:
        return None


async def test_writer_upsert_raw_executes_sql() -> None:
    pool = _FakePool()
    writer = OhlcvDbWriter(pool=pool)
    rows = await writer.upsert_raw_frame(_raw_frame(), contract="S50M2026", timeframe="5m")
    assert rows == 1
    assert len(pool.captured) == 1
    sql, captured_rows = pool.captured[0]
    assert "INSERT INTO ohlcv_raw" in sql
    assert "ON CONFLICT" in sql
    assert captured_rows[0][1] == "S50M2026"


async def test_writer_upsert_continuous_executes_sql() -> None:
    pool = _FakePool()
    writer = OhlcvDbWriter(pool=pool)
    df = _raw_frame().with_columns(
        [
            pl.lit("S50M2026").alias("contract_at_time"),
            pl.lit(Decimal("1.0")).cast(pl.Decimal(18, 8)).alias("adjustment_factor"),
        ]
    )
    rows = await writer.upsert_continuous_frame(df, timeframe="1h")
    assert rows == 1
    sql, _captured = pool.captured[0]
    assert "INSERT INTO ohlcv_continuous" in sql


async def test_writer_raises_dbwritererror_on_postgres_error() -> None:
    class _BadConn(_FakeConn):
        async def executemany(self, *_a: object) -> None:
            raise asyncpg.PostgresError("boom")

    class _BadPool(_FakePool):
        def acquire(self) -> _BadConn:
            return _BadConn(self.captured)

    writer = OhlcvDbWriter(pool=_BadPool())
    with pytest.raises(DbWriterError):
        await writer.upsert_raw_frame(_raw_frame(), contract="S50M2026", timeframe="5m")


async def test_writer_close_is_safe() -> None:
    pool = _FakePool()
    writer = OhlcvDbWriter(pool=pool)
    await writer.close()
