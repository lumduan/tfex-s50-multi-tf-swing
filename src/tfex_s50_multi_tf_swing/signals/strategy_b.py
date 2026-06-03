"""Strategy B — Opening-Range Breakout (ROADMAP §5.2).

On the aligned 5m frame:

1. Opening range = the first ``or_window`` minutes (default 15), read from the pipeline columns
   ``or_high_{or_window}`` / ``or_low_{or_window}``.
2. Breakout: ``close > or_high`` (long) / ``close < or_low`` (short) with volume expansion
   (``volume_expansion ≥ volume_expansion_min``).
3. HTF-aligned: ``4h_bias_direction`` matches the breakout side.
4. Suppressed in the lunch dead-zone (``lunch_zone_flag == 1``) and in any regime whose Phase-3
   policy does not whitelist B (which already excludes ``range_low_vol``).

``stop_reference`` is the opposite opening-range extreme.
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl

from tfex_s50_multi_tf_swing.signals import base
from tfex_s50_multi_tf_swing.signals.inputs import COL_BIAS, COL_REGIME
from tfex_s50_multi_tf_swing.signals.models import (
    SetupDirection,
    SetupFeatures,
    SetupSignal,
    SignalConfig,
    StrategyId,
)

STRATEGY_ID: StrategyId = "B"


def _or_columns(config: SignalConfig) -> tuple[str, str]:
    """The opening-range high / low column names for the configured window."""
    return f"or_high_{config.or_window}", f"or_low_{config.or_window}"


def required_columns(config: SignalConfig) -> tuple[str, ...]:
    """Columns :func:`classify_frame` reads (the opening-range pair depends on ``or_window``)."""
    or_high, or_low = _or_columns(config)
    return (COL_BIAS, COL_REGIME, "close", "volume_expansion", "lunch_zone_flag", or_high, or_low)


def classify_frame(df: pl.DataFrame, *, config: SignalConfig | None = None) -> pl.DataFrame:
    """Append ``signal`` / ``reasons`` / ``trigger_price`` / ``stop_reference`` columns."""
    config = config or SignalConfig()
    base.require_columns(df, required_columns(config), what="strategy B input frame")
    or_high, or_low = _or_columns(config)
    long_gate = _long_gate(config, or_high, or_low)
    short_gate = _short_gate(config, or_high, or_low)
    return df.with_columns(
        base.direction_expr(long_gate, short_gate).alias(base.SIGNAL),
        base.reasons_expr(STRATEGY_ID, long_gate, short_gate).alias(base.REASONS),
        base.price_expr(long_gate, short_gate, on_long="close", on_short="close").alias(
            base.TRIGGER_PRICE
        ),
        base.price_expr(long_gate, short_gate, on_long=or_low, on_short=or_high).alias(
            base.STOP_REFERENCE
        ),
    )


def _long_gate(config: SignalConfig, or_high: str, or_low: str) -> pl.Expr:
    return (
        (pl.col(COL_BIAS) == "long")
        & pl.col(COL_REGIME).is_in(base.regimes_allowing(STRATEGY_ID))
        & (pl.col("lunch_zone_flag") == 0)
        & (pl.col("close") > pl.col(or_high))
        & (pl.col("volume_expansion") >= config.volume_expansion_min)
        & pl.col(or_low).is_not_null()
    ).fill_null(False)


def _short_gate(config: SignalConfig, or_high: str, or_low: str) -> pl.Expr:
    return (
        (pl.col(COL_BIAS) == "short")
        & pl.col(COL_REGIME).is_in(base.regimes_allowing(STRATEGY_ID))
        & (pl.col("lunch_zone_flag") == 0)
        & (pl.col("close") < pl.col(or_low))
        & (pl.col("volume_expansion") >= config.volume_expansion_min)
        & pl.col(or_high).is_not_null()
    ).fill_null(False)


def _row_long(f: SetupFeatures, config: SignalConfig) -> bool:
    return (
        f.bias_direction == "long"
        and f.regime in base.regimes_allowing(STRATEGY_ID)
        and f.lunch_zone_flag == 0
        and f.or_high is not None
        and base.gt(f.close, f.or_high)
        and base.ge(f.volume_expansion, config.volume_expansion_min)
        and f.or_low is not None
    )


def _row_short(f: SetupFeatures, config: SignalConfig) -> bool:
    return (
        f.bias_direction == "short"
        and f.regime in base.regimes_allowing(STRATEGY_ID)
        and f.lunch_zone_flag == 0
        and f.or_low is not None
        and base.lt(f.close, f.or_low)
        and base.ge(f.volume_expansion, config.volume_expansion_min)
        and f.or_high is not None
    )


def classify_row(features: SetupFeatures, config: SignalConfig | None = None) -> SetupSignal | None:
    """Scalar mirror of :func:`classify_frame`; returns ``None`` when no setup fires."""
    config = config or SignalConfig()
    direction: SetupDirection
    if _row_long(features, config):
        direction, stop = "long", features.or_low
    elif _row_short(features, config):
        direction, stop = "short", features.or_high
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
    """Materialise one :class:`SetupSignal` per fired Strategy-B bar."""
    return base.to_signals(df, strategy_id=STRATEGY_ID)


__all__: list[str] = ["classify_frame", "classify_row", "required_columns", "to_signals"]
