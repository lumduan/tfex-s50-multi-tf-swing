"""§2.1 Trend features.

* ``ema_slope_{n}`` — ATR-normalised slope of the ``n``-span EMA.
* ``dist_from_vwap`` — distance of close from the session VWAP, in ATR units.
* ``structure`` — HH/HL/LH/LL classification from the most-recent *confirmed*
  swing pivot (see :func:`tfex_s50_multi_tf_swing.features.indicators.with_swing_pivots`).

Expects the working frame to already carry ``_atr`` (current ATR), the session
columns from :func:`tfex_s50_multi_tf_swing.features.time_of_day.with_session_columns`,
and the ``_pivot_high`` / ``_pivot_low`` columns from ``with_swing_pivots``.
"""

from __future__ import annotations

import polars as pl

from tfex_s50_multi_tf_swing.features.indicators import ema_slope
from tfex_s50_multi_tf_swing.features.models import FeatureConfig


def add_trend(df: pl.DataFrame, config: FeatureConfig) -> pl.DataFrame:
    """Add the §2.1 trend feature columns."""
    out = df.with_columns(
        *[
            (ema_slope("close", span=n, lookback=n) / pl.col("_atr")).alias(f"ema_slope_{n}")
            for n in config.ema_spans
        ],
        _session_vwap_dist().alias("dist_from_vwap"),
    )
    return _add_structure(out)


def _session_vwap_dist() -> pl.Expr:
    """``(close - session VWAP) / ATR``; VWAP is a causal per-session cumulative."""
    typical = (pl.col("high") + pl.col("low") + pl.col("close")) / 3.0
    cum_pv = (typical * pl.col("volume")).cum_sum().over("session_date")
    cum_v = pl.col("volume").cum_sum().over("session_date")
    vwap = cum_pv / cum_v
    return (pl.col("close") - vwap) / pl.col("_atr")


def _add_structure(df: pl.DataFrame) -> pl.DataFrame:
    """Classify market structure from confirmed swing pivots (causal).

    ``last_*`` is the forward-filled most-recent confirmed pivot; ``prev_*`` is
    the one before it (captured at the bar a new pivot confirms, then
    forward-filled). The label reflects whichever pivot type confirmed most
    recently. Null until two pivots of that type exist.
    """
    idx = pl.int_range(0, pl.len())
    ph = pl.col("_pivot_high")
    pl_ = pl.col("_pivot_low")

    out = df.with_columns(
        ph.forward_fill().alias("_last_ph"),
        pl_.forward_fill().alias("_last_pl"),
        pl.when(ph.is_not_null())
        .then(ph.forward_fill().shift(1))
        .otherwise(None)
        .alias("_prev_ph_mark"),
        pl.when(pl_.is_not_null())
        .then(pl_.forward_fill().shift(1))
        .otherwise(None)
        .alias("_prev_pl_mark"),
        pl.when(ph.is_not_null()).then(idx).otherwise(None).forward_fill().alias("_ph_idx"),
        pl.when(pl_.is_not_null()).then(idx).otherwise(None).forward_fill().alias("_pl_idx"),
    )
    out = out.with_columns(
        pl.col("_prev_ph_mark").forward_fill().alias("_prev_ph"),
        pl.col("_prev_pl_mark").forward_fill().alias("_prev_pl"),
    )

    higher_high = pl.col("_last_ph") > pl.col("_prev_ph")
    higher_low = pl.col("_last_pl") > pl.col("_prev_pl")
    # Null index ⇒ no pivot of that kind yet; treat as "long ago" (-1) so the
    # comparison still resolves to the kind that has actually confirmed.
    recent_is_high = pl.col("_ph_idx").fill_null(-1) >= pl.col("_pl_idx").fill_null(-1)

    high_label = pl.when(higher_high).then(pl.lit("HH")).otherwise(pl.lit("LH"))
    low_label = pl.when(higher_low).then(pl.lit("HL")).otherwise(pl.lit("LL"))
    structure = (
        pl.when(recent_is_high & pl.col("_prev_ph").is_not_null())
        .then(high_label)
        .when(~recent_is_high & pl.col("_prev_pl").is_not_null())
        .then(low_label)
        .otherwise(None)
    )
    out = out.with_columns(structure.alias("structure"))
    return out.drop(
        [
            "_last_ph",
            "_last_pl",
            "_prev_ph_mark",
            "_prev_pl_mark",
            "_prev_ph",
            "_prev_pl",
            "_ph_idx",
            "_pl_idx",
        ]
    )


__all__: list[str] = ["add_trend"]
