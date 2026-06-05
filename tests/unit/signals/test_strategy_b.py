"""Truth table + frame/row parity for Strategy B (opening-range breakout)."""

from __future__ import annotations

from typing import cast

import pytest

from tests.unit.signals.conftest import LONG_BASE, SHORT_BASE, feats, frame, to_row
from tfex_s50_multi_tf_swing.signals import base, strategy_b
from tfex_s50_multi_tf_swing.signals.errors import SignalInputError
from tfex_s50_multi_tf_swing.signals.models import SignalConfig


def _direction(b: dict[str, object], **ov: object) -> str | None:
    out = strategy_b.classify_frame(frame([to_row(b, **ov)]))
    return cast("str | None", out.get_column(base.SIGNAL).to_list()[0])


def test_clean_long_and_short() -> None:
    long_out = strategy_b.classify_frame(frame([to_row(LONG_BASE)]))
    assert long_out.get_column(base.SIGNAL).to_list() == ["long"]
    assert long_out.get_column(base.STOP_REFERENCE).to_list() == [96.0]  # or_low_15
    assert _direction(SHORT_BASE) == "short"


@pytest.mark.parametrize(
    "override",
    [
        {"bias_direction": "neutral"},  # not HTF-aligned
        {"regime": "range_low_vol"},  # B suppressed in range_low_vol
        {"lunch_zone_flag": 1},  # lunch dead-zone
        {"close": 99.0},  # no breakout of the opening range
        {"volume_expansion": 0.5},  # no volume expansion
        {"or_low": None},  # no opposite-extreme stop
    ],
)
def test_single_gate_failure_yields_no_signal(override: dict[str, object]) -> None:
    assert _direction(LONG_BASE, **override) == "none"


@pytest.mark.parametrize(
    "base_and_override",
    [
        (LONG_BASE, {}),
        (SHORT_BASE, {}),
        (LONG_BASE, {"lunch_zone_flag": 1}),
        (LONG_BASE, {"regime": "range_low_vol"}),
        (LONG_BASE, {"close": 99.0}),
    ],
)
def test_row_matches_frame(base_and_override: tuple[dict[str, object], dict[str, object]]) -> None:
    b, override = base_and_override
    out = strategy_b.classify_frame(frame([to_row(b, **override)]))
    frame_dir = out.get_column(base.SIGNAL).to_list()[0]
    signal = strategy_b.classify_row(feats(b, **override))
    if signal is None:
        assert frame_dir == "none"
    else:
        assert signal.direction == frame_dir
        assert signal.strategy_id == "B"
        assert signal.reasons == out.get_column(base.REASONS).to_list()[0]


def test_required_columns_track_or_window() -> None:
    assert "or_high_30" in strategy_b.required_columns(SignalConfig(or_window=30))
    assert "or_high_60" in strategy_b.required_columns(SignalConfig())


def test_missing_or_window_columns_raise() -> None:
    # The default frame only carries the 15-minute opening range.
    with pytest.raises(SignalInputError, match="missing columns"):
        strategy_b.classify_frame(frame([to_row(LONG_BASE)]), config=SignalConfig(or_window=30))


def test_to_signals_only_fired_rows() -> None:
    rows = [to_row(LONG_BASE), to_row(LONG_BASE, lunch_zone_flag=1)]
    out = strategy_b.classify_frame(frame(rows))
    signals = strategy_b.to_signals(out)
    assert [s.direction for s in signals] == ["long"]
    assert signals[0].strategy_id == "B"
