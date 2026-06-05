"""Setup-detection layer (ROADMAP Phase 5 — §5.1–5.3).

Three rule-based strategies — A (pullback continuation), B (opening-range breakout),
C (liquidity-sweep reversal, permanently disabled per 1H migration) — each gated by the
1D HTF bias veto and the 1D regime → strategy policy, read on a causally aligned 1H frame
(:func:`build_signal_inputs`). Each strategy module exposes the bias/regime shape:
``classify_frame`` (vectorised) + ``classify_row`` (scalar) + ``to_signals`` (materialiser).
Pure offline library code — one-way dependency ``features/ + regime/ + bias/ → signals/``;
nothing here imports ``api/``, builds ``risk/`` (Phase 7), or changes the gateway contract.
"""

from __future__ import annotations

from tfex_s50_multi_tf_swing.signals import strategy_a, strategy_b, strategy_c
from tfex_s50_multi_tf_swing.signals.errors import SignalError, SignalInputError
from tfex_s50_multi_tf_swing.signals.inputs import (
    COL_BIAS,
    COL_REGIME,
    build_signal_inputs,
)
from tfex_s50_multi_tf_swing.signals.models import (
    NO_SIGNAL,
    SETUP_DIRECTIONS,
    STRATEGY_IDS,
    SetupDirection,
    SetupFeatures,
    SetupSignal,
    SignalConfig,
    StrategyId,
)

__all__: list[str] = [
    "COL_BIAS",
    "COL_REGIME",
    "NO_SIGNAL",
    "SETUP_DIRECTIONS",
    "STRATEGY_IDS",
    "SetupDirection",
    "SetupFeatures",
    "SetupSignal",
    "SignalConfig",
    "SignalError",
    "SignalInputError",
    "StrategyId",
    "build_signal_inputs",
    "strategy_a",
    "strategy_b",
    "strategy_c",
]
