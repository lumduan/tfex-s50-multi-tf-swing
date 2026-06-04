"""Risk-decision orchestrator (ROADMAP §7).

:func:`evaluate_entry` composes the Phase-7 building blocks into one guarded verdict for a
candidate entry, in strict precedence:

1. **Kill switch first** — if engaged, no entry, flatten + halt (TFEX hard rule #8 overrides
   everything).
2. **Session limits** — a halted session (daily-loss / streak / trade-count) blocks new entries.
3. **Position sizing** — risk-budget sizing with regime / volatility scaling baked in (a no-trade
   regime sizes to 0).
4. **Ladder cap** — the contract count is capped by the deployment stage + evidence.

It is a **pure, deterministic** function and is **not** wired into ``backtest/`` or ``live/`` —
Phase 8 will drive it. This keeps ``risk/`` a leaf that imports nothing downstream.
"""

from __future__ import annotations

import logging

from tfex_s50_multi_tf_swing.risk.killswitch import evaluate_kill_switch
from tfex_s50_multi_tf_swing.risk.ladder import max_contracts_for_stage
from tfex_s50_multi_tf_swing.risk.limits import can_open
from tfex_s50_multi_tf_swing.risk.models import (
    LadderEvidence,
    MarketHealth,
    PositionSizeRequest,
    RiskConfig,
    RiskDecision,
    SessionRiskState,
)
from tfex_s50_multi_tf_swing.risk.sizing import compute_position_size

logger = logging.getLogger(__name__)


def evaluate_entry(
    *,
    request: PositionSizeRequest,
    session_state: SessionRiskState,
    config: RiskConfig,
    market_health: MarketHealth | None = None,
    evidence: LadderEvidence | None = None,
) -> RiskDecision:
    """Return the risk engine's :class:`RiskDecision` for one candidate entry.

    Raises :class:`~tfex_s50_multi_tf_swing.risk.errors.RiskInputError` (via
    :func:`compute_position_size`) for a non-positive equity / stop distance — those are bad inputs,
    not no-trade states. Every other gate degrades to a no-entry decision that still carries the
    :class:`~tfex_s50_multi_tf_swing.risk.models.KillSwitchState` (so a caller can honour a flatten
    directive even when no entry was requested).
    """
    health = market_health if market_health is not None else MarketHealth()
    ladder_evidence = evidence if evidence is not None else LadderEvidence()

    kill_switch = evaluate_kill_switch(health, session_state, config)
    if kill_switch.engaged:
        return RiskDecision(
            allow_entry=False,
            contracts=0,
            kill_switch=kill_switch,
            reasons=[f"kill switch engaged: {', '.join(kill_switch.triggers)}"],
        )

    allowed, halt_reason = can_open(session_state, config)
    if not allowed:
        return RiskDecision(
            allow_entry=False,
            contracts=0,
            kill_switch=kill_switch,
            reasons=[halt_reason or "session closed to new entries"],
        )

    size_result = compute_position_size(request, config)
    cap = max_contracts_for_stage(config.deployment_stage, ladder_evidence, config)
    contracts = min(size_result.contracts, cap)

    reasons = list(size_result.reasons)
    if cap < size_result.contracts:
        reasons.append(f"ladder cap ({config.deployment_stage}) → {cap} contract(s)")

    allow_entry = contracts >= 1
    if not allow_entry and "sub-1-contract → no trade" not in reasons:
        reasons.append("no tradable size after caps")

    logger.debug(
        "risk decision: allow=%s contracts=%d (sized=%d cap=%d)",
        allow_entry,
        contracts,
        size_result.contracts,
        cap,
    )
    return RiskDecision(
        allow_entry=allow_entry,
        contracts=contracts,
        kill_switch=kill_switch,
        size_result=size_result,
        reasons=reasons,
    )


__all__: list[str] = ["evaluate_entry"]
