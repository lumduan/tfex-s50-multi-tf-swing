"""Kill switch (ROADMAP §7.4 — TFEX hard rule #8, overrides everything).

:func:`evaluate_kill_switch` is a **pure** function over observed :class:`MarketHealth`, the
session state, and :class:`RiskConfig`. Any single trigger — abnormal spread, a latency-budget
breach, a broker disconnect / API-error spike, a market halt, the daily-loss limit, or the manual
env-flag override — engages the switch, which means *flatten every position and halt new entries*.

The **manual override is an env flag today** (``config.kill_switch_engaged`, surfaced as
``TFEX_S50_MULTI_TF_SWING_RISK_KILL_SWITCH_ENGAGED``). An **admin endpoint is deferred** until the
``api/`` package lands — Phases 3–6 added no FastAPI endpoint and Phase 7 stays ROADMAP-pure. The
returned :class:`KillSwitchState` is the typed contract a future live/API layer consumes.
"""

from __future__ import annotations

import logging

from tfex_s50_multi_tf_swing.risk.models import (
    KillSwitchState,
    KillSwitchTrigger,
    MarketHealth,
    RiskConfig,
    SessionRiskState,
)

logger = logging.getLogger(__name__)


def evaluate_kill_switch(
    health: MarketHealth,
    session_state: SessionRiskState | None,
    config: RiskConfig,
) -> KillSwitchState:
    """Evaluate every kill-switch condition and return the resulting :class:`KillSwitchState`.

    Triggers are collected in a fixed order so the output is deterministic. The daily-loss trigger
    fires on the *cumulative R* breaching the limit directly (not on the softer streak / trade-count
    halts, which pause rather than flatten). When any trigger fires, ``flatten_positions`` and
    ``halt_entries`` are both set.
    """
    triggers: list[KillSwitchTrigger] = []

    if config.kill_switch_engaged:
        triggers.append("manual")
    spread_limit = config.spread_anomaly_mult * health.median_spread
    if health.median_spread > 0.0 and health.spread > spread_limit:
        triggers.append("spread_anomaly")
    if health.latency_ms > config.latency_budget_ms:
        triggers.append("latency_breach")
    if not health.broker_connected or health.error_rate > config.max_error_rate:
        triggers.append("broker_disconnect")
    if health.market_halted:
        triggers.append("market_halt")
    if session_state is not None:
        loss_floor = -float(config.daily_loss_limit_r)
        if float(session_state.cumulative_r) <= loss_floor:
            triggers.append("daily_loss_limit")

    engaged = bool(triggers)
    if engaged:
        logger.warning("kill switch ENGAGED: %s — flatten + halt", ", ".join(triggers))
    return KillSwitchState(
        engaged=engaged,
        triggers=tuple(triggers),
        flatten_positions=engaged,
        halt_entries=engaged,
    )


__all__: list[str] = ["evaluate_kill_switch"]
