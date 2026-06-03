"""Higher-timeframe (4H) bias filter (ROADMAP §4.1 / §4.2).

The bias engine materialises **one directional bias per 4H bar** — ``long`` / ``short`` /
``neutral`` — used downstream to **veto** counter-trend trades. It only filters; it never
generates trades. It is deterministic and trailing-only, and consumes the **un-normalised**
Phase 2 feature panel exactly like the regime layer (the normalised panel z-scores
``ema_slope_*`` / ``dist_from_vwap``, destroying the absolute signs the gates need).

Composition is **conservative unanimity** (mirrors the regime ``trend_up`` AND-rule): a
directional bias requires *every* gate to agree, and a healthy regime. Any disagreement, tie,
null ``structure``, or insufficient lookback yields ``neutral`` — never a directional guess.

Three entry points (mirroring :mod:`tfex_s50_multi_tf_swing.regime.rules`):

* :func:`build_bias_inputs` — bridge from a continuous OHLCV frame to the bias-input columns
  (reuses :func:`regime.build_regime_inputs` + :func:`regime.classify_frame`, so regime is
  computed once, never re-derived here).
* :func:`classify_frame` — vectorised Polars pass appending ``bias_direction`` (Utf8) and
  ``bias_reasons`` (``List[Utf8]``) columns to a frame carrying :data:`REQUIRED_COLUMNS`.
* :func:`classify_row` — scalar mirror returning a :class:`BiasSignal`.
* :func:`to_signals` — materialise one :class:`BiasSignal` per row of a classified frame.

**4h is mirror-only.** The bias engine is source-agnostic: it consumes already-loaded frames
and never fetches tvkit / the engine. The canonical ``engine`` OHLCV source declines ``4h``
(:class:`~tfex_s50_multi_tf_swing.data.errors.EngineTimeframeUnavailableError`) because the
Market Data Engine has no ``4h`` route yet — no local rollup (Decision D10). Until then ``4h``
comes from the ``mirror`` source. See ``docs/plans/ROADMAP.md`` and ``.claude/knowledge``.
"""

from __future__ import annotations

import logging

import polars as pl

from tfex_s50_multi_tf_swing.bias.errors import BiasInputError
from tfex_s50_multi_tf_swing.bias.models import (
    BiasConfig,
    BiasDirection,
    BiasFeatures,
    BiasSignal,
)
from tfex_s50_multi_tf_swing.data.models import Timeframe
from tfex_s50_multi_tf_swing.features.models import FeatureConfig
from tfex_s50_multi_tf_swing.regime.models import (
    BEARISH_STRUCTURE,
    BULLISH_STRUCTURE,
    RegimeThresholds,
)
from tfex_s50_multi_tf_swing.regime.rules import build_regime_inputs
from tfex_s50_multi_tf_swing.regime.rules import classify_frame as classify_regime_frame

logger = logging.getLogger(__name__)

#: Columns :func:`classify_frame` requires on its input frame.
REQUIRED_COLUMNS: tuple[str, ...] = (
    "ema_fast_minus_slow",
    "ema_slope_fast",
    "structure",
    "dist_from_vwap",
    "regime",
)


def build_bias_inputs(
    df: pl.DataFrame,
    timeframe: Timeframe,
    *,
    feature_config: FeatureConfig | None = None,
    regime_thresholds: RegimeThresholds | None = None,
) -> pl.DataFrame:
    """Build the bias-input frame from a continuous OHLCV frame.

    Returns ``time`` plus :data:`REQUIRED_COLUMNS`. Reuses the regime bridge for the trend
    features and the regime label, so the volatility-healthy gate reads the *same* regime
    classification the Phase 3 layer produces — never a re-derivation.
    """
    inputs = build_regime_inputs(df, timeframe, feature_config)
    classified = classify_regime_frame(inputs, thresholds=regime_thresholds)
    return classified.select(
        "time",
        "ema_fast_minus_slow",
        "ema_slope_fast",
        "structure",
        "dist_from_vwap",
        "regime",
    )


def classify_frame(df: pl.DataFrame, *, config: BiasConfig | None = None) -> pl.DataFrame:
    """Append ``bias_direction`` (Utf8) and ``bias_reasons`` (List[Utf8]) columns.

    The input frame must carry :data:`REQUIRED_COLUMNS`. One vectorised, look-ahead-free pass
    (no new rolling window) — every input column is already causal.
    """
    config = config or BiasConfig()
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise BiasInputError(f"bias input frame missing columns: {sorted(missing)}")
    return df.with_columns(
        _direction_expr(config).alias("bias_direction"),
        _reasons_expr(config).alias("bias_reasons"),
    )


def _long_gates(config: BiasConfig) -> pl.Expr:
    """Boolean expr — every long gate agrees and the regime is healthy."""
    return (
        (pl.col("ema_fast_minus_slow") > 0.0)
        & (pl.col("ema_slope_fast") > config.slope_deadband)
        & pl.col("structure").is_in(list(BULLISH_STRUCTURE))
        & (pl.col("dist_from_vwap") > config.vwap_deadband)
        & _regime_ok(config)
    ).fill_null(False)


def _short_gates(config: BiasConfig) -> pl.Expr:
    """Boolean expr — every short gate agrees and the regime is healthy."""
    return (
        (pl.col("ema_fast_minus_slow") < 0.0)
        & (pl.col("ema_slope_fast") < -config.slope_deadband)
        & pl.col("structure").is_in(list(BEARISH_STRUCTURE))
        & (pl.col("dist_from_vwap") < -config.vwap_deadband)
        & _regime_ok(config)
    ).fill_null(False)


def _regime_ok(config: BiasConfig) -> pl.Expr:
    """Boolean expr — the 4H regime is not one of the no-trade (veto) regimes."""
    return ~pl.col("regime").is_in(list(config.neutral_regimes))


