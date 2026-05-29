"""Tests for the rule-based regime classifier."""

from __future__ import annotations

import polars as pl
import pytest

from tfex_s50_multi_tf_swing.features.models import FeatureConfig
from tfex_s50_multi_tf_swing.regime.errors import RegimeInputError
from tfex_s50_multi_tf_swing.regime.models import Regime, RegimeFeatures, RegimeThresholds
from tfex_s50_multi_tf_swing.regime.rules import (
    REQUIRED_COLUMNS,
    build_regime_inputs,
    classify_frame,
    classify_row,
)

from .conftest import inputs_frame, neutral, rising_ohlcv, row


def _features(**overrides: object) -> RegimeFeatures:
    return RegimeFeatures.model_validate(row(**overrides))


@pytest.mark.parametrize(
    ("features", "expected"),
    [
        (row(), "trend_up"),
        (
            row(
                ema_fast_minus_slow=-2.0,
                ema_slope_fast=-1.0,
                structure="LL",
                dist_from_vwap=-1.5,
                trend_persistence=-0.6,
            ),
            "trend_down",
        ),
        (neutral(rv_percentile=0.20, range_compression=1), "range_low_vol"),
        (neutral(rv_percentile=0.99), "panic"),
        (neutral(volume_expansion=5.0), "panic"),
        # No clear trend / not quiet / not panic -> residual high-vol range.
        (neutral(rv_percentile=0.5), "range_high_vol"),
    ],
)
def test_classify_row_branches(features: dict[str, object], expected: Regime) -> None:
    assert classify_row(RegimeFeatures.model_validate(features)) == expected


def test_panic_dominates_trend() -> None:
    """A blow-off in an otherwise trending tape is still panic."""
    feats = _features(rv_percentile=0.97)  # all trend_up signals intact
    assert classify_row(feats) == "panic"


def test_classify_frame_matches_classify_row() -> None:
    rows = [
        row(),
        row(
            ema_fast_minus_slow=-2.0,
            ema_slope_fast=-1.0,
            structure="LL",
            dist_from_vwap=-1.5,
            trend_persistence=-0.6,
        ),
        row(rv_percentile=0.2, range_compression=1),
        row(rv_percentile=0.99),
        row(volume_expansion=5.0),
        row(structure=None, dist_from_vwap=0.0, trend_persistence=0.0),
    ]
    frame_labels = classify_frame(inputs_frame(rows))["regime"].to_list()
    row_labels = [classify_row(RegimeFeatures.model_validate(r)) for r in rows]
    assert frame_labels == row_labels


def test_insufficient_lookback_is_no_trade_regime() -> None:
    """Null core inputs (early bars) fall back to the no-trade range_low_vol."""
    rows = [
        row(rv_percentile=None),
        row(range_compression=None),
        row(volume_expansion=None),
    ]
    frame = inputs_frame(rows).with_columns(
        pl.col("rv_percentile").cast(pl.Float64),
        pl.col("range_compression").cast(pl.Int64),
        pl.col("volume_expansion").cast(pl.Float64),
    )
    assert classify_frame(frame)["regime"].to_list() == ["range_low_vol"] * 3


def test_custom_thresholds_shift_panic_boundary() -> None:
    feats = RegimeFeatures.model_validate(neutral(rv_percentile=0.80))
    assert classify_row(feats) == "range_high_vol"
    lenient = RegimeThresholds(panic_rv=0.75)
    assert classify_row(feats, lenient) == "panic"


def test_classify_frame_rejects_missing_columns() -> None:
    bad = inputs_frame([row()]).drop("rv_percentile")
    with pytest.raises(RegimeInputError, match="missing columns"):
        classify_frame(bad)


def test_build_regime_inputs_end_to_end(small_config: FeatureConfig) -> None:
    inputs = build_regime_inputs(rising_ohlcv(n=80), "4h", small_config)
    assert set(REQUIRED_COLUMNS).issubset(inputs.columns)
    assert "time" in inputs.columns

    labels = classify_frame(inputs)["regime"]
    valid = {"trend_up", "trend_down", "range_low_vol", "range_high_vol", "panic"}
    assert set(labels.to_list()).issubset(valid)
    assert labels.len() == inputs.height
    # Real feature columns flow through to >1 regime, and the EMA-diff bridge ran.
    assert len(set(labels.to_list())) >= 2
    assert inputs["ema_fast_minus_slow"].null_count() < inputs.height


def test_build_regime_inputs_defaults_config() -> None:
    """``config=None`` uses FeatureConfig defaults (large lookback)."""
    inputs = build_regime_inputs(rising_ohlcv(n=300), "4h")
    assert "ema_fast_minus_slow" in inputs.columns
