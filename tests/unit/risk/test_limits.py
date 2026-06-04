"""Daily/streak limits + no-averaging-down / no-widen-stop tests (ROADMAP §7.2)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from tfex_s50_multi_tf_swing.risk.errors import RiskInputError, RiskLimitError
from tfex_s50_multi_tf_swing.risk.limits import (
    assert_no_average_down,
    assert_stop_not_widened,
    can_open,
    register_outcome,
    start_session,
)
from tfex_s50_multi_tf_swing.risk.models import (
    OpenPosition,
    RiskConfig,
    SessionRiskState,
    TradeOutcome,
)

DAY = date(2026, 6, 4)
CFG = RiskConfig()


def _outcome(r: str) -> TradeOutcome:
    return TradeOutcome(r_multiple=Decimal(r), session_date=DAY)


def test_start_session_is_fresh() -> None:
    state = start_session(DAY)
    assert state.session_date == DAY
    assert state.cumulative_r == Decimal("0")
    assert not state.halted
    assert can_open(state, CFG) == (True, None)


def test_register_outcome_wrong_date_raises() -> None:
    with pytest.raises(RiskInputError):
        register_outcome(
            start_session(DAY),
            TradeOutcome(r_multiple=Decimal("1"), session_date=date(2026, 6, 5)),
            CFG,
        )


def test_daily_loss_limit_at_boundary_vs_just_under() -> None:
    # Just under -2R: not halted.
    state = register_outcome(start_session(DAY), _outcome("-1.99"), CFG)
    assert not state.halted
    # Exactly -2R: halted.
    state = register_outcome(start_session(DAY), _outcome("-2.0"), CFG)
    assert state.halted
    assert state.halt_reason is not None and "loss limit" in state.halt_reason


def test_daily_loss_limit_accumulates() -> None:
    state = start_session(DAY)
    state = register_outcome(state, _outcome("-1.0"), CFG)
    assert not state.halted
    state = register_outcome(state, _outcome("-1.0"), CFG)
    assert state.halted


def test_consecutive_loss_limit() -> None:
    state = start_session(DAY)
    state = register_outcome(state, _outcome("-0.5"), CFG)
    state = register_outcome(state, _outcome("-0.5"), CFG)
    assert not state.halted  # only 2 in a row
    assert state.consecutive_losses == 2
    state = register_outcome(state, _outcome("-0.5"), CFG)
    assert state.halted
    assert state.halt_reason is not None and "consecutive" in state.halt_reason


def test_win_resets_consecutive_losses() -> None:
    state = start_session(DAY)
    state = register_outcome(state, _outcome("-0.5"), CFG)
    state = register_outcome(state, _outcome("-0.5"), CFG)
    state = register_outcome(state, _outcome("0.5"), CFG)  # win resets streak
    assert state.consecutive_losses == 0
    state = register_outcome(state, _outcome("-0.5"), CFG)
    state = register_outcome(state, _outcome("-0.5"), CFG)
    assert not state.halted  # only 2 in a row after the reset


def test_trade_count_cap() -> None:
    cfg = RiskConfig(max_trades_per_day=3)
    state = start_session(DAY)
    state = register_outcome(state, _outcome("0.1"), cfg)
    state = register_outcome(state, _outcome("0.1"), cfg)
    assert not state.halted
    state = register_outcome(state, _outcome("0.1"), cfg)
    assert state.halted
    assert state.halt_reason is not None and "trade-count" in state.halt_reason


def test_halt_latches() -> None:
    state = register_outcome(start_session(DAY), _outcome("-2.5"), CFG)
    assert state.halted
    reason = state.halt_reason
    # A subsequent win does not un-halt.
    state = register_outcome(state, _outcome("1.0"), CFG)
    assert state.halted
    assert state.halt_reason == reason


def test_can_open_halted_and_count_guard() -> None:
    halted = SessionRiskState(session_date=DAY, halted=True, halt_reason="stop for the day")
    assert can_open(halted, CFG) == (False, "stop for the day")
    # Not halted but trade-count already met (e.g. a restored state).
    maxed = SessionRiskState(session_date=DAY, trades_today=CFG.max_trades_per_day)
    allowed, reason = can_open(maxed, CFG)
    assert not allowed
    assert reason is not None and "trade-count" in reason


def test_no_average_down() -> None:
    pos = OpenPosition(direction="long", entry=Decimal("900"), stop=Decimal("895"))
    # Same direction into a losing position is forbidden.
    with pytest.raises(RiskLimitError):
        assert_no_average_down(pos, "long", position_is_losing=True)
    # Adding to a winner is allowed.
    assert_no_average_down(pos, "long", position_is_losing=False)
    # Opposite direction is not averaging down.
    assert_no_average_down(pos, "short", position_is_losing=True)


def test_no_widen_stop() -> None:
    # Long: moving the stop down (further from entry) widens — forbidden.
    with pytest.raises(RiskLimitError):
        assert_stop_not_widened("long", Decimal("895"), Decimal("890"))
    # Long: tightening up, or leaving unchanged, is allowed.
    assert_stop_not_widened("long", Decimal("895"), Decimal("897"))
    assert_stop_not_widened("long", Decimal("895"), Decimal("895"))
    # Short: moving the stop up widens — forbidden.
    with pytest.raises(RiskLimitError):
        assert_stop_not_widened("short", Decimal("905"), Decimal("910"))
    assert_stop_not_widened("short", Decimal("905"), Decimal("903"))
