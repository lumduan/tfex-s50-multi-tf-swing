"""Causal numeric primitives shared across feature groups.

Every primitive here is **trailing-only**: it uses information up to and
including the current bar, never a future bar. ``rolling_*`` windows end at the
current row (no ``center=True``); ``ewm_mean`` is causal by construction. The
two helpers that *need* future bars to confirm a pattern — :func:`with_swing_pivots`
— shift their output forward by the confirmation lag so the value at row ``i``
reflects only data available at ``i``.

Primitives operate on **Float64** columns named ``open/high/low/close/volume``.
The pipeline casts the Decimal prices read from the store to Float64 before
calling any of these. Wilder-style smoothing (ATR, ADX) uses an exponential
moving average with ``alpha = 1/period`` (``adjust=False``), the standard RMA
approximation; it is deterministic and matches common TA libraries.
"""

from __future__ import annotations

import polars as pl

# --------------------------------------------------------------------------
# Returns / moving averages
# --------------------------------------------------------------------------


def log_return(close: str = "close") -> pl.Expr:
    """Bar-to-bar log return; the first row is null (no prior bar)."""
    col = pl.col(close)
    return (col / col.shift(1)).log()


def ema(col: str, span: int) -> pl.Expr:
    """Exponential moving average (causal, ``adjust=False``)."""
    return pl.col(col).ewm_mean(span=span, adjust=False)


def ema_slope(col: str, span: int, lookback: int) -> pl.Expr:
    """Per-bar EMA slope ``(EMA_t - EMA_{t-lookback}) / lookback``.

    Not yet ATR-normalised — the caller divides by ATR to make it
    regime-invariant.
    """
    e = ema(col, span)
    return (e - e.shift(lookback)) / lookback


# --------------------------------------------------------------------------
# True range / ATR
# --------------------------------------------------------------------------


def true_range() -> pl.Expr:
    """Wilder true range: ``max(H-L, |H-C_prev|, |L-C_prev|)``."""
    prev_close = pl.col("close").shift(1)
    hl = pl.col("high") - pl.col("low")
    hc = (pl.col("high") - prev_close).abs()
    lc = (pl.col("low") - prev_close).abs()
    return pl.max_horizontal(hl, hc, lc)


def atr(period: int) -> pl.Expr:
    """Average true range via Wilder RMA (``alpha = 1/period``)."""
    return true_range().ewm_mean(alpha=1.0 / period, adjust=False)


def realised_vol(window: int, close: str = "close") -> pl.Expr:
    """Rolling standard deviation of log returns over ``window`` bars (trailing)."""
    return log_return(close).rolling_std(window_size=window)


# --------------------------------------------------------------------------
# Channel widths
# --------------------------------------------------------------------------


def bollinger_width(period: int, k: float, close: str = "close") -> pl.Expr:
    """Bollinger band width ``2 * k * rolling_std(close, period)`` (trailing)."""
    return 2.0 * k * pl.col(close).rolling_std(window_size=period)


def keltner_width(period: int, m: float) -> pl.Expr:
    """Keltner channel width ``2 * m * ATR(period)``."""
    return 2.0 * m * atr(period)


# --------------------------------------------------------------------------
# Normalisation (trailing, no global stats)
# --------------------------------------------------------------------------


def rolling_zscore(expr: pl.Expr, window: int) -> pl.Expr:
    """Z-score of ``expr`` against its own trailing ``window`` (mean/std)."""
    mean = expr.rolling_mean(window_size=window)
    std = expr.rolling_std(window_size=window)
    return (expr - mean) / std


def winsorize(expr: pl.Expr, lower_q: float, upper_q: float, window: int) -> pl.Expr:
    """Clip ``expr`` to its trailing rolling [lower_q, upper_q] quantiles."""
    lo = expr.rolling_quantile(quantile=lower_q, window_size=window)
    hi = expr.rolling_quantile(quantile=upper_q, window_size=window)
    return expr.clip(lower_bound=lo, upper_bound=hi)


