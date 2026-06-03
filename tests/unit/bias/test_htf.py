"""Tests for the 4H bias classifier (`bias/htf.py`).

Each gate is exercised on a hand-built bias-input frame so the composition is deterministic.
The scalar :func:`classify_row` is asserted to agree with the vectorised
:func:`classify_frame` row-for-row, and the :func:`build_bias_inputs` bridge is smoke-tested
end-to-end on a synthetic continuous frame.
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.unit.bias.conftest import (
    inputs_frame,
    long_row,
    make_features,
    rising_ohlcv,
    short_row,
)
from tfex_s50_multi_tf_swing.bias.errors import BiasInputError
from tfex_s50_multi_tf_swing.bias.htf import (
    REQUIRED_COLUMNS,
    build_bias_inputs,
    classify_frame,
    classify_row,
    to_signals,
)
from tfex_s50_multi_tf_swing.bias.models import BIAS_DIRECTIONS, BiasConfig


def _classify(rows: list[dict[str, object]], *, config: BiasConfig | None = None) -> list[str]:
    out = classify_frame(inputs_frame(rows), config=config)
    return out["bias_direction"].to_list()


def test_clean_long_and_short() -> None:
    assert _classify([long_row()]) == ["long"]
    assert _classify([short_row()]) == ["short"]


def test_long_reasons_are_all_long_plus_regime_ok() -> None:
    out = classify_frame(inputs_frame([long_row()]))
    reasons = out["bias_reasons"].to_list()[0]
    assert reasons == [
        "ema_fast>ema_slow (long)",
        "slope>0 (long)",
        "structure HH/HL (long)",
        "price>vwap (long)",
        "regime trend_up (ok)",
    ]


@pytest.mark.parametrize(
    "override",
    [
        {"ema_fast_minus_slow": 0.0},  # tie EMA
        {"ema_slope_fast": 0.0},  # flat slope
        {"structure": None},  # null structure
        {"structure": "LL"},  # structure disagrees with the rest (conflict)
        {"dist_from_vwap": 0.0},  # price at vwap
    ],
)
def test_single_gate_failure_yields_neutral(override: dict[str, object]) -> None:
    assert _classify([long_row(**override)]) == ["neutral"]


@pytest.mark.parametrize("regime", ["panic", "range_low_vol"])
def test_no_trade_regime_vetoes_to_neutral(regime: str) -> None:
    out = classify_frame(inputs_frame([long_row(regime=regime)]))
    assert out["bias_direction"].to_list() == ["neutral"]
    assert f"regime {regime} (veto)" in out["bias_reasons"].to_list()[0]


def test_healthy_high_vol_regime_is_not_vetoed() -> None:
    # range_high_vol is tradeable, so a fully-aligned long survives.
    assert _classify([long_row(regime="range_high_vol")]) == ["long"]


def test_slope_deadband_suppresses_weak_slope() -> None:
    config = BiasConfig(slope_deadband=0.5)
    assert _classify([long_row(ema_slope_fast=0.3)], config=config) == ["neutral"]
    assert _classify([long_row(ema_slope_fast=1.0)], config=config) == ["long"]


def test_vwap_deadband_suppresses_weak_distance() -> None:
    config = BiasConfig(vwap_deadband=1.0)
    assert _classify([long_row(dist_from_vwap=0.5)], config=config) == ["neutral"]
    assert _classify([long_row(dist_from_vwap=2.0)], config=config) == ["long"]


def test_conflicting_gates_record_reasons() -> None:
    # Slope says long, structure says short → neutral, both reasons present.
    out = classify_frame(inputs_frame([long_row(structure="LL")]))
    reasons = out["bias_reasons"].to_list()[0]
    assert out["bias_direction"].to_list() == ["neutral"]
    assert "slope>0 (long)" in reasons
    assert "structure LH/LL (short)" in reasons


def test_null_core_inputs_never_directional() -> None:
    row = long_row(
        ema_fast_minus_slow=None, ema_slope_fast=None, dist_from_vwap=None, structure=None
    )
    assert _classify([row]) == ["neutral"]


def test_missing_columns_raise() -> None:
    bad = inputs_frame([long_row()]).drop("structure")
    with pytest.raises(BiasInputError, match="missing columns"):
        classify_frame(bad)


def test_empty_frame_yields_no_rows() -> None:
    empty = pl.DataFrame(schema={c: pl.Float64 for c in REQUIRED_COLUMNS}).with_columns(
        pl.col("structure").cast(pl.Utf8), pl.col("regime").cast(pl.Utf8)
    )
    out = classify_frame(empty)
    assert out.height == 0
    assert to_signals(out) == []


def test_to_signals_one_per_bar() -> None:
    rows = [long_row(), short_row(), long_row(regime="panic")]
    out = classify_frame(inputs_frame(rows))
    signals = to_signals(out)
    assert [s.direction for s in signals] == ["long", "short", "neutral"]
    assert len(signals) == out.height


def test_to_signals_requires_classified_frame() -> None:
    with pytest.raises(BiasInputError, match="missing columns"):
        to_signals(inputs_frame([long_row()]))


@pytest.mark.parametrize(
    "override",
    [
        {},
        {
            "ema_fast_minus_slow": -2.0,
            "ema_slope_fast": -1.0,
            "structure": "LH",
            "dist_from_vwap": -1.0,
            "regime": "trend_down",
        },
        {"ema_fast_minus_slow": 0.0},  # EMA tie → scalar neutral reason branch
        {"structure": None},
        {"ema_slope_fast": 0.0},
        {"regime": "panic"},
        {"regime": "range_low_vol"},
        {"structure": "LL"},
    ],
)
def test_row_matches_frame(override: dict[str, object]) -> None:
    config = BiasConfig()
    rows = [long_row(**override)]
    frame_out = classify_frame(inputs_frame(rows), config=config)
    features = make_features(**override)
    signal = classify_row(features, config)
    assert signal.direction == frame_out["bias_direction"].to_list()[0]
    assert signal.reasons == frame_out["bias_reasons"].to_list()[0]


def test_row_matches_frame_with_deadband() -> None:
    config = BiasConfig(slope_deadband=0.5, vwap_deadband=0.5)
    rows = [long_row(ema_slope_fast=0.3, dist_from_vwap=0.4)]
    frame_out = classify_frame(inputs_frame(rows), config=config)
    signal = classify_row(make_features(ema_slope_fast=0.3, dist_from_vwap=0.4), config)
    assert signal.direction == "neutral" == frame_out["bias_direction"].to_list()[0]
    assert signal.reasons == frame_out["bias_reasons"].to_list()[0]


def test_default_config_used_when_none() -> None:
    # classify_row with no config falls back to BiasConfig() defaults.
    assert classify_row(make_features()).direction == "long"


def test_build_bias_inputs_bridge(small_config: object) -> None:
    inputs = build_bias_inputs(rising_ohlcv(), "4h", feature_config=small_config)  # type: ignore[arg-type]
    assert set(inputs.columns) >= set(REQUIRED_COLUMNS)
    out = classify_frame(inputs)
    directions = set(out["bias_direction"].to_list())
    assert directions <= set(BIAS_DIRECTIONS)
    assert out["bias_direction"].null_count() == 0
    assert out.height == rising_ohlcv().height
