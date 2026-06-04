"""Risk engine (ROADMAP Phase 7).

Turns the Phase-5 *sizing-ready* outputs (``signals.SetupSignal`` / ``execution.Trade``) into
**contract-sized, risk-guarded decisions**: position sizing on the 200-THB/point S50 multiplier,
daily-loss / streak / trade-count limits, the no-averaging-down + no-widen-stop guards, regime /
volatility scaling, the kill switch (TFEX hard rule #8), and the capital-deployment ladder.

Pure offline library code — a leaf with the one-way dependency
``signals/ + execution/ + regime/ → risk/``. It imports **nothing** downstream (no ``backtest/``,
no ``live/``, no ``api/``); Phase 8 will drive :func:`evaluate_entry`.
"""

from __future__ import annotations

from tfex_s50_multi_tf_swing.risk.decision import evaluate_entry
from tfex_s50_multi_tf_swing.risk.errors import (
    RiskConfigError,
    RiskError,
    RiskInputError,
    RiskLimitError,
)
from tfex_s50_multi_tf_swing.risk.killswitch import evaluate_kill_switch
from tfex_s50_multi_tf_swing.risk.ladder import max_contracts_for_stage
from tfex_s50_multi_tf_swing.risk.limits import (
    assert_no_average_down,
    assert_stop_not_widened,
    can_open,
    register_outcome,
    start_session,
)
from tfex_s50_multi_tf_swing.risk.models import (
    DEPLOYMENT_STAGES,
    KILL_SWITCH_TRIGGERS,
    DeploymentStage,
    KillSwitchState,
    KillSwitchTrigger,
    LadderEvidence,
    MarketHealth,
    OpenPosition,
    PositionSizeRequest,
    PositionSizeResult,
    RiskConfig,
    RiskDecision,
    SessionRiskState,
    TradeOutcome,
)
from tfex_s50_multi_tf_swing.risk.sizing import (
    S50_MULTIPLIER,
    compute_position_size,
    volatility_scale_factor,
)

__all__: list[str] = [
    "DEPLOYMENT_STAGES",
    "KILL_SWITCH_TRIGGERS",
    "S50_MULTIPLIER",
    "DeploymentStage",
    "KillSwitchState",
    "KillSwitchTrigger",
    "LadderEvidence",
    "MarketHealth",
    "OpenPosition",
    "PositionSizeRequest",
    "PositionSizeResult",
    "RiskConfig",
    "RiskConfigError",
    "RiskDecision",
    "RiskError",
    "RiskInputError",
    "RiskLimitError",
    "SessionRiskState",
    "TradeOutcome",
    "assert_no_average_down",
    "assert_stop_not_widened",
    "can_open",
    "compute_position_size",
    "evaluate_entry",
    "evaluate_kill_switch",
    "max_contracts_for_stage",
    "register_outcome",
    "start_session",
    "volatility_scale_factor",
]
