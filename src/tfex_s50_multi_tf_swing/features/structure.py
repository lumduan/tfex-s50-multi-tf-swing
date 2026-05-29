"""§2.4 Market-structure features.

* ``overnight_gap`` — ``(session_open - prev_session_close) / ATR``.
* ``dist_to_prev_high`` / ``dist_to_prev_low`` — distance of close from the
  previous trading day's high / low, in ATR units.
* ``ib_high`` / ``ib_low`` — initial-balance (first-hour) extremes (intraday TFs).
* ``liquidity_sweep_flag`` — a recent swing high/low is pierced and price
  reverses back through it within ``k`` bars. The flag is emitted at the
  confirmation bar ``t+k`` so it never uses information from beyond ``t+k``.

Expects the working frame to carry ``_atr``, ``session_date`` and
``session_name`` (added upstream by the pipeline).
"""

from __future__ import annotations

import polars as pl

from tfex_s50_multi_tf_swing.data.models import Timeframe
from tfex_s50_multi_tf_swing.features.models import INTRADAY_TIMEFRAMES, FeatureConfig
from tfex_s50_multi_tf_swing.features.time_of_day import _MORN_START


def add_structure(df: pl.DataFrame, config: FeatureConfig, timeframe: Timeframe) -> pl.DataFrame:
    """Add the §2.4 market-structure feature columns."""
    out = _add_prev_day(df)
    out = out.with_columns(
        ((pl.col("_session_open") - pl.col("_prev_close")) / pl.col("_atr")).alias("overnight_gap"),
        ((pl.col("close") - pl.col("_prev_high")) / pl.col("_atr")).alias("dist_to_prev_high"),
        ((pl.col("close") - pl.col("_prev_low")) / pl.col("_atr")).alias("dist_to_prev_low"),
    )
    out = out.with_columns(_liquidity_sweep_flag(config).alias("liquidity_sweep_flag"))
    if timeframe in INTRADAY_TIMEFRAMES:
        out = _add_initial_balance(out, config)
    return out.drop(["_session_open", "_prev_close", "_prev_high", "_prev_low"])


def _add_prev_day(df: pl.DataFrame) -> pl.DataFrame:
    """Join per-session aggregates and the strictly-prior session's H/L/close."""
    day_agg = (
        df.group_by("session_date")
        .agg(
            pl.col("open").sort_by("time").first().alias("_session_open"),
            pl.col("close").sort_by("time").last().alias("_session_close"),
            pl.col("high").max().alias("_day_high"),
            pl.col("low").min().alias("_day_low"),
        )
        .sort("session_date")
    )
    day_agg = day_agg.with_columns(
        pl.col("_session_close").shift(1).alias("_prev_close"),
        pl.col("_day_high").shift(1).alias("_prev_high"),
        pl.col("_day_low").shift(1).alias("_prev_low"),
    )
    return df.join(
        day_agg.select(["session_date", "_session_open", "_prev_close", "_prev_high", "_prev_low"]),
        on="session_date",
        how="left",
    )


def _add_initial_balance(df: pl.DataFrame, config: FeatureConfig) -> pl.DataFrame:
    """First-hour high/low per session, exposed only once the IB window closes."""
    m = pl.col("_bkk_minute")
    ib = config.initial_balance_minutes
    in_window = (pl.col("session_name") == "morning") & (m >= _MORN_START) & (m < _MORN_START + ib)
    window_closed = m >= _MORN_START + ib
    hi = pl.when(in_window).then(pl.col("high")).otherwise(None).max().over("session_date")
    lo = pl.when(in_window).then(pl.col("low")).otherwise(None).min().over("session_date")
    return df.with_columns(
        pl.when(window_closed).then(hi).otherwise(None).cast(pl.Float64).alias("ib_high"),
        pl.when(window_closed).then(lo).otherwise(None).cast(pl.Float64).alias("ib_low"),
    )


def _liquidity_sweep_flag(config: FeatureConfig) -> pl.Expr:
    """Sweep + reversal within ``k`` bars, shifted forward to the confirmation bar."""
    k = config.liquidity_confirm_bars
    recent_high = pl.col("high").rolling_max(window_size=config.liquidity_lookback).shift(1)
    recent_low = pl.col("low").rolling_min(window_size=config.liquidity_lookback).shift(1)

    pierced_up = pl.col("high") > recent_high
    pierced_down = pl.col("low") < recent_low

    future_min_close = pl.min_horizontal(*[pl.col("close").shift(-i) for i in range(1, k + 1)])
    future_max_close = pl.max_horizontal(*[pl.col("close").shift(-i) for i in range(1, k + 1)])

    swept_up = pierced_up & (future_min_close < recent_high)
    swept_down = pierced_down & (future_max_close > recent_low)
    raw = (swept_up | swept_down).fill_null(False)
    # Emit at t+k: the value at row r reflects a sweep completed using bars up to r.
    return raw.shift(k).fill_null(False).cast(pl.Int8)


__all__: list[str] = ["add_structure"]
