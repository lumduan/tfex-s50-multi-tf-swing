"""FeatureStore round-trip and schema-enforcement tests."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from tfex_s50_multi_tf_swing.data.models import Timeframe
from tfex_s50_multi_tf_swing.features.errors import FeatureSchemaError
from tfex_s50_multi_tf_swing.features.models import FeatureConfig
from tfex_s50_multi_tf_swing.features.pipeline import build_aligned, build_panel
from tfex_s50_multi_tf_swing.features.store import FeatureStore

from .conftest import ohlcv


def test_panel_round_trip(tmp_path: Path, small_config: FeatureConfig) -> None:
    store = FeatureStore(tmp_path, small_config)
    panel = build_panel(ohlcv(n=120, interval_minutes=5), "5m", small_config)
    path = store.write_panel("5m", panel)
    assert path.exists()
    back = store.read_panel("5m")
    assert back.columns == panel.columns
    assert back.height == panel.height


def test_aligned_round_trip(tmp_path: Path, small_config: FeatureConfig) -> None:
    store = FeatureStore(tmp_path, small_config)
    panels: dict[Timeframe, pl.DataFrame] = {
        "5m": build_panel(ohlcv(n=400, interval_minutes=5), "5m", small_config),
        "4h": build_panel(ohlcv(n=120, interval_minutes=240), "4h", small_config),
    }
    aligned = build_aligned(panels, base_timeframe="5m")
    store.write_aligned(aligned, "5m")
    back = store.read_aligned("5m")
    assert back.height == aligned.height
    assert "4h_atr_ratio" in back.columns


def test_write_panel_rejects_bad_schema(tmp_path: Path, small_config: FeatureConfig) -> None:
    store = FeatureStore(tmp_path, small_config)
    bad = pl.DataFrame({"time": [], "timeframe": []})
    with pytest.raises(FeatureSchemaError):
        store.write_panel("5m", bad)


def test_read_missing_panel_raises(tmp_path: Path, small_config: FeatureConfig) -> None:
    store = FeatureStore(tmp_path, small_config)
    assert store.base_dir == tmp_path
    with pytest.raises(FeatureSchemaError):
        store.read_panel("1h")


def test_write_aligned_requires_time(tmp_path: Path, small_config: FeatureConfig) -> None:
    store = FeatureStore(tmp_path, small_config)
    with pytest.raises(FeatureSchemaError):
        store.write_aligned(pl.DataFrame({"x": [1.0]}), "5m")


def test_read_missing_aligned_raises(tmp_path: Path, small_config: FeatureConfig) -> None:
    store = FeatureStore(tmp_path, small_config)
    with pytest.raises(FeatureSchemaError):
        store.read_aligned("5m")