def _direction_expr(config: BiasConfig) -> pl.Expr:
    """Conservative-unanimity direction: long/short only on full agreement, else neutral."""
    return (
        pl.when(_long_gates(config))
        .then(pl.lit("long"))
        .when(_short_gates(config))
        .then(pl.lit("short"))
        .otherwise(pl.lit("neutral"))
    )


def _reasons_expr(config: BiasConfig) -> pl.Expr:
    """One human-auditable reason string per gate, gathered into a List[Utf8]."""
    ema = (
        pl.when(pl.col("ema_fast_minus_slow") > 0.0)
        .then(pl.lit("ema_fast>ema_slow (long)"))
        .when(pl.col("ema_fast_minus_slow") < 0.0)
        .then(pl.lit("ema_fast<ema_slow (short)"))
        .otherwise(pl.lit("ema_fast==ema_slow (neutral)"))
    )
    slope = (
        pl.when(pl.col("ema_slope_fast") > config.slope_deadband)
        .then(pl.lit("slope>0 (long)"))
        .when(pl.col("ema_slope_fast") < -config.slope_deadband)
        .then(pl.lit("slope<0 (short)"))
        .otherwise(pl.lit("slope flat (neutral)"))
    )
    structure = (
        pl.when(pl.col("structure").is_in(list(BULLISH_STRUCTURE)))
        .then(pl.lit("structure HH/HL (long)"))
        .when(pl.col("structure").is_in(list(BEARISH_STRUCTURE)))
        .then(pl.lit("structure LH/LL (short)"))
        .otherwise(pl.lit("structure none (neutral)"))
    )
    vwap = (
        pl.when(pl.col("dist_from_vwap") > config.vwap_deadband)
        .then(pl.lit("price>vwap (long)"))
        .when(pl.col("dist_from_vwap") < -config.vwap_deadband)
        .then(pl.lit("price<vwap (short)"))
        .otherwise(pl.lit("price at vwap (neutral)"))
    )
    regime = (
        pl.when(_regime_ok(config))
        .then(pl.format("regime {} (ok)", "regime"))
        .otherwise(pl.format("regime {} (veto)", "regime"))
    )
    return pl.concat_list([ema, slope, structure, vwap, regime])


def classify_row(features: BiasFeatures, config: BiasConfig | None = None) -> BiasSignal:
    """Classify a single bar from pre-computed :class:`BiasFeatures`.

    Produces the same direction + reason strings as :func:`classify_frame` for identical
    inputs (asserted by the test suite).
    """
    config = config or BiasConfig()
    reasons = _row_reasons(features, config)
    direction = _row_direction(features, config)
    return BiasSignal(direction=direction, reasons=reasons)


def _row_direction(features: BiasFeatures, config: BiasConfig) -> BiasDirection:
    """Scalar mirror of :func:`_direction_expr`."""
    regime_ok = features.regime not in config.neutral_regimes
    long_all = (
        features.ema_fast_minus_slow > 0.0
        and features.ema_slope_fast > config.slope_deadband
        and features.structure in BULLISH_STRUCTURE
        and features.dist_from_vwap > config.vwap_deadband
        and regime_ok
    )
    short_all = (
        features.ema_fast_minus_slow < 0.0
        and features.ema_slope_fast < -config.slope_deadband
        and features.structure in BEARISH_STRUCTURE
        and features.dist_from_vwap < -config.vwap_deadband
        and regime_ok
    )
    if long_all:
        return "long"
    if short_all:
        return "short"
    return "neutral"


def _row_reasons(features: BiasFeatures, config: BiasConfig) -> list[str]:
    """Scalar mirror of :func:`_reasons_expr` (one string per gate, same wording)."""
    if features.ema_fast_minus_slow > 0.0:
        ema = "ema_fast>ema_slow (long)"
    elif features.ema_fast_minus_slow < 0.0:
        ema = "ema_fast<ema_slow (short)"
    else:
        ema = "ema_fast==ema_slow (neutral)"
    if features.ema_slope_fast > config.slope_deadband:
        slope = "slope>0 (long)"
    elif features.ema_slope_fast < -config.slope_deadband:
        slope = "slope<0 (short)"
    else:
        slope = "slope flat (neutral)"
    if features.structure in BULLISH_STRUCTURE:
        structure = "structure HH/HL (long)"
    elif features.structure in BEARISH_STRUCTURE:
        structure = "structure LH/LL (short)"
    else:
        structure = "structure none (neutral)"
    if features.dist_from_vwap > config.vwap_deadband:
        vwap = "price>vwap (long)"
    elif features.dist_from_vwap < -config.vwap_deadband:
        vwap = "price<vwap (short)"
    else:
        vwap = "price at vwap (neutral)"
    healthy = features.regime not in config.neutral_regimes
    regime = f"regime {features.regime} ({'ok' if healthy else 'veto'})"
    return [ema, slope, structure, vwap, regime]


def to_signals(df: pl.DataFrame) -> list[BiasSignal]:
    """Materialise one :class:`BiasSignal` per row of a classified frame.

    The frame must already carry ``bias_direction`` + ``bias_reasons`` (i.e. be the output of
    :func:`classify_frame`).
    """
    missing = [c for c in ("bias_direction", "bias_reasons") if c not in df.columns]
    if missing:
        raise BiasInputError(f"classified frame missing columns: {sorted(missing)}")
    return [
        BiasSignal(direction=row["bias_direction"], reasons=list(row["bias_reasons"]))
        for row in df.iter_rows(named=True)
    ]


__all__: list[str] = [
    "REQUIRED_COLUMNS",
    "build_bias_inputs",
    "classify_frame",
    "classify_row",
    "to_signals",
]
