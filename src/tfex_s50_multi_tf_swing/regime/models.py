"""Type contracts for the regime layer.

* :data:`Regime` / :data:`REGIMES` — the five-label taxonomy from
  ``.claude/knowledge/regime-detection.md``.
* :class:`RegimeFeatures` — the scalar inputs a single-bar classification needs.
* :class:`RegimeThresholds` — every numeric cutoff the rule classifier uses, with
  defaults matching the documented rule sketches. Frozen so a threshold set is a
  stable cache key and cannot drift mid-run.
* :class:`RegimeClassification` — one classified bar ``(time, timeframe, regime)``.
* :class:`RegimePolicy` — the regime → allowed-strategies / size / direction mapping.

Regime inputs are :class:`float`: they are internal statistical quantities that never
cross the gateway boundary, so the Decimal-for-money rule does not apply (see the
Phase 2 feature layer).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tfex_s50_multi_tf_swing.data.models import Timeframe

Regime = Literal[
    "trend_up",
    "trend_down",
    "range_low_vol",
    "range_high_vol",
    "panic",
]
"""The five mutually-exclusive market regimes."""

REGIMES: tuple[Regime, ...] = get_args(Regime)
"""Tuple of every :data:`Regime` label, for iteration / parametrised tests."""

Direction = Literal["long", "short", "both", "none"]
"""Trade direction a regime permits."""

# Structure labels that count as bullish / bearish market structure.
BULLISH_STRUCTURE: frozenset[str] = frozenset({"HH", "HL"})
BEARISH_STRUCTURE: frozenset[str] = frozenset({"LH", "LL"})


class RegimeThresholds(BaseModel):
    """Numeric cutoffs for the rule-based classifier.

    Defaults follow the rule sketches in ``.claude/knowledge/regime-detection.md``.
    Every value is bounded so an out-of-range env override fails loud at load time.
    """

    model_config = ConfigDict(frozen=True)

    panic_rv: float = Field(default=0.95, gt=0.0, le=1.0)
    panic_volume_z: float = Field(default=3.0, gt=0.0)
    range_low_rv: float = Field(default=0.30, ge=0.0, le=1.0)
    range_high_rv: float = Field(default=0.70, ge=0.0, le=1.0)
    trend_persist_min: float = Field(default=0.30, ge=0.0, le=1.0)


class RegimeFeatures(BaseModel):
    """Scalar feature inputs for a single-bar classification.

    Mirrors the (un-normalised) panel columns the rules read, plus the derived
    ``ema_fast_minus_slow`` level. ``structure`` is the categorical HH/HL/LH/LL
    label (``None`` until two pivots of a kind exist).
    """

    model_config = ConfigDict(frozen=True)

    ema_fast_minus_slow: float
    ema_slope_fast: float
    structure: str | None
    dist_from_vwap: float
    rv_percentile: float = Field(ge=0.0, le=1.0)
    trend_persistence: float = Field(ge=-1.0, le=1.0)
    volume_expansion: float
    range_compression: int = Field(ge=0, le=1)


class RegimeClassification(BaseModel):
    """One classified bar."""

    model_config = ConfigDict(frozen=True)

    time: datetime
    timeframe: Timeframe
    regime: Regime

    @field_validator("time")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        """Reject tz-naive / non-UTC timestamps (store-UTC rule)."""
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(None):
            raise ValueError("time must be a UTC-aware datetime")
        return value


class RegimePolicy(BaseModel):
    """Regime → strategy gating contract (ROADMAP §3.4)."""

    model_config = ConfigDict(frozen=True)

    regime: Regime
    allowed_strategies: frozenset[str]
    size_multiplier: float = Field(ge=0.0, le=1.0)
    direction: Direction


__all__: list[str] = [
    "BEARISH_STRUCTURE",
    "BULLISH_STRUCTURE",
    "Direction",
    "REGIMES",
    "Regime",
    "RegimeClassification",
    "RegimeFeatures",
    "RegimePolicy",
    "RegimeThresholds",
]
