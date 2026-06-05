"""Build the aligned 1H signal-input frame (the multi-timeframe substrate for §5.1–5.3).

Setups span two timeframes — 1D HTF bias/regime, 1H execution. Rather than join
frames ad-hoc, :func:`build_signal_inputs` resolves everything onto the **1H** grid using the
Phase-2 causal aligner (:func:`tfex_s50_multi_tf_swing.features.align.align_timeframes`): every
higher-timeframe column is availability-shifted by its bar duration, so an HTF value can only
appear on a 1H bar once the HTF bar has *closed*. This is the single most dangerous look-ahead
trap in a multi-timeframe system; ``tests/unit/signals/test_inputs.py`` asserts no future value
leaks.

The frame carries, per 1H bar:

* the 1H feature columns (``atr_ratio``, ``bollinger_squeeze``, ``volume_expansion``,
  ``dist_from_vwap``, ``structure``, ``or_high_*`` / ``or_low_*``, ``liquidity_sweep_flag``,
  ``lunch_zone_flag``) — already on the base panel;
* the raw 1H ``close`` / ``high`` / ``low`` plus causal ``swing_high`` / ``swing_low``
  (rolling extremes, shifted) used for triggers and the structure stop anchor;
* ``1d_*`` features and the **1D regime** (``1d_regime``) that gates which strategies may trade;
* the **1D bias** (``1d_bias_direction``) that vetoes counter-trend A / B trades.

**Source-agnostic.** This builder consumes already-loaded continuous OHLCV frames
(mirror or engine); it never fetches tvkit / the engine. Both ``1h`` and ``1d`` are served by
both sources, so the bias/regime layers run regardless of OHLCV source (unlike the prior 4H
dependency which was engine-declined). When the 1D frame is absent ``1d_bias_direction`` is
filled ``"neutral"`` (safe degrade).

**1H-execution migration (2026-06-05).** The prior 4H→1H→5m hierarchy is replaced with
1D→1H: Daily bars carry regime + bias; 1H bars carry setup detection + execution. The
4H and 5m types remain in the type system for backward-compatible Parquet store reads but
no active signal path references them.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

import polars as pl

from tfex_s50_multi_tf_swing.bias.htf import build_bias_inputs
from tfex_s50_multi_tf_swing.bias.htf import classify_frame as classify_bias_frame
from tfex_s50_multi_tf_swing.bias.models import BiasConfig
from tfex_s50_multi_tf_swing.data.models import Timeframe
from tfex_s50_multi_tf_swing.features.align import align_timeframes
from tfex_s50_multi_tf_swing.features.models import FeatureConfig
from tfex_s50_multi_tf_swing.features.pipeline import build_panel
from tfex_s50_multi_tf_swing.regime.models import RegimeThresholds
from tfex_s50_multi_tf_swing.regime.rules import build_regime_inputs
from tfex_s50_multi_tf_swing.regime.rules import classify_frame as classify_regime_frame
from tfex_s50_multi_tf_swing.signals.errors import SignalInputError
from tfex_s50_multi_tf_swing.signals.models import SignalConfig

logger = logging.getLogger(__name__)

# Aligned-frame column names. 1H base columns are unprefixed; 1D columns are ``1d_{col}``.
COL_BIAS: str = "1d_bias_direction"
COL_REGIME: str = "1d_regime"

#: Raw price + causal level columns the base 1H frame carries (besides the feature panel).
_RAW_PRICE_COLUMNS: tuple[str, ...] = ("close", "high", "low", "swing_high", "swing_low")


def build_signal_inputs(
    frames: Mapping[Timeframe, pl.DataFrame],
    *,
    feature_config: FeatureConfig | None = None,
    regime_thresholds: RegimeThresholds | None = None,
    bias_config: BiasConfig | None = None,
    signal_config: SignalConfig | None = None,
) -> pl.DataFrame:
    """Build the aligned 1H signal-input frame from per-timeframe continuous OHLCV frames.

    Args:
        frames: Continuous OHLCV frames keyed by timeframe. ``"1h"`` and ``"1d"`` are
            required.
        feature_config: Feature windows; forced ``normalise=False`` (the rules read absolute
            signs, exactly like the regime / bias layers).
        regime_thresholds / bias_config: passed through to the regime / bias classifiers.
        signal_config: supplies ``swing_window`` for the causal swing levels.

    Returns:
        The 1H base panel widened with raw price + swing levels, ``1d_*`` features +
        ``1d_regime``, and ``1d_bias_direction`` (``"neutral"`` when the 1D frame is
        absent).
    """
    for required in ("1h", "1d"):
        if required not in frames:
            raise SignalInputError(f"signal inputs require a {required!r} frame")

    fc = (feature_config or FeatureConfig()).model_copy(update={"normalise": False})
    cfg = signal_config or SignalConfig()

    base = _build_base(frames["1h"], fc, cfg)
    higher: dict[Timeframe, pl.DataFrame] = {
        "1d": _build_d1(frames["1d"], fc, regime_thresholds, bias_config),
    }

    aligned = align_timeframes(base, base_timeframe="1h", higher=higher)
    if COL_BIAS not in aligned.columns:
        logger.info("no 1d frame supplied; %s defaults to 'neutral' (A/B will not fire)", COL_BIAS)
        aligned = aligned.with_columns(pl.lit("neutral").alias(COL_BIAS))
    return aligned


def _build_base(df: pl.DataFrame, fc: FeatureConfig, cfg: SignalConfig) -> pl.DataFrame:
    """1H feature panel + raw close/high/low + causal swing high/low."""
    panel = build_panel(df, "1h", fc)
    raw = (
        df.sort("time")
        .with_columns(
            pl.col("close").cast(pl.Float64),
            pl.col("high").cast(pl.Float64),
            pl.col("low").cast(pl.Float64),
        )
        .with_columns(
            pl.col("high").rolling_max(window_size=cfg.swing_window).shift(1).alias("swing_high"),
            pl.col("low").rolling_min(window_size=cfg.swing_window).shift(1).alias("swing_low"),
        )
        .select("time", *_RAW_PRICE_COLUMNS)
    )
    return panel.join(raw, on="time", how="left")


def _build_d1(
    df: pl.DataFrame,
    fc: FeatureConfig,
    regime_thresholds: RegimeThresholds | None,
    bias_config: BiasConfig | None,
) -> pl.DataFrame:
    """1D feature panel widened with the 1D regime label and 1D bias direction.

    Regime classification runs on the Daily frame — the market state is judged on the
    daily bar. Bias classification (the HTF directional veto) also runs on Daily,
    replacing the prior 4H bias engine. Both classifiers are timeframe-agnostic;
    only the caller changes which frame they consume.
    """
    panel = build_panel(df, "1d", fc)
    # Regime on the Daily frame.
    regime_inputs = build_regime_inputs(df, "1d", fc)
    regime = classify_regime_frame(regime_inputs, thresholds=regime_thresholds).select(
        "time", "regime"
    )
    panel_with_regime = panel.join(regime, on="time", how="left")
    # Bias on the Daily frame.
    bias_inputs = build_bias_inputs(
        df, "1d", feature_config=fc, regime_thresholds=regime_thresholds
    )
    classified = classify_bias_frame(bias_inputs, config=bias_config)
    return panel_with_regime.join(
        classified.select("time", "bias_direction"), on="time", how="left"
    )


__all__: list[str] = [
    "COL_BIAS",
    "COL_REGIME",
    "build_signal_inputs",
]
