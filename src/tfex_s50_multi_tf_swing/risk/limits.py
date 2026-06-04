"""Daily & streak limits + the no-averaging-down / no-widen-stop guards (ROADMAP §7.2).

Session state is an **immutable reducer**: :func:`register_outcome` takes the current
:class:`SessionRiskState` and a closed :class:`TradeOutcome` and returns a *new* state. There is
no wall-clock and no mutation, so every limit boundary is deterministic and unit-testable. The
session day is injected via :func:`start_session`.

Two TFEX hard rules are encoded here as fail-loud guards:

* **No averaging down** (#4) — :func:`assert_no_average_down` rejects a new entry that increases
  exposure in the direction of an existing *losing* position.
* **Never widen a stop after entry** — :func:`assert_stop_not_widened` rejects a stop moved
  further from entry.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from tfex_s50_multi_tf_swing.risk.errors import RiskInputError, RiskLimitError
from tfex_s50_multi_tf_swing.risk.models import (
    OpenPosition,
    RiskConfig,
    SessionRiskState,
    TradeOutcome,
)
from tfex_s50_multi_tf_swing.signals.models import SetupDirection

logger = logging.getLogger(__name__)


def start_session(session_date: date) -> SessionRiskState:
    """Return a fresh, un-halted :class:`SessionRiskState` for ``session_date``."""
    return SessionRiskState(session_date=session_date)


def register_outcome(
    state: SessionRiskState,
    outcome: TradeOutcome,
    config: RiskConfig,
) -> SessionRiskState:
    """Fold one closed trade into the session state, returning the new state.

    Raises :class:`RiskInputError` if ``outcome.session_date`` disagrees with the state's day (the
    caller must :func:`start_session` for a new day). The session ``halted`` flag **latches**: once
    a daily-loss / streak / trade-count limit is hit it stays set for the rest of the day.
    """
    if outcome.session_date != state.session_date:
        raise RiskInputError(
            f"outcome session_date {outcome.session_date} != state {state.session_date}; "
            "start a new session for a new trading day"
        )

    cumulative_r = state.cumulative_r + outcome.r_multiple
    is_loss = outcome.r_multiple < 0
    consecutive_losses = state.consecutive_losses + 1 if is_loss else 0
    trades_today = state.trades_today + 1

    halted = state.halted
    halt_reason = state.halt_reason
    loss_floor = -Decimal(str(config.daily_loss_limit_r))
    if not halted:
        if cumulative_r <= loss_floor:
            halted, halt_reason = True, f"daily loss limit {loss_floor}R reached"
        elif consecutive_losses >= config.max_consecutive_losses:
            halted, halt_reason = True, f"{consecutive_losses} consecutive losses"
        elif trades_today >= config.max_trades_per_day:
            halted, halt_reason = True, f"daily trade-count cap {config.max_trades_per_day} reached"

    if halted and not state.halted:
        logger.info("session %s halted: %s", state.session_date, halt_reason)

    return SessionRiskState(
        session_date=state.session_date,
        cumulative_r=cumulative_r,
        consecutive_losses=consecutive_losses,
        trades_today=trades_today,
        halted=halted,
        halt_reason=halt_reason,
    )


def can_open(state: SessionRiskState, config: RiskConfig) -> tuple[bool, str | None]:
    """Return ``(allowed, reason)`` for opening a new trade this session.

    Disallowed when the session has halted, or when the trade-count cap is already met (a guard
    that also holds for a freshly-restored state that was never reduced through
    :func:`register_outcome`).
    """
    if state.halted:
        return False, state.halt_reason
    if state.trades_today >= config.max_trades_per_day:
        return False, f"daily trade-count cap {config.max_trades_per_day} reached"
    return True, None


def assert_no_average_down(
    open_position: OpenPosition,
    new_direction: SetupDirection,
    *,
    position_is_losing: bool,
) -> None:
    """Raise :class:`RiskLimitError` if a new entry would average down (TFEX hard rule #4).

    A new entry in the **same direction** as an existing **losing** position increases exposure to
    a wrong idea — strictly forbidden. Adding to a winner, or entering the opposite direction, is
    not averaging down and is allowed here.
    """
    if open_position.direction == new_direction and position_is_losing:
        raise RiskLimitError(
            f"averaging down forbidden: new {new_direction} entry into a losing "
            f"{open_position.direction} position"
        )


def assert_stop_not_widened(
    direction: SetupDirection,
    original_stop: Decimal,
    new_stop: Decimal,
) -> None:
    """Raise :class:`RiskLimitError` if ``new_stop`` is further from entry than ``original_stop``.

    For a long, the stop sits below entry, so widening means moving it *down* (``new < original``);
    for a short it sits above entry, so widening means moving it *up* (``new > original``).
    Tightening (or leaving it unchanged) is allowed.
    """
    widened = new_stop < original_stop if direction == "long" else new_stop > original_stop
    if widened:
        raise RiskLimitError(
            f"widening a {direction} stop after entry is forbidden: {original_stop} → {new_stop}"
        )


__all__: list[str] = [
    "assert_no_average_down",
    "assert_stop_not_widened",
    "can_open",
    "register_outcome",
    "start_session",
]
