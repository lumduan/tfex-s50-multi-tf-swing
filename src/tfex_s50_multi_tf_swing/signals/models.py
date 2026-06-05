"""Type contracts for the setup-detection (signal) layer (ROADMAP §5.1–5.3).

* :data:`StrategyId` / :data:`SetupDirection` — the taxonomies the layer emits.
* :class:`SetupSignal` — one fired setup: the strategy that produced it, the 1H trigger bar,
  the direction, and the **Decimal** trigger / stop-reference prices a Phase-7 risk engine will
  size against. Prices are money, so they are :class:`~decimal.Decimal` (matching
  :class:`~tfex_s50_multi_tf_swing.data.models.OhlcvBar`); the detection frame works in Float64
  and casts at this boundary.
* :class:`SignalConfig` — every tunable gate threshold, frozen and bounded so an out-of-range
  env override fails loud at load time (mirrors
  :class:`~tfex_s50_multi_tf_swing.bias.models.BiasConfig`).
* :class:`SetupFeatures` — the scalar per-row inputs a single-bar :func:`classify_row` reads
  (the union of what strategies A / B / C consume off the aligned 1H panel).

The gate thresholds are :class:`float` (internal statistical quantities); only the emitted
prices on :class:`SetupSignal` are Decimal, because only they are money that a later phase
sizes against.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tfex_s50_multi_tf_swing.regime.models import Regime

StrategyId = Literal["A", "B", "C"]
"""The three Phase-5 setup strategies: A (pullback), B (opening-range), C (sweep reversal)."""

STRATEGY_IDS: tuple[StrategyId, ...] = get_args(StrategyId)
"""Tuple of every :data:`StrategyId`, for iteration / parametrised tests."""

SetupDirection = Literal["long", "short"]
"""A fired setup is directional; the absence of a setup is modelled as no :class:`SetupSignal`."""

SETUP_DIRECTIONS: tuple[SetupDirection, ...] = get_args(SetupDirection)
"""Tuple of every :data:`SetupDirection`."""

# The Utf8 sentinel a vectorised ``classify_frame`` writes when no setup fired on a bar.
NO_SIGNAL: str = "none"


class SignalConfig(BaseModel):
    """Tunable gate thresholds for the three setup strategies.

    Every field is bounded so an out-of-range env override fails at load time. Defaults
    reproduce the documented ``strategy-design`` behaviour, so an unset env keeps current
    behaviour. ``or_window`` selects which opening-range column Strategy B breaks out of
    (``or_high_{or_window}`` / ``or_low_{or_window}``), and must be one the feature pipeline
    emits (``opening_range_minutes``, default 15 / 30 / 60). Default ``or_window=60`` for the
    1H-execution migration — one 1H bar as the opening range.
    """

    model_config = ConfigDict(frozen=True)

    # Strategy A — 1H pullback gates (1H is now the base TF, these read unprefixed columns).
    pullback_band: float = Field(default=1.0, ge=0.0)
    atr_contraction_max: float = Field(default=1.0, gt=0.0)
    volume_contraction_max: float = Field(default=0.5)
    # Strategy A — 1H compression gates.
    squeeze_max: float = Field(default=1.0, gt=0.0)
    atr_compression_max: float = Field(default=1.0, gt=0.0)
    # Shared 1H trigger gate.
    volume_expansion_min: float = Field(default=1.0)
    # Strategy B — opening-range window (must be a pipeline opening_range_minutes value).
    # Default 60 = first 1H bar as the opening range (1H-execution migration).
    or_window: int = Field(default=60, ge=1)
    # Strategy C — require the post-sweep structure to have shifted to the reversal side.
    # (Permanently disabled per the 1H-execution migration.)
    require_structure_shift: bool = True
    # Lookback (in 1H bars) for the causal swing high/low used as the structure stop anchor.
    swing_window: int = Field(default=4, ge=2)
    # Directional entry gate (applied by ``signals.gate.apply_regime_gate``). ``allowed_regimes`` is
    # the **long** allow-set: a fired LONG bar survives only when its **1D regime** is in it.
    # Defaults to ``trend_up`` only (61.7% of the historical edge).
    allowed_regimes: frozenset[Regime] = frozenset({"trend_up"})
    # The **short** allow-set: a fired SHORT bar survives only when its 1D regime is in it. Default
    # empty ⇒ shorts blocked (long-only, backward-compatible). Set to ``{"trend_down"}`` to capture
    # downside alpha in bear regimes (dual-direction hedging of the long-only macro book).
    short_allowed_regimes: frozenset[Regime] = frozenset()


class SetupSignal(BaseModel):
    """One fired setup, ready for risk sizing (Phase 7) and execution simulation (§5.4).

    ``trigger_price`` is the 5m breakout / confirmation close; ``stop_reference`` is the
    structure-anchored invalidation level the execution engine clamps its ``k·ATR`` stop to.
    Both are Decimal — they are money. ``reasons`` records one human-auditable string per gate.
    """

    model_config = ConfigDict(frozen=True)

    strategy_id: StrategyId
    time: datetime
    direction: SetupDirection
    trigger_price: Decimal
    stop_reference: Decimal
    regime: Regime | None = None
    reasons: list[str] = Field(default_factory=list)

    @field_validator("time")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        """Reject tz-naive / non-UTC timestamps (store-UTC rule)."""
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(None):
            raise ValueError("time must be a UTC-aware datetime")
        return value


class SetupFeatures(BaseModel):
    """Scalar per-row inputs for a single-bar :func:`classify_row`.

    Mirrors the aligned-1H-panel columns the strategies read: the 1D bias label, the 1D regime,
    the 1H features (unprefixed — they are the base timeframe), and the raw 1H price + the
    causal swing / opening-range levels, and the two session flags. Fields a given strategy does
    not use may be ``None`` (e.g. ``or_high`` for Strategy A).

    The ``h1_*`` fields are **deprecated** — with the 1H-execution migration 1H is the base
    timeframe, so its features are the unprefixed fields. The ``h1_*`` fields remain for
    backward-compatible test code but are no longer populated from the aligned frame.
    """

    model_config = ConfigDict(frozen=True)

    time: datetime
    bias_direction: str
    regime: Regime | None
    # 1H pullback context.
    h1_dist_from_vwap: float | None = None
    h1_structure: str | None = None
    h1_atr_ratio: float | None = None
    h1_volume_expansion: float | None = None
    # 5m compression / trigger context.
    atr_ratio: float | None = None
    bollinger_squeeze: float | None = None
    volume_expansion: float | None = None
    dist_from_vwap: float | None = None
    structure: str | None = None
    # Raw 5m price + causal levels.
    close: float
    swing_high: float | None = None
    swing_low: float | None = None
    or_high: float | None = None
    or_low: float | None = None
    # Session flags.
    liquidity_sweep_flag: int = 0
    lunch_zone_flag: int = 0

    @field_validator("time")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(None):
            raise ValueError("time must be a UTC-aware datetime")
        return value


__all__: list[str] = [
    "NO_SIGNAL",
    "SETUP_DIRECTIONS",
    "STRATEGY_IDS",
    "SetupDirection",
    "SetupFeatures",
    "SignalConfig",
    "SetupSignal",
    "StrategyId",
]
