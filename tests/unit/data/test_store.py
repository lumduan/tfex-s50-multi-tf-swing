"""Unit tests for :class:`tfex_s50_multi_tf_swing.data.store.ParquetStore`."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from tfex_s50_multi_tf_swing.data.errors import StoreError
from tfex_s50_multi_tf_swing.data.models import (
    ValidationIssue,
    ValidationReport,
)
from tfex_s50_multi_tf_swing.data.store import (
    CONTINUOUS_SCHEMA,
    RAW_SCHEMA,
    REFERENCE_SCHEMA,
    ParquetStore,
)


def _raw_frame() -> pl.DataFrame:
    start = datetime(2026, 5, 27, 2, 45, tzinfo=UTC)
    rows = []
    for i in range(5):
        t = start + timedelta(minutes=5 * i)
        rows.append(
            {
                "time": t,
                "open": Decimal(f"{800 + i:.4f}"),
                "high": Decimal(f"{801 + i:.4f}"),
                "low": Decimal(f"{799 + i:.4f}"),
                "close": Decimal(f"{800.5 + i:.4f}"),
                "volume": Decimal("1000.0000"),
            }
        )
    return pl.DataFrame(rows)


def test_paths_obey_layout(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    assert store.raw_path("S50M2026", "5m") == tmp_path / "raw" / "S50M2026" / "5m.parquet"
    assert store.continuous_path("1h") == tmp_path / "continuous" / "1h.parquet"
    assert store.reference_path("4h") == tmp_path / "continuous_reference" / "4h.parquet"
    assert store.validation_path(date(2026, 5, 27)) == tmp_path / "validation" / "2026-05-27.json"


def test_unknown_timeframe_raises(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    with pytest.raises(StoreError):
        store.raw_path("S50M2026", "1w")


def test_write_then_read_raw_roundtrip(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    df = _raw_frame()
    store.write_raw("S50M2026", "5m", df)
    read = store.read_raw("S50M2026", "5m")
    assert read.height == 5
    # contract + timeframe were injected by the store
    assert set(read.columns) == set(RAW_SCHEMA.names)
    assert read["contract"].to_list() == ["S50M2026"] * 5
    assert read["timeframe"].to_list() == ["5m"] * 5
    # Decimal precision preserved
    assert read["open"].to_list()[0] == Decimal("800.0000")


def test_write_raw_dedups_on_time(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    df = _raw_frame()
    duplicated = pl.concat([df, df.head(2)])
    store.write_raw("S50M2026", "5m", duplicated)
    read = store.read_raw("S50M2026", "5m")
    assert read.height == 5  # duplicates collapsed


def test_read_raw_missing_path_raises(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    with pytest.raises(StoreError):
        store.read_raw("S50Z2026", "5m")


def test_read_raw_if_exists_returns_none(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    assert store.read_raw_if_exists("S50Z2026", "5m") is None


def test_write_then_read_continuous_roundtrip(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    base = _raw_frame().with_columns(
        [
            pl.lit("S50M2026").alias("contract_at_time"),
            pl.lit("1.00000000").cast(pl.Decimal(18, 8)).alias("adjustment_factor"),
        ]
    )
    store.write_continuous("5m", base)
    read = store.read_continuous("5m")
    assert read.height == 5
    assert set(read.columns) == set(CONTINUOUS_SCHEMA.names)


def test_write_then_read_reference_roundtrip(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    base = _raw_frame()
    store.write_reference("5m", base)
    read = store.read_reference("5m")
    assert read.height == 5
    assert set(read.columns) == set(REFERENCE_SCHEMA.names)


def test_validation_report_roundtrip(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    report = ValidationReport(
        as_of=datetime(2026, 5, 27, 12, 0, tzinfo=UTC),
        contract="S50M2026",
        timeframe="5m",
        bar_count=100,
        missing_bars=0,
        duplicate_timestamps=0,
        abnormal_spread_bars=2,
        issues=[
            ValidationIssue(
                level="info",
                kind="abnormal_spread",
                detail="2 bars",
                count=2,
            )
        ],
    )
    store.write_validation_report(report)
    read = store.read_validation_report(date(2026, 5, 27))
    assert read == report
    assert read.is_clean  # only info-level


def test_read_missing_validation_report(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    with pytest.raises(StoreError):
        store.read_validation_report(date(2026, 1, 1))


def test_write_raw_rejects_missing_columns(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    bad = pl.DataFrame(
        {
            "time": [datetime(2026, 5, 27, 2, 45, tzinfo=UTC)],
            "close": [Decimal("800.0")],
        }
    )
    with pytest.raises(StoreError):
        store.write_raw("S50M2026", "5m", bad)


def test_write_raw_rejects_non_polars_frame(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    with pytest.raises(StoreError):
        store.write_raw("S50M2026", "5m", {"time": []})  # type: ignore[arg-type]
