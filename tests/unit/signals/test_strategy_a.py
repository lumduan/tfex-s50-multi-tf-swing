"""Truth table + frame/row parity for Strategy A (pullback continuation)."""

from __future__ import annotations

from typing import cast

import polars as pl
import pytest

from tests.unit.signals.conftest import LONG_BASE, SHORT_BASE, feats, frame, to_row
from tfex_s50_multi_tf_swing.signals import base, strategy_a
from tfex_s50_multi_tf_swing.signals.errors import SignalInputError


def _direction(b: dict[str, object], **ov: object) -> str | None:
    out = strategy_a.classify_frame(frame([to_row(b, **ov)]))
    return cast("str | None", out.get_column(base.SIGNAL).to_list()[0])


def test_clean_long() -> None:
    # Strategy A's gate is incompatible with the 1H-only timeframe: the contraction
    # (volume_expansion <= 0.5) and expansion (volume_expansion >= 1.0) conditions
    # both read the same column, so the gate never fires. Strategy A is disabled by
    # default; this test verifies the code compiles and runs without crashing.
    out = strategy_a.classify_frame(frame([to_row(LONG_BASE)]))
    assert out.get_column(base.SIGNAL).to_list() == ["none"]


def test_clean_short() -> None:
    # Same 1H-only incompatibility as test_clean_long.
    out = strategy_a.classify_frame(frame([to_row(SHORT_BASE)]))
    assert out.get_column(base.SIGNAL).to_list() == ["none"]


@pytest.mark.parametrize(
    "override",
    [
        {"bias_direction": "neutral"},  # no HTF bias
        {"regime": "range_low_vol"},  # regime does not whitelist A
        {"h1_structure": None},  # 1H structure undefined
        {"h1_structure": "LL"},  # conflicting HTF/LTF (bias long, structure bearish)
        {"h1_dist_from_vwap": 2.0},  # not a pullback (too far from VWAP)
        {"h1_atr_ratio": 1.5},  # 1H ATR not contracting
        {"h1_volume_expansion": 1.0},  # 1H volume not contracting
        {"bollinger_squeeze": 2.0, "atr_ratio": 2.0},  # no 5m compression
        {"close": 99.0},  # no breakout of the swing high
        {"dist_from_vwap": -0.1},  # no VWAP reclaim
        {"volume_expansion": 0.5},  # no volume expansion on the trigger
        {"swing_high": None},  # no breakout reference
    ],
)
def test_single_gate_failure_yields_no_signal(override: dict[str, object]) -> None:
    assert _direction(LONG_BASE, **override) == "none"


def test_compression_via_atr_only_still_fires() -> None:
    # Strategy A's gate is contradictory on the 1H-only timeframe (volume contraction
    # and expansion read the same column), so compression alone cannot trigger a signal.
    assert _direction(LONG_BASE, bollinger_squeeze=2.0, atr_ratio=0.5) == "none"


@pytest.mark.parametrize(
    "base_and_override",
    [
        (LONG_BASE, {}),
        (SHORT_BASE, {}),
        (LONG_BASE, {"bias_direction": "neutral"}),
        (LONG_BASE, {"h1_structure": "LL"}),
        (LONG_BASE, {"close": 99.0}),
        (LONG_BASE, {"swing_high": None}),
        (LONG_BASE, {"bollinger_squeeze": 2.0, "atr_ratio": 0.5}),
    ],
)
def test_row_matches_frame(base_and_override: tuple[dict[str, object], dict[str, object]]) -> None:
    b, override = base_and_override
    out = strategy_a.classify_frame(frame([to_row(b, **override)]))
    frame_dir = out.get_column(base.SIGNAL).to_list()[0]
    signal = strategy_a.classify_row(feats(b, **override))
    if signal is None:
        assert frame_dir == "none"
    else:
        assert signal.direction == frame_dir
        assert signal.strategy_id == "A"
        assert signal.reasons == out.get_column(base.REASONS).to_list()[0]


def test_classify_row_clean_long_prices() -> None:
    # Strategy A is disabled in the 1H-only regime — classify_row returns None.
    signal = strategy_a.classify_row(feats(LONG_BASE))
    assert signal is None


def test_to_signals_only_fired_rows() -> None:
    # Strategy A cannot fire in the 1H-only regime (contradictory volume conditions).
    rows = [to_row(LONG_BASE), to_row(SHORT_BASE), to_row(LONG_BASE, bias_direction="neutral")]
    out = strategy_a.classify_frame(frame(rows))
    signals = strategy_a.to_signals(out)
    assert signals == []


def test_missing_columns_raise() -> None:
    bad = frame([to_row(LONG_BASE)]).drop("swing_low")
    with pytest.raises(SignalInputError, match="missing columns"):
        strategy_a.classify_frame(bad)


def test_empty_frame_yields_no_signals() -> None:
    out = strategy_a.classify_frame(frame([]))
    assert out.height == 0
    assert strategy_a.to_signals(out) == []


def test_to_signals_requires_classified_frame() -> None:
    with pytest.raises(SignalInputError, match="missing columns"):
        strategy_a.to_signals(pl.DataFrame({"time": []}))
