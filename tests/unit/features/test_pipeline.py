"""Pipeline assembly, input validation, and the look-ahead regression test."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from tfex_s50_multi_tf_swing.data.models import Timeframe
from tfex_s50_multi_tf_swing.features.errors import FeatureInputError, InsufficientLookbackError
from tfex_s50_multi_tf_swing.features.models import FeatureConfig, feature_columns
from tfex_s50_multi_tf_swing.features.pipeline import build_aligned, build_panel

from .conftest import ohlcv


def test_panel_has_registered_columns(small_config: FeatureConfig) -> None:
    df = ohlcv(n=200, interval_minutes=5)
    panel = build_panel(df, "5m", small_config)
    expected = ["time", "timeframe", *(c.name for c in feature_columns(small_config, "5m"))]
    assert list(panel.columns) == expected
    assert panel["timeframe"].unique().to_list() == ["5m"]
    assert panel.height == df.height


def test_default_config_builds(small_config: FeatureConfig) -> None:
    # Default config needs >252 bars; confirm it runs and the 4h panel omits intraday cols.
    df = ohlcv(n=300, interval_minutes=240)
    panel = build_panel(df, "4h")
    assert "ib_high" not in panel.columns
    assert "or_high_15" not in panel.columns


def test_missing_column_raises() -> None:
    df = ohlcv(n=60, interval_minutes=5).drop("volume")
    with pytest.raises(FeatureInputError):
        build_panel(df, "5m", FeatureConfig(zscore_window=10))


def test_too_short_raises(small_config: FeatureConfig) -> None:
    df = ohlcv(n=5, interval_minutes=5)
    with pytest.raises(InsufficientLookbackError):
        build_panel(df, "5m", small_config)


def test_empty_frame_raises(small_config: FeatureConfig) -> None:
    empty = ohlcv(n=1, interval_minutes=5).clear()  # 0 rows, columns intact
    with pytest.raises(InsufficientLookbackError):
        build_panel(empty, "5m", small_config)


def test_duplicate_timestamps_raise(small_config: FeatureConfig) -> None:
    df = ohlcv(n=40, interval_minutes=5)
    dup = pl.concat([df, df.tail(1)])
    with pytest.raises(FeatureInputError):
        build_panel(dup, "5m", small_config)


def test_tz_naive_raises(small_config: FeatureConfig) -> None:
    df = ohlcv(n=40, interval_minutes=5).with_columns(pl.col("time").dt.replace_time_zone(None))
    with pytest.raises(FeatureInputError):
        build_panel(df, "5m", small_config)


def test_non_monotonic_raises(small_config: FeatureConfig) -> None:
    rows = []
    base = datetime(2026, 1, 5, 2, 45, tzinfo=UTC)
    order = list(range(40))
    order[10], order[11] = order[11], order[10]  # swap two timestamps out of order
    for i in order:
        rows.append(
            {
                "time": base + timedelta(minutes=5 * i),
                "open": Decimal("800.0000"),
                "high": Decimal("801.0000"),
                "low": Decimal("799.0000"),
                "close": Decimal("800.0000"),
                "volume": Decimal("1000.0000"),
            }
        )
    df = pl.DataFrame(rows).with_columns(pl.col("time").dt.replace_time_zone("UTC"))
    with pytest.raises(FeatureInputError):
        build_panel(df, "5m", small_config)


def test_no_lookahead_prefix_equals_full(small_config: FeatureConfig) -> None:
    """The gold-standard causality check.

    Features computed on a truncated prefix must equal features computed on the
    full series for every overlapping row. If any feature peeked at a future
    bar, appending more data would change a past value and this fails.
    """
    df = ohlcv(n=140, interval_minutes=5)
    full = build_panel(df, "5m", small_config)
    for k in (60, 90, 120):
        prefix = build_panel(df.head(k), "5m", small_config)
        assert_frame_equal(prefix, full.head(k), check_exact=False)


def test_build_aligned_widens_base(small_config: FeatureConfig) -> None:
    panels: dict[Timeframe, pl.DataFrame] = {
        "5m": build_panel(ohlcv(n=400, interval_minutes=5), "5m", small_config),
        "1h": build_panel(ohlcv(n=120, interval_minutes=60), "1h", small_config),
        "4h": build_panel(ohlcv(n=120, interval_minutes=240), "4h", small_config),
    }
    aligned = build_aligned(panels, base_timeframe="5m")
    assert aligned.height == panels["5m"].height
    assert any(c.startswith("1h_") for c in aligned.columns)
    assert any(c.startswith("4h_") for c in aligned.columns)


def test_build_aligned_missing_base_raises(small_config: FeatureConfig) -> None:
    panels: dict[Timeframe, pl.DataFrame] = {
        "1h": build_panel(ohlcv(n=120, interval_minutes=60), "1h", small_config)
    }
    with pytest.raises(FeatureInputError):
        build_aligned(panels, base_timeframe="5m")
