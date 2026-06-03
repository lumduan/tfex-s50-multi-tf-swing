"""Build the aligned 5m signal-input frame (the multi-timeframe substrate for §5.1–5.3).

Setups span three timeframes — 4H HTF bias, 1H setup context, 5m trigger. Rather than join
frames ad-hoc, :func:`build_signal_inputs` resolves everything onto the **5m** grid using the
Phase-2 causal aligner (:func:`tfex_s50_multi_tf_swing.features.align.align_timeframes`): every
higher-timeframe column is availability-shifted by its bar duration, so an HTF value can only
appear on a 5m bar once the HTF bar has *closed*. This is the single most dangerous look-ahead
trap in a multi-timeframe system; ``tests/unit/signals/test_inputs.py`` asserts no future value
leaks.

The frame carries, per 5m bar:

* the 5m feature columns (``atr_ratio``, ``bollinger_squeeze``, ``volume_expansion``,
  ``dist_from_vwap``, ``structure``, ``or_high_*`` / ``or_low_*``, ``liquidity_sweep_flag``,
  ``lunch_zone_flag``) — already on the base panel;
* the raw 5m ``close`` / ``high`` / ``low`` plus causal ``swing_high`` / ``swing_low``
  (rolling extremes, shifted) used for triggers and the structure stop anchor;
* ``1h_*`` features and the **1H regime** (``1h_regime``) that gates which strategies may trade;
* the **4H bias** (``4h_bias_direction``) that vetoes counter-trend A / B trades.

**Source-agnostic + 4h-aware.** This builder consumes already-loaded continuous OHLCV frames
(mirror or engine); it never fetches tvkit / the engine. On the ``engine`` source the 4H frame
is **absent** (the engine declines ``4h`` before any I/O — no local rollup, Decision D10), so
``4h_bias_direction`` is filled ``"neutral"`` and A / B emit no signals (a documented safe
degrade), while C — gated on the 1H regime, not the 4H bias — can still run.
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

# Aligned-frame column names. 5m base columns are unprefixed; higher TFs are ``{tf}_{col}``.
COL_BIAS: str = "4h_bias_direction"
COL_REGIME: str = "1h_regime"
COL_H1_VWAP: str = "1h_dist_from_vwap"
COL_H1_STRUCT: str = "1h_structure"
COL_H1_ATR_RATIO: str = "1h_atr_ratio"
COL_H1_VOL_EXP: str = "1h_volume_expansion"

#: Raw price + causal level columns the base 5m frame carries (besides the feature panel).
_RAW_PRICE_COLUMNS: tuple[str, ...] = ("close", "high", "low", "swing_high", "swing_low")


def build_signal_inputs(
    frames: Mapping[Timeframe, pl.DataFrame],
    *,
    feature_config: FeatureConfig | None = None,
    regime_thresholds: RegimeThresholds | None = None,
    bias_config: BiasConfig | None = None,
    signal_config: SignalConfig | None = None,
) -> pl.DataFrame:
    """Build the aligned 5m signal-input frame from per-timeframe continuous OHLCV frames.

    Args:
        frames: Continuous OHLCV frames keyed by timeframe. ``"5m"`` and ``"1h"`` are required;
            ``"4h"`` is optional (absent on the ``engine`` source).
        feature_config: Feature windows; forced ``normalise=False`` (the rules read absolute
            signs, exactly like the regime / bias layers).
        regime_thresholds / bias_config: passed through to the regime / bias classifiers.
        signal_config: supplies ``swing_window`` for the causal swing levels.

    Returns:
        The 5m base panel widened with raw price + swing levels, ``1h_*`` features + ``1h_regime``,
        and ``4h_bias_direction`` (``"neutral"`` when the 4H frame is absent).
    """
    for required in ("5m", "1h"):
        if required not in frames:
            raise SignalInputError(f"signal inputs require a {required!r} frame")

    fc = (feature_config or FeatureConfig()).model_copy(update={"normalise": False})
    cfg = signal_config or SignalConfig()

    base = _build_base(frames["5m"], fc, cfg)
    higher: dict[Timeframe, pl.DataFrame] = {"1h": _build_h1(frames["1h"], fc, regime_thresholds)}
    if "4h" in frames:
        higher["4h"] = _build_h4(frames["4h"], fc, regime_thresholds, bias_config)

    aligned = align_timeframes(base, base_timeframe="5m", higher=higher)
    if COL_BIAS not in aligned.columns:
        logger.info("no 4h frame supplied; %s defaults to 'neutral' (A/B will not fire)", COL_BIAS)
        aligned = aligned.with_columns(pl.lit("neutral").alias(COL_BIAS))
    return aligned


def _build_base(df: pl.DataFrame, fc: FeatureConfig, cfg: SignalConfig) -> pl.DataFrame:
    """5m feature panel + raw close/high/low + causal swing high/low."""
    panel = build_panel(df, "5m", fc)
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


def _build_h1(
    df: pl.DataFrame, fc: FeatureConfig, regime_thresholds: RegimeThresholds | None
) -> pl.DataFrame:
    """1H feature panel widened with the 1H regime label (gates the strategy whitelist)."""
    panel = build_panel(df, "1h", fc)
    regime_inputs = build_regime_inputs(df, "1h", fc)
    regime = classify_regime_frame(regime_inputs, thresholds=regime_thresholds).select(
        "time", "regime"
    )
    return panel.join(regime, on="time", how="left")


def _build_h4(
    df: pl.DataFrame,
    fc: FeatureConfig,
    regime_thresholds: RegimeThresholds | None,
    bias_config: BiasConfig | None,
) -> pl.DataFrame:
    """4H frame carrying only the per-4H ``bias_direction`` (the HTF veto)."""
    bias_inputs = build_bias_inputs(
        df, "4h", feature_config=fc, regime_thresholds=regime_thresholds
    )
    classified = classify_bias_frame(bias_inputs, config=bias_config)
    return classified.select("time", "bias_direction")


__all__: list[str] = [
    "COL_BIAS",
    "COL_H1_ATR_RATIO",
    "COL_H1_STRUCT",
    "COL_H1_VOL_EXP",
    "COL_H1_VWAP",
    "COL_REGIME",
    "build_signal_inputs",
]
