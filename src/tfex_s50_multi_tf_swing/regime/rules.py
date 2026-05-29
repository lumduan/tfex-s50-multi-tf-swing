"""Rule-based regime classifier (ROADMAP §3.1).

The classifier is deterministic and trailing-only. It consumes the **un-normalised**
Phase 2 feature panel: the normalised panel z-scores ``ema_slope_*`` / ``dist_from_vwap``
against a trailing window, which would destroy the absolute signs the rules need.

Two entry points:

* :func:`build_regime_inputs` — bridge from a continuous OHLCV frame to the raw columns
  the rules read (reuses :func:`tfex_s50_multi_tf_swing.features.pipeline.build_panel` with
  ``normalise=False`` and derives the EMA-level diff via ``indicators.ema``).
* :func:`classify_frame` — vectorised Polars pass appending a ``regime`` column to any
  frame already carrying the regime-input columns. Computed once per frame, never per-bar.
* :func:`classify_row` — scalar mirror for callers holding a single
  :class:`~tfex_s50_multi_tf_swing.regime.models.RegimeFeatures`.

Evaluation order: ``panic`` first (a volatility blow-off dominates an otherwise-trending
tape), then trend, then ``range_low_vol``, with ``range_high_vol`` the residual. Rows whose
core inputs are null (insufficient lookback) are labelled ``range_low_vol`` — the no-trade
bucket — so trading is never enabled on undefined features.
"""

from __future__ import annotations

import logging

import polars as pl

from tfex_s50_multi_tf_swing.data.models import Timeframe
from tfex_s50_multi_tf_swing.features.indicators import ema
from tfex_s50_multi_tf_swing.features.models import FeatureConfig
from tfex_s50_multi_tf_swing.features.pipeline import build_panel
from tfex_s50_multi_tf_swing.regime.errors import RegimeInputError
from tfex_s50_multi_tf_swing.regime.models import (
    BEARISH_STRUCTURE,
    BULLISH_STRUCTURE,
    Regime,
    RegimeFeatures,
    RegimeThresholds,
)

logger = logging.getLogger(__name__)

#: Columns :func:`classify_frame` requires on its input frame.
REQUIRED_COLUMNS: tuple[str, ...] = (
    "ema_fast_minus_slow",
    "ema_slope_fast",
    "structure",
    "dist_from_vwap",
    "rv_percentile",
    "trend_persistence",
    "volume_expansion",
    "range_compression",
)


def build_regime_inputs(
    df: pl.DataFrame, timeframe: Timeframe, config: FeatureConfig | None = None
) -> pl.DataFrame:
    """Build the regime-input frame from a continuous OHLCV frame.

    Returns ``time`` plus the :data:`REQUIRED_COLUMNS`. Reuses the Phase 2 pipeline
    (un-normalised) for the bulk of the features and derives ``ema_fast_minus_slow``
    from ``close`` with the shared causal EMA primitive.
    """
    config = config or FeatureConfig()
    fast, slow = min(config.ema_spans), max(config.ema_spans)

    panel = build_panel(df, timeframe, config.model_copy(update={"normalise": False}))
    ema_diff = (
        df.sort("time")
        .with_columns(pl.col("close").cast(pl.Float64))
        .select(
            "time",
            (ema("close", fast) - ema("close", slow)).alias("ema_fast_minus_slow"),
        )
    )
    merged = panel.join(ema_diff, on="time", how="left")
    return merged.select(
        "time",
        "ema_fast_minus_slow",
        pl.col(f"ema_slope_{fast}").alias("ema_slope_fast"),
        "structure",
        "dist_from_vwap",
        "rv_percentile",
        "trend_persistence",
        "volume_expansion",
        "range_compression",
    )


def classify_frame(df: pl.DataFrame, *, thresholds: RegimeThresholds | None = None) -> pl.DataFrame:
    """Append a ``regime`` (Utf8) column to a frame carrying :data:`REQUIRED_COLUMNS`."""
    thresholds = thresholds or RegimeThresholds()
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise RegimeInputError(f"regime input frame missing columns: {sorted(missing)}")
    return df.with_columns(_regime_expr(thresholds).alias("regime"))


def _regime_expr(thresholds: RegimeThresholds) -> pl.Expr:
    """Build the panic-first ``when/then`` regime expression."""
    rv = pl.col("rv_percentile")
    insufficient = (
        rv.is_null() | pl.col("range_compression").is_null() | pl.col("volume_expansion").is_null()
    )
    panic = (
        (rv > thresholds.panic_rv) | (pl.col("volume_expansion") > thresholds.panic_volume_z)
    ).fill_null(False)
    trend_up = (
        (pl.col("ema_fast_minus_slow") > 0.0)
        & (pl.col("ema_slope_fast") > 0.0)
        & pl.col("structure").is_in(list(BULLISH_STRUCTURE))
        & (pl.col("dist_from_vwap") > 0.0)
    ).fill_null(False)
    trend_down = (
        (pl.col("ema_fast_minus_slow") < 0.0)
        & (pl.col("ema_slope_fast") < 0.0)
        & pl.col("structure").is_in(list(BEARISH_STRUCTURE))
        & (pl.col("dist_from_vwap") < 0.0)
    ).fill_null(False)
    range_low = ((rv < thresholds.range_low_rv) & (pl.col("range_compression") == 1)).fill_null(
        False
    )
    return (
        pl.when(insufficient)
        .then(pl.lit("range_low_vol"))
        .when(panic)
        .then(pl.lit("panic"))
        .when(trend_up)
        .then(pl.lit("trend_up"))
        .when(trend_down)
        .then(pl.lit("trend_down"))
        .when(range_low)
        .then(pl.lit("range_low_vol"))
        .otherwise(pl.lit("range_high_vol"))
    )


def classify_row(features: RegimeFeatures, thresholds: RegimeThresholds | None = None) -> Regime:
    """Classify a single bar from pre-computed :class:`RegimeFeatures`."""
    thresholds = thresholds or RegimeThresholds()
    if features.rv_percentile > thresholds.panic_rv:
        return "panic"
    if features.volume_expansion > thresholds.panic_volume_z:
        return "panic"
    if (
        features.ema_fast_minus_slow > 0.0
        and features.ema_slope_fast > 0.0
        and features.structure in BULLISH_STRUCTURE
        and features.dist_from_vwap > 0.0
    ):
        return "trend_up"
    if (
        features.ema_fast_minus_slow < 0.0
        and features.ema_slope_fast < 0.0
        and features.structure in BEARISH_STRUCTURE
        and features.dist_from_vwap < 0.0
    ):
        return "trend_down"
    if features.rv_percentile < thresholds.range_low_rv and features.range_compression == 1:
        return "range_low_vol"
    return "range_high_vol"


__all__: list[str] = [
    "REQUIRED_COLUMNS",
    "build_regime_inputs",
    "classify_frame",
    "classify_row",
]
