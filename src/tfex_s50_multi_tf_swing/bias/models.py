"""Type contracts for the higher-timeframe bias layer (ROADMAP §4.2).

* :data:`BiasDirection` — the three-label output taxonomy (``long`` / ``short`` /
  ``neutral``).
* :class:`BiasSignal` — one bar's directional bias plus the human-auditable reason strings
  (one per gate) that produced it.
* :class:`BiasConfig` — every tunable threshold the gates use, with bounded defaults. Frozen
  so a config set is a stable cache key and cannot drift mid-run (mirrors
  :class:`~tfex_s50_multi_tf_swing.regime.models.RegimeThresholds`).
* :class:`BiasFeatures` — the scalar inputs a single-bar classification needs.

Bias inputs are :class:`float`: internal statistical quantities that never cross the gateway
boundary, so the Decimal-for-money rule does not apply (see the Phase 2 feature layer).
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from tfex_s50_multi_tf_swing.regime.models import Regime

BiasDirection = Literal["long", "short", "neutral"]
"""The three mutually-exclusive bias directions emitted per 4H bar."""

BIAS_DIRECTIONS: tuple[BiasDirection, ...] = get_args(BiasDirection)
"""Tuple of every :data:`BiasDirection`, for iteration / parametrised tests."""

# Regimes that force a ``neutral`` bias regardless of the trend gates (ROADMAP §4.1
# "volatility-healthy gate"): the two no-trade regimes from the Phase 3 policy table.
DEFAULT_NEUTRAL_REGIMES: tuple[Regime, ...] = ("panic", "range_low_vol")


class BiasConfig(BaseModel):
    """Tunable thresholds for the 4H bias gates.

    ``slope_deadband`` / ``vwap_deadband`` are noise bands: a gate only votes directionally
    when the (ATR-normalised) magnitude exceeds the band. Both default to ``0.0`` so the
    baseline rule is a strict sign test. ``neutral_regimes`` lists the regimes that veto any
    directional bias. Every value is bounded so an out-of-range env override fails loud at
    load time.
    """

    model_config = ConfigDict(frozen=True)

    slope_deadband: float = Field(default=0.0, ge=0.0)
    vwap_deadband: float = Field(default=0.0, ge=0.0)
    neutral_regimes: tuple[Regime, ...] = DEFAULT_NEUTRAL_REGIMES


class BiasFeatures(BaseModel):
    """Scalar feature inputs for a single-bar bias classification.

    Mirrors the (un-normalised) columns the gates read: the EMA-level diff, the fast-EMA
    ATR-normalised slope, the categorical HH/HL/LH/LL ``structure`` label (``None`` until two
    pivots of a kind exist), the ATR-normalised distance from session VWAP, and the
    already-classified 4H ``regime``.
    """

    model_config = ConfigDict(frozen=True)

    ema_fast_minus_slow: float
    ema_slope_fast: float
    structure: str | None
    dist_from_vwap: float
    regime: Regime


class BiasSignal(BaseModel):
    """One bar's higher-timeframe bias.

    ``direction`` is the veto verdict; ``reasons`` is one human-auditable string per gate that
    fired, so a human can read exactly why the bar got its label.
    """

    model_config = ConfigDict(frozen=True)

    direction: BiasDirection
    reasons: list[str]


__all__: list[str] = [
    "BIAS_DIRECTIONS",
    "DEFAULT_NEUTRAL_REGIMES",
    "BiasConfig",
    "BiasDirection",
    "BiasFeatures",
    "BiasSignal",
]
