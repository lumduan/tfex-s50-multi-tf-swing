"""Truth table + frame/row parity for Strategy C (liquidity-sweep reversal)."""

from __future__ import annotations

from typing import cast

import pytest

from tests.unit.signals.conftest import SWEEP_BASE, feats, frame, to_row
from tfex_s50_multi_tf_swing.signals import base, strategy_c
from tfex_s50_multi_tf_swing.signals.errors import SignalInputError
from tfex_s50_multi_tf_swing.signals.models import SignalConfig


def _direction(b: dict[str, object], **ov: object) -> str | None:
    out = strategy_c.classify_frame(frame([to_row(b, **ov)]))
    return cast("str | None", out.get_column(base.SIGNAL).to_list()[0])


def test_clean_long_reversal() -> None:
    out = strategy_c.classify_frame(frame([to_row(SWEEP_BASE)]))
    assert out.get_column(base.SIGNAL).to_list() == ["long"]
    assert out.get_column(base.STOP_REFERENCE).to_list() == [95.0]  # swing_low


def test_clean_short_reversal() -> None:
    # A swept high reversing down: below VWAP + bearish structure.
    assert _direction(SWEEP_BASE, dist_from_vwap=-0.5, structure="LL") == "short"


@pytest.mark.parametrize(
    "override",
    [
        {"regime": "trend_up"},  # regime does not whitelist C
        {"liquidity_sweep_flag": 0},  # no sweep
        {"dist_from_vwap": 0.0},  # no reclaim either side
        {"structure": "LL"},  # structure conflicts with the long reclaim
    ],
)
def test_single_gate_failure_yields_no_signal(override: dict[str, object]) -> None:
    assert _direction(SWEEP_BASE, **override) == "none"


def test_structure_shift_optional_when_disabled() -> None:
    # With the structure-shift gate off, a null/contrary structure still fires on the reclaim.
    config = SignalConfig(require_structure_shift=False)
    out = strategy_c.classify_frame(frame([to_row(SWEEP_BASE, structure=None)]), config=config)
    assert out.get_column(base.SIGNAL).to_list() == ["long"]


@pytest.mark.parametrize(
    "override",
    [
        {},
        {"dist_from_vwap": -0.5, "structure": "LL"},
        {"regime": "trend_up"},
        {"liquidity_sweep_flag": 0},
        {"structure": "LL"},
    ],
)
def test_row_matches_frame(override: dict[str, object]) -> None:
    out = strategy_c.classify_frame(frame([to_row(SWEEP_BASE, **override)]))
    frame_dir = out.get_column(base.SIGNAL).to_list()[0]
    signal = strategy_c.classify_row(feats(SWEEP_BASE, **override))
    if signal is None:
        assert frame_dir == "none"
    else:
        assert signal.direction == frame_dir
        assert signal.strategy_id == "C"
        assert signal.reasons == out.get_column(base.REASONS).to_list()[0]


def test_row_matches_frame_structure_shift_disabled() -> None:
    config = SignalConfig(require_structure_shift=False)
    row = to_row(SWEEP_BASE, structure=None)
    frame_dir = strategy_c.classify_frame(frame([row]), config=config).get_column(base.SIGNAL)[0]
    signal = strategy_c.classify_row(feats(SWEEP_BASE, structure=None), config)
    assert signal is not None
    assert signal.direction == frame_dir == "long"


def test_missing_columns_raise() -> None:
    bad = frame([to_row(SWEEP_BASE)]).drop("liquidity_sweep_flag")
    with pytest.raises(SignalInputError, match="missing columns"):
        strategy_c.classify_frame(bad)


def test_to_signals_only_fired_rows() -> None:
    rows = [to_row(SWEEP_BASE), to_row(SWEEP_BASE, liquidity_sweep_flag=0)]
    out = strategy_c.classify_frame(frame(rows))
    signals = strategy_c.to_signals(out)
    assert [s.direction for s in signals] == ["long"]
    assert signals[0].strategy_id == "C"
