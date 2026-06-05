"""Strategy C — Liquidity-Sweep Reversal (ROADMAP §5.3).

**Permanently disabled per the 1H-execution migration (2026-06-05).** This strategy was
identified as the primary drawdown driver in the 14-month walk-forward (294 trades at
+0.01R, 49.0% win rate, 31.13R max drawdown contribution) and has been removed from the
active registry in ``gate.py``. The module remains importable for reference but no code
path reaches it.

On the aligned 5m frame (legacy):

1. The **1H regime** whitelists C (``range_high_vol`` per the Phase-3 policy).
2. A liquidity sweep + reversal has just confirmed (``liquidity_sweep_flag == 1`` — the Phase-2
   feature, already shifted to its confirmation bar, so it is look-ahead-free).
3. Reversal direction: the close has reclaimed the *other* side of session VWAP —
   ``dist_from_vwap > 0`` ⇒ long (a swept low that reversed up), ``< 0`` ⇒ short.
4. Optional structure-shift confirmation (``require_structure_shift``): the 5m structure has
   flipped to the reversal side (HH/HL for long, LH/LL for short).

Unlike A / B, **C does not require the 4H bias** — so it still runs on the ``engine`` OHLCV
source where ``4h`` is unavailable. The ML ``P(fake_breakout)`` filter that would discard fake
breakouts is **Phase 6** (a documented extension point, not implemented here). ``stop_reference``
sits beyond the swept extreme (the recent swing low for a long, swing high for a short).
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl

from tfex_s50_multi_tf_swing.regime.models import BEARISH_STRUCTURE, BULLISH_STRUCTURE
from tfex_s50_multi_tf_swing.signals import base
from tfex_s50_multi_tf_swing.signals.inputs import COL_BIAS, COL_REGIME
from tfex_s50_multi_tf_swing.signals.models import (
    SetupDirection,
    SetupFeatures,
    SetupSignal,
    SignalConfig,
    StrategyId,
)

STRATEGY_ID: StrategyId = "C"

#: Columns :func:`classify_frame` reads off the aligned 5m frame (``COL_BIAS`` only for reasons).
REQUIRED_COLUMNS: tuple[str, ...] = (
    COL_BIAS,
    COL_REGIME,
    "liquidity_sweep_flag",
    "dist_from_vwap",
    "structure",
    "close",
    "swing_high",
    "swing_low",
)


def classify_frame(df: pl.DataFrame, *, config: SignalConfig | None = None) -> pl.DataFrame:
    """Append ``signal`` / ``reasons`` / ``trigger_price`` / ``stop_reference`` columns."""
    config = config or SignalConfig()
    base.require_columns(df, REQUIRED_COLUMNS, what="strategy C input frame")
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


def _swept() -> pl.Expr:
    return pl.col(COL_REGIME).is_in(base.regimes_allowing(STRATEGY_ID)) & (
        pl.col("liquidity_sweep_flag") == 1
    )


def _long_gate(config: SignalConfig) -> pl.Expr:
    gate = _swept() & (pl.col("dist_from_vwap") > 0.0) & pl.col("swing_low").is_not_null()
    if config.require_structure_shift:
        gate = gate & pl.col("structure").is_in(list(BULLISH_STRUCTURE))
    return gate.fill_null(False)


def _short_gate(config: SignalConfig) -> pl.Expr:
    gate = _swept() & (pl.col("dist_from_vwap") < 0.0) & pl.col("swing_high").is_not_null()
    if config.require_structure_shift:
        gate = gate & pl.col("structure").is_in(list(BEARISH_STRUCTURE))
    return gate.fill_null(False)


def _row_swept(f: SetupFeatures) -> bool:
    return f.regime in base.regimes_allowing(STRATEGY_ID) and f.liquidity_sweep_flag == 1


def _row_long(f: SetupFeatures, config: SignalConfig) -> bool:
    ok = _row_swept(f) and base.gt(f.dist_from_vwap, 0.0) and f.swing_low is not None
    if config.require_structure_shift:
        ok = ok and f.structure in BULLISH_STRUCTURE
    return ok


def _row_short(f: SetupFeatures, config: SignalConfig) -> bool:
    ok = _row_swept(f) and base.lt(f.dist_from_vwap, 0.0) and f.swing_high is not None
    if config.require_structure_shift:
        ok = ok and f.structure in BEARISH_STRUCTURE
    return ok


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
    """Materialise one :class:`SetupSignal` per fired Strategy-C bar."""
    return base.to_signals(df, strategy_id=STRATEGY_ID)


__all__: list[str] = ["REQUIRED_COLUMNS", "classify_frame", "classify_row", "to_signals"]
