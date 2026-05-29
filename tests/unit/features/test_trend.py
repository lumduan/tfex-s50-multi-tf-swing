"""§2.1 trend feature tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import polars as pl

from tfex_s50_multi_tf_swing.features.models import FeatureConfig
from tfex_s50_multi_tf_swing.features.trend import add_trend

from .conftest import as_floats, working_frame


def _frame(highs: list[float], lows: list[float], closes: list[float]) -> pl.DataFrame:
    start = datetime(2026, 1, 5, 2, 45, tzinfo=UTC)
    rows = [
        {
            "time": start + timedelta(minutes=5 * i),
            "open": Decimal(f"{closes[i]:.4f}"),
            "high": Decimal(f"{highs[i]:.4f}"),
            "low": Decimal(f"{lows[i]:.4f}"),
            "close": Decimal(f"{closes[i]:.4f}"),
            "volume": Decimal("1000.0000"),
        }
        for i in range(len(closes))
    ]
    return pl.DataFrame(rows).with_columns(pl.col("time").dt.replace_time_zone("UTC"))


def test_ema_slope_positive_on_uptrend(small_config: FeatureConfig) -> None:
    n = 40
    closes = [800.0 + i for i in range(n)]
    df = _frame([c + 1 for c in closes], [c - 1 for c in closes], closes)
    out = add_trend(working_frame(df, small_config), small_config)
    assert "ema_slope_5" in out.columns
    slope = as_floats(out["ema_slope_5"].drop_nulls().to_list())
    assert slope[-1] > 0  # rising market -> positive ATR-normalised slope


def test_dist_from_vwap_sign(small_config: FeatureConfig) -> None:
    n = 40
    closes = [800.0 + i for i in range(n)]
    df = _frame([c + 1 for c in closes], [c - 1 for c in closes], closes)
    out = add_trend(working_frame(df, small_config), small_config)
    # In a monotonic rise the close sits above the session VWAP -> positive distance.
    assert as_floats(out["dist_from_vwap"].drop_nulls().to_list())[-1] > 0


def test_structure_higher_high(small_config: FeatureConfig) -> None:
    # Two ascending swing-high peaks (5 then 7) confirmed with lookback=2.
    highs = [3, 4, 5, 4, 3, 6, 7, 6, 5, 4, 3, 2]
    lows = [5, 4, 3, 4, 5, 2, 1, 2, 3, 4, 5, 6]
    closes = [(h + lo) / 2 for h, lo in zip(highs, lows, strict=True)]
    df = _frame([float(h) for h in highs], [float(lo) for lo in lows], closes)
    out = add_trend(working_frame(df, small_config), small_config)
    structure = out["structure"].to_list()
    assert "HH" in structure  # second (higher) high confirmed -> HH


def test_structure_lower_high(small_config: FeatureConfig) -> None:
    # Two well-separated swing-high peaks (9 at idx2, then a lower 8 at idx8) so
    # each is the max of its own ±2 window with lookback=2 -> the latter is a LH.
    highs = [5, 6, 9, 6, 5, 4, 4, 6, 8, 6, 5, 4]
    lows = [4, 5, 8, 5, 4, 3, 3, 5, 7, 5, 4, 3]
    closes = [(h + lo) / 2 for h, lo in zip(highs, lows, strict=True)]
    df = _frame([float(h) for h in highs], [float(lo) for lo in lows], closes)
    out = add_trend(working_frame(df, small_config), small_config)
    assert "LH" in out["structure"].to_list()
