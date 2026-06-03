"""Strategy A — Pullback Continuation ⭐ (primary) (ROADMAP §5.1).

Pattern: impulse → pullback → compression → continuation, read on the aligned 5m frame:

1. **4H** — HTF bias is directional (``4h_bias_direction``) and the **1H regime** whitelists A.
2. **1H** — pullback to value: price near session VWAP (``|1h_dist_from_vwap| ≤ pullback_band``),
   structure intact (HH/HL for long), ATR contracting (``1h_atr_ratio ≤ atr_contraction_max``),
   volume contracting (``1h_volume_expansion ≤ volume_contraction_max``).
3. **5m** — volatility compression (``bollinger_squeeze`` or ``atr_ratio`` below its threshold).
4. **5m** — trigger: breakout of the recent swing high + VWAP reclaim (``dist_from_vwap > 0``) +
   volume expansion (``volume_expansion ≥ volume_expansion_min``).

Short is the exact mirror. Like the bias engine, a setup fires only on **full agreement**; any
failing or null gate yields no signal (never a guess). ``stop_reference`` is the opposite recent
swing extreme — the structure invalidation the execution engine anchors its ``k·ATR`` stop to.
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl

from tfex_s50_multi_tf_swing.regime.models import BEARISH_STRUCTURE, BULLISH_STRUCTURE
from tfex_s50_multi_tf_swing.signals import base
from tfex_s50_multi_tf_swing.signals.inputs import (
    COL_BIAS,
    COL_H1_ATR_RATIO,
    COL_H1_STRUCT,
    COL_H1_VOL_EXP,
    COL_H1_VWAP,
    COL_REGIME,
)
from tfex_s50_multi_tf_swing.signals.models import (
    SetupDirection,
    SetupFeatures,
    SetupSignal,
    SignalConfig,
    StrategyId,
)

STRATEGY_ID: StrategyId = "A"

#: Columns :func:`classify_frame` reads off the aligned 5m frame.
REQUIRED_COLUMNS: tuple[str, ...] = (
    COL_BIAS,
    COL_REGIME,
    COL_H1_VWAP,
    COL_H1_STRUCT,
    COL_H1_ATR_RATIO,
    COL_H1_VOL_EXP,
    "bollinger_squeeze",
    "atr_ratio",
    "dist_from_vwap",
    "volume_expansion",
    "close",
    "swing_high",
    "swing_low",
)


def classify_frame(df: pl.DataFrame, *, config: SignalConfig | None = None) -> pl.DataFrame:
    """Append ``signal`` / ``reasons`` / ``trigger_price`` / ``stop_reference`` columns."""
    config = config or SignalConfig()
    base.require_columns(df, REQUIRED_COLUMNS, what="strategy A input frame")
    long_gate = _long_gate(config)
    short_gate = _short_gate(config)
    return df.with_columns(
        base.direction_expr(long_gate, short_gate).alias(base.SIGNAL),
        base.reasons_expr(STRATEGY_ID, long_gate, short_gate).alias(base.REASONS),
        base.price_expr(long_gate, short_gate, on_long="close", on_short="close").alias(
            base.TRIGGER_PRICE
        ),
        base.price_expr(long_gate, short_gate, on_long="swing_low", on_short="swing_high").alias(
            base.STOP_REFERENCE
        ),
    )


def _compression_expr(config: SignalConfig) -> pl.Expr:
    return (pl.col("bollinger_squeeze") <= config.squeeze_max) | (
        pl.col("atr_ratio") <= config.atr_compression_max
    )


def _long_gate(config: SignalConfig) -> pl.Expr:
    return (
        (pl.col(COL_BIAS) == "long")
        & pl.col(COL_REGIME).is_in(base.regimes_allowing(STRATEGY_ID))
        & (pl.col(COL_H1_VWAP).abs() <= config.pullback_band)
        & pl.col(COL_H1_STRUCT).is_in(list(BULLISH_STRUCTURE))
        & (pl.col(COL_H1_ATR_RATIO) <= config.atr_contraction_max)
        & (pl.col(COL_H1_VOL_EXP) <= config.volume_contraction_max)
        & _compression_expr(config)
        & (pl.col("close") > pl.col("swing_high"))
        & (pl.col("dist_from_vwap") > 0.0)
        & (pl.col("volume_expansion") >= config.volume_expansion_min)
        & pl.col("swing_low").is_not_null()
    ).fill_null(False)


def _short_gate(config: SignalConfig) -> pl.Expr:
    return (
        (pl.col(COL_BIAS) == "short")
        & pl.col(COL_REGIME).is_in(base.regimes_allowing(STRATEGY_ID))
        & (pl.col(COL_H1_VWAP).abs() <= config.pullback_band)
        & pl.col(COL_H1_STRUCT).is_in(list(BEARISH_STRUCTURE))
        & (pl.col(COL_H1_ATR_RATIO) <= config.atr_contraction_max)
        & (pl.col(COL_H1_VOL_EXP) <= config.volume_contraction_max)
        & _compression_expr(config)
        & (pl.col("close") < pl.col("swing_low"))
        & (pl.col("dist_from_vwap") < 0.0)
        & (pl.col("volume_expansion") >= config.volume_expansion_min)
        & pl.col("swing_high").is_not_null()
    ).fill_null(False)


def _compression_ok(f: SetupFeatures, config: SignalConfig) -> bool:
    return base.le(f.bollinger_squeeze, config.squeeze_max) or base.le(
        f.atr_ratio, config.atr_compression_max
    )


def _h1_pullback(f: SetupFeatures, config: SignalConfig, *, bullish: bool) -> bool:
    structure = BULLISH_STRUCTURE if bullish else BEARISH_STRUCTURE
    return (
        f.h1_dist_from_vwap is not None
        and abs(f.h1_dist_from_vwap) <= config.pullback_band
        and f.h1_structure in structure
        and base.le(f.h1_atr_ratio, config.atr_contraction_max)
        and base.le(f.h1_volume_expansion, config.volume_contraction_max)
    )


def _row_long(f: SetupFeatures, config: SignalConfig) -> bool:
    return (
        f.bias_direction == "long"
        and f.regime in base.regimes_allowing(STRATEGY_ID)
        and _h1_pullback(f, config, bullish=True)
        and _compression_ok(f, config)
        and f.swing_high is not None
        and base.gt(f.close, f.swing_high)
        and base.gt(f.dist_from_vwap, 0.0)
        and base.ge(f.volume_expansion, config.volume_expansion_min)
        and f.swing_low is not None
    )


def _row_short(f: SetupFeatures, config: SignalConfig) -> bool:
    return (
        f.bias_direction == "short"
        and f.regime in base.regimes_allowing(STRATEGY_ID)
        and _h1_pullback(f, config, bullish=False)
        and _compression_ok(f, config)
        and f.swing_low is not None
        and base.lt(f.close, f.swing_low)
        and base.lt(f.dist_from_vwap, 0.0)
        and base.ge(f.volume_expansion, config.volume_expansion_min)
        and f.swing_high is not None
    )


def classify_row(features: SetupFeatures, config: SignalConfig | None = None) -> SetupSignal | None:
    """Scalar mirror of :func:`classify_frame`; returns ``None`` when no setup fires."""
    config = config or SignalConfig()
    direction: SetupDirection
    if _row_long(features, config):
        direction, stop = "long", features.swing_low
    elif _row_short(features, config):
        direction, stop = "short", features.swing_high
    else:
        return None
    if stop is None:  # pragma: no cover — the gates already require a non-null stop
        return None
    return SetupSignal(
        strategy_id=STRATEGY_ID,
        time=features.time,
        direction=direction,
        trigger_price=Decimal(str(features.close)),
        stop_reference=Decimal(str(stop)),
        regime=features.regime,
        reasons=base.row_reasons(
            STRATEGY_ID, direction, bias=features.bias_direction, regime=features.regime
        ),
    )


def to_signals(df: pl.DataFrame) -> list[SetupSignal]:
    """Materialise one :class:`SetupSignal` per fired Strategy-A bar."""
    return base.to_signals(df, strategy_id=STRATEGY_ID)


__all__: list[str] = ["REQUIRED_COLUMNS", "classify_frame", "classify_row", "to_signals"]
