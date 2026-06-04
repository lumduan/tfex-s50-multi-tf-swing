"""Source-agnostic loader tests (ROADMAP §8.1) — Parquet snapshot, typed error, exec bars."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from tfex_s50_multi_tf_swing.backtest.data_source import (
    build_execution_bars,
    load_continuous_frames,
)
from tfex_s50_multi_tf_swing.backtest.errors import WalkForwardDataError
from tfex_s50_multi_tf_swing.data.store import ParquetStore


def _continuous(n: int) -> pl.DataFrame:
    base = datetime(2026, 1, 5, 3, 0, tzinfo=UTC)
    return pl.DataFrame(
        {
            "time": [base + timedelta(hours=i) for i in range(n)],
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1000.0] * n,
            "contract_at_time": ["S50Z2026"] * n,
            "adjustment_factor": [1.0] * n,
        }
    )


def test_load_continuous_frames_success(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    store.write_continuous("5m", _continuous(20))
    store.write_continuous("1h", _continuous(10))
    frames = load_continuous_frames(store)
    assert set(frames) == {"5m", "1h"}
    assert frames["5m"].height == 20


def test_load_continuous_frames_missing_raises(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    with pytest.raises(WalkForwardDataError, match="never tvkit"):
        load_continuous_frames(store)


def test_load_continuous_frames_empty_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ParquetStore(tmp_path)
    empty = pl.DataFrame({"time": []}, schema={"time": pl.Datetime("us", "UTC")})
    monkeypatch.setattr(store, "read_continuous", lambda _tf: empty)
    with pytest.raises(WalkForwardDataError, match="empty"):
        load_continuous_frames(store)


def test_load_continuous_frames_with_4h_missing_raises(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    store.write_continuous("5m", _continuous(20))
    store.write_continuous("1h", _continuous(10))
    with pytest.raises(WalkForwardDataError):
        load_continuous_frames(store, with_4h=True)


def test_build_execution_bars_appends_atr() -> None:
    bars = build_execution_bars(_continuous(30))
    assert "atr" in bars.columns
    assert bars.schema["open"] == pl.Float64
