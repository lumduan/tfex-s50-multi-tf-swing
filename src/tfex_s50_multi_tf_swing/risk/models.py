"""Type contracts for the risk engine (ROADMAP §7).

Money quantities are :class:`~decimal.Decimal` end-to-end (equity, risk amount, stop distance,
the S50 multiplier) — they are real THB that can reach the gateway boundary, where floats are
forbidden. Statistical inputs (``rv_percentile``, spread, latency) stay :class:`float`: they are
internal quantities that never cross that boundary, exactly as the Phase 2/3 layers established.
The volatility scale factor is a quantised :class:`~decimal.Decimal` so the sizing computation
stays in one numeric domain.

A kill-switch *trip* and a session *halt* are modelled as typed **state**
(:class:`KillSwitchState` / :class:`SessionRiskState`), not exceptions — halting is the engine
working as designed.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from tfex_s50_multi_tf_swing.regime.models import Regime
from tfex_s50_multi_tf_swing.signals.models import SetupDirection

DeploymentStage = Literal["paper", "micro_live", "validated", "scale"]
"""The capital-deployment ladder rungs (ROADMAP §7.5)."""

DEPLOYMENT_STAGES: tuple[DeploymentStage, ...] = get_args(DeploymentStage)
"""Tuple of every :data:`DeploymentStage`, for iteration / parametrised tests."""

KillSwitchTrigger = Literal[
    "spread_anomaly",
    "latency_breach",
    "broker_disconnect",
    "market_halt",
    "daily_loss_limit",
    "manual",
]
"""Why the kill switch tripped (ROADMAP §7.4). ``manual`` is the env-flag override."""

KILL_SWITCH_TRIGGERS: tuple[KillSwitchTrigger, ...] = get_args(KillSwitchTrigger)
"""Tuple of every :data:`KillSwitchTrigger`."""


class RiskConfig(BaseModel):
    """Risk-engine knobs (frozen + bounded so an out-of-range env override fails at load).

    Every default reproduces the documented :mod:`risk-engine` spec, so an unset environment is a
    no-op. ``risk_per_trade_pct`` is the fraction of equity risked per trade (1 % default);
    ``daily_loss_limit_r`` halts the session at ``-2R`` cumulative; the streak / trade-count caps
    prevent tilt. ``high_vol_size_factor`` halves size above ``high_vol_percentile``;
    ``panic_no_trade`` forces no-trade in the panic regime. The kill-switch budgets and the ladder
    contract caps live here too — no magic number is allowed at a call site.
    """

    model_config = ConfigDict(frozen=True)

    # §7.1 sizing.
    risk_per_trade_pct: float = Field(default=0.01, gt=0.0, le=1.0)

    # §7.2 daily & streak limits.
    daily_loss_limit_r: float = Field(default=2.0, gt=0.0)
    max_consecutive_losses: int = Field(default=3, ge=1)
    max_trades_per_day: int = Field(default=6, ge=1)

    # §7.3 volatility scaling.
    high_vol_percentile: float = Field(default=0.70, ge=0.0, le=1.0)
    high_vol_size_factor: float = Field(default=0.5, ge=0.0, le=1.0)
    panic_no_trade: bool = True

    # §7.4 kill switch (budgets + manual override).
    kill_switch_engaged: bool = False
    spread_anomaly_mult: float = Field(default=5.0, gt=0.0)
    latency_budget_ms: float = Field(default=500.0, gt=0.0)
    max_error_rate: float = Field(default=0.10, ge=0.0, le=1.0)

    # §7.5 capital-deployment ladder.
    deployment_stage: DeploymentStage = "paper"
    micro_live_max_contracts: int = Field(default=1, ge=0)
    validated_max_contracts: int = Field(default=2, ge=0)
    scale_max_contracts: int = Field(default=4, ge=0)
    validated_min_months_live: float = Field(default=6.0, ge=0.0)
    scale_min_months_live: float = Field(default=12.0, ge=0.0)


class PositionSizeRequest(BaseModel):
    """Inputs to :func:`~tfex_s50_multi_tf_swing.risk.sizing.compute_position_size`.

    ``stop_distance_points`` is ``abs(entry - stop)`` in index points, derived by the caller from
    a :class:`~tfex_s50_multi_tf_swing.signals.models.SetupSignal`
    (``trigger_price - stop_reference``) or an execution
    :class:`~tfex_s50_multi_tf_swing.execution.models.Trade`. Both are Decimal (money). The
    optional ``rv_percentile`` / ``regime`` drive volatility scaling.
    """

    model_config = ConfigDict(frozen=True)

    equity: Decimal
    stop_distance_points: Decimal
    rv_percentile: float | None = Field(default=None, ge=0.0, le=1.0)
    regime: Regime | None = None


class PositionSizeResult(BaseModel):
    """Output of :func:`~tfex_s50_multi_tf_swing.risk.sizing.compute_position_size`.

    ``contracts`` is the floored, tradable whole-contract count (``0`` ⇒ no trade).
    ``raw_contracts`` is the pre-floor quantity for auditing; ``scale_factor`` is the applied
    volatility multiplier.
    """

    model_config = ConfigDict(frozen=True)

    contracts: int = Field(ge=0)
    risk_amount: Decimal
    scale_factor: Decimal
    raw_contracts: Decimal
    reasons: list[str] = Field(default_factory=list)


class TradeOutcome(BaseModel):
    """One closed trade's result, fed to the session reducer.

    ``r_multiple`` is signed (negative = loss). ``session_date`` keys the trade to a trading day so
    the reducer is deterministic without reading the wall clock.
    """

    model_config = ConfigDict(frozen=True)

    r_multiple: Decimal
    session_date: date


class SessionRiskState(BaseModel):
    """Per-session risk state (the reducer's immutable accumulator).

    ``halted`` latches once a daily-loss / streak / trade-count limit is breached; ``halt_reason``
    records which. A fresh session starts via
    :func:`~tfex_s50_multi_tf_swing.risk.limits.start_session`.
    """

    model_config = ConfigDict(frozen=True)

    session_date: date
    cumulative_r: Decimal = Field(default=Decimal("0"))
    consecutive_losses: int = Field(default=0, ge=0)
    trades_today: int = Field(default=0, ge=0)
    halted: bool = False
    halt_reason: str | None = None


class OpenPosition(BaseModel):
    """An existing open position, for the no-averaging-down guard."""

    model_config = ConfigDict(frozen=True)

    direction: SetupDirection
    entry: Decimal
    stop: Decimal


class LadderEvidence(BaseModel):
    """Statistical evidence gating a ladder step-up (ROADMAP §7.5).

    These inputs are produced by Phase 9 (paper) / Phase 10 (live); they are **data-gated** today
    (no live history exists yet). The default — no months live, expectancy not yet stable — keeps
    the ladder conservative, so an unproven strategy never sizes above micro-live.
    """

    model_config = ConfigDict(frozen=True)

    months_live: float = Field(default=0.0, ge=0.0)
    expectancy_stable: bool = False
    drawdown_within_budget: bool = True


class MarketHealth(BaseModel):
    """Observed market / broker health for the kill switch (ROADMAP §7.4).

    Spread is a proxy (e.g. the bar range or quoted bid/ask gap); ``median_spread`` is its rolling
    median. ``latency_ms`` is the most recent signal→order latency, ``error_rate`` the fraction of
    failed broker / data requests in the window. Thresholds live in :class:`RiskConfig`.
    """

    model_config = ConfigDict(frozen=True)

    spread: float = Field(default=0.0, ge=0.0)
    median_spread: float = Field(default=0.0, ge=0.0)
    latency_ms: float = Field(default=0.0, ge=0.0)
    error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    broker_connected: bool = True
    market_halted: bool = False


class KillSwitchState(BaseModel):
    """Result of :func:`~tfex_s50_multi_tf_swing.risk.killswitch.evaluate_kill_switch`.

    When ``engaged`` is True the engine must flatten every open position and halt new entries —
    the kill switch overrides everything (TFEX hard rule #8). ``triggers`` lists every condition
    that tripped (there can be more than one).
    """

    model_config = ConfigDict(frozen=True)

    engaged: bool
    triggers: tuple[KillSwitchTrigger, ...] = ()
    flatten_positions: bool = False
    halt_entries: bool = False


class RiskDecision(BaseModel):
    """The risk engine's verdict for one candidate entry (ROADMAP §7).

    ``allow_entry`` is True only when the kill switch is clear, the session is open, the regime
    permits trading, and the sized contract count is ≥ 1. ``contracts`` is the final, ladder-capped
    size. ``kill_switch`` is always carried so a caller can act on a flatten/halt directive even
    when no entry was requested.
    """

    model_config = ConfigDict(frozen=True)

    allow_entry: bool
    contracts: int = Field(ge=0)
    kill_switch: KillSwitchState
    size_result: PositionSizeResult | None = None
    reasons: list[str] = Field(default_factory=list)


__all__: list[str] = [
    "DEPLOYMENT_STAGES",
    "KILL_SWITCH_TRIGGERS",
    "DeploymentStage",
    "KillSwitchState",
    "KillSwitchTrigger",
    "LadderEvidence",
    "MarketHealth",
    "OpenPosition",
    "PositionSizeRequest",
    "PositionSizeResult",
    "RiskConfig",
    "RiskDecision",
    "SessionRiskState",
    "TradeOutcome",
]
