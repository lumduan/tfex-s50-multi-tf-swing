"""Higher-timeframe bias layer (ROADMAP Phase 4 — §4.1 4H trend filter + §4.2 output).

Materialises one directional bias (``long`` / ``short`` / ``neutral``) per 4H bar to **veto**
counter-trend trades downstream — it only filters, never generates trades. Pure offline library
code consuming the Phase 2 feature panel + the Phase 3 regime label. One-way dependency:
``features/ + regime/ → bias/``; nothing downstream (``signals/``, ``execution/``, ``risk/``,
``backtest/``, ``api/``) is imported here.
"""

from __future__ import annotations

from tfex_s50_multi_tf_swing.bias.errors import BiasError, BiasInputError
from tfex_s50_multi_tf_swing.bias.htf import (
    REQUIRED_COLUMNS,
    build_bias_inputs,
    classify_frame,
    classify_row,
    to_signals,
)
from tfex_s50_multi_tf_swing.bias.models import (
    BIAS_DIRECTIONS,
    DEFAULT_NEUTRAL_REGIMES,
    BiasConfig,
    BiasDirection,
    BiasFeatures,
    BiasSignal,
)

__all__: list[str] = [
    "BIAS_DIRECTIONS",
    "DEFAULT_NEUTRAL_REGIMES",
    "REQUIRED_COLUMNS",
    "BiasConfig",
    "BiasDirection",
    "BiasError",
    "BiasFeatures",
    "BiasInputError",
    "BiasSignal",
    "build_bias_inputs",
    "classify_frame",
    "classify_row",
    "to_signals",
]