# --------------------------------------------------------------------------
# ADX (multi-step → frame-augmenting helper)
# --------------------------------------------------------------------------


def with_adx(df: pl.DataFrame, period: int) -> pl.DataFrame:
    """Append a Float64 ``adx`` column (Wilder ADX). Causal, trailing.

    Expects ``high/low/close`` Float64 columns sorted ascending by time.
    """
    up_move = pl.col("high") - pl.col("high").shift(1)
    down_move = pl.col("low").shift(1) - pl.col("low")
    alpha = 1.0 / period
    out = df.with_columns(
        pl.when((up_move > down_move) & (up_move > 0)).then(up_move).otherwise(0.0).alias("_pdm"),
        pl.when((down_move > up_move) & (down_move > 0))
        .then(down_move)
        .otherwise(0.0)
        .alias("_mdm"),
        true_range().alias("_tr"),
    )
    out = out.with_columns(
        pl.col("_tr").ewm_mean(alpha=alpha, adjust=False).alias("_adx_atr"),
        pl.col("_pdm").ewm_mean(alpha=alpha, adjust=False).alias("_pdm_s"),
        pl.col("_mdm").ewm_mean(alpha=alpha, adjust=False).alias("_mdm_s"),
    )
    out = out.with_columns(
        (100.0 * pl.col("_pdm_s") / pl.col("_adx_atr")).alias("_pdi"),
        (100.0 * pl.col("_mdm_s") / pl.col("_adx_atr")).alias("_mdi"),
    )
    di_sum = pl.col("_pdi") + pl.col("_mdi")
    out = out.with_columns(
        pl.when(di_sum != 0)
        .then(100.0 * (pl.col("_pdi") - pl.col("_mdi")).abs() / di_sum)
        .otherwise(0.0)
        .alias("_dx")
    )
    out = out.with_columns(pl.col("_dx").ewm_mean(alpha=alpha, adjust=False).alias("adx"))
    return out.drop(["_pdm", "_mdm", "_tr", "_adx_atr", "_pdm_s", "_mdm_s", "_pdi", "_mdi", "_dx"])


# --------------------------------------------------------------------------
# Swing pivots (confirmation lag shifted forward → causal)
# --------------------------------------------------------------------------


def with_swing_pivots(df: pl.DataFrame, lookback: int) -> pl.DataFrame:
    """Append confirmed swing pivot prices ``_pivot_high`` / ``_pivot_low``.

    A bar ``lookback`` rows back is a confirmed swing high when its ``high`` is
    the maximum across the symmetric ``2*lookback + 1`` window centred on it.
    Because the right half of that window is in the future relative to the
    pivot, the pivot can only be *confirmed* ``lookback`` bars later — so the
    confirmed price is written at the confirmation bar (current row), i.e.
    ``high.shift(lookback)``. The columns are null on bars that do not confirm
    a pivot. Equality is exact (the pivot value is itself a window member), so
    no float tolerance is required.
    """
    window = 2 * lookback + 1
    roll_max = pl.col("high").rolling_max(window_size=window)
    roll_min = pl.col("low").rolling_min(window_size=window)
    candidate_high = pl.col("high").shift(lookback)
    candidate_low = pl.col("low").shift(lookback)
    return df.with_columns(
        pl.when(candidate_high == roll_max)
        .then(candidate_high)
        .otherwise(None)
        .alias("_pivot_high"),
        pl.when(candidate_low == roll_min).then(candidate_low).otherwise(None).alias("_pivot_low"),
    )


__all__: list[str] = [
    "atr",
    "bollinger_width",
    "ema",
    "ema_slope",
    "keltner_width",
    "log_return",
    "realised_vol",
    "rolling_zscore",
    "true_range",
    "winsorize",
    "with_adx",
    "with_swing_pivots",
]
