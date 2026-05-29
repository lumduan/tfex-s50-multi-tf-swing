"""Regime detection layer (ROADMAP Phase 3 — §3.1 rule baseline + §3.4 policy).

Classifies every bar into one of five regimes and maps each regime to the strategies
and position size it permits. Pure offline library code consuming the Phase 2 feature
panel; downstream phases (bias engine, setup detection, risk) gate on these outputs.
"""

from __future__ import annotations

from tfex_s50_multi_tf_swing.regime.errors import (
    RegimeError,
    RegimeInputError,
    RegimePolicyError,
    UnknownRegimeError,
)
from tfex_s50_multi_tf_swing.regime.models import (
    REGIMES,
    Direction,
    Regime,
    RegimeClassification,
    RegimeFeatures,
    RegimePolicy,
    RegimeThresholds,
)
from tfex_s50_multi_tf_swing.regime.policy import (
    is_no_trade,
    regime_policy,
    regime_to_size_multiplier,
    regime_to_strategies,
)
from tfex_s50_multi_tf_swing.regime.rules import (
    REQUIRED_COLUMNS,
    build_regime_inputs,
    classify_frame,
    classify_row,
)

__all__: list[str] = [
    "REGIMES",
    "REQUIRED_COLUMNS",
    "Direction",
    "Regime",
    "RegimeClassification",
    "RegimeError",
    "RegimeFeatures",
    "RegimeInputError",
    "RegimePolicy",
    "RegimePolicyError",
    "RegimeThresholds",
    "UnknownRegimeError",
    "build_regime_inputs",
    "classify_frame",
    "classify_row",
    "is_no_trade",
    "regime_policy",
    "regime_to_size_multiplier",
    "regime_to_strategies",
]
