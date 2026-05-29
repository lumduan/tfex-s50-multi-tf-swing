"""§2.5 Regime features.

* ``rv_percentile`` — trailing percentile rank of realised volatility.
* ``trend_persistence`` — rolling mean of the sign of returns (∈ [-1, 1]).
* ``range_compression`` — low ``atr_ratio`` **and** low ADX flag.
* ``volume_expansion`` — trailing z-score of volume.

Expects ``atr_ratio`` and ``adx`` columns to be present already (added by the
volatility group and the pipeline's ADX pass). ``rv_percentile`` is computed
with a trailing :func:`polars.Expr.rolling_map`; on long 5m series this is the
most expensive feature — it is the one obvious bottleneck and is documented as
such in the plan.
"""

from __future__ import annotations

import polars as pl

from tfex_s50_multi_tf_swing.features.indicators import log_return, realised_vol, rolling_zscore
from tfex_s50_multi_tf_swing.features.models import FeatureConfig


def add_regime(df: pl.DataFrame, config: FeatureConfig) -> pl.DataFrame:
    """Add the §2.5 regime feature columns."""
    base_rv_window = config.realised_vol_windows[0]
    lr = log_return()
    sign = (lr > 0).cast(pl.Float64) - (lr < 0).cast(pl.Float64)

    out = df.with_columns(realised_vol(window=base_rv_window).alias("_rv_base"))
    out = out.with_columns(
        _trailing_percentile("_rv_base", config.rv_percentile_window).alias("rv_percentile"),
        sign.rolling_mean(window_size=config.trend_persistence_window).alias("trend_persistence"),
        (
            (pl.col("atr_ratio") < config.range_compression_atr_ratio_threshold)
            & (pl.col("adx") < config.range_compression_adx_threshold)
        )
        .cast(pl.Int8)
        .alias("range_compression"),
        rolling_zscore(pl.col("volume"), config.volume_zscore_window).alias("volume_expansion"),
    )
    return out.drop("_rv_base")


def window_percentile(s: pl.Series) -> float:
    """Fraction of a trailing window (incl. current) ≤ the current value.

    Extracted to module scope so it is unit-testable directly: Polars may run a
    ``rolling_map`` callback on a worker thread where line-coverage tracing does
    not follow it.
    """
    last = s[-1]
    if last is None:
        return float("nan")
    # ``last`` is non-null ⇒ the window has at least one valid value.
    valid = s.drop_nulls()
    return float((valid <= last).sum()) / float(valid.len())


def _trailing_percentile(col: str, window: int) -> pl.Expr:
    """Fraction of the trailing ``window`` (incl. current) ≤ the current value."""
    return pl.col(col).rolling_map(window_percentile, window_size=window)


__all__: list[str] = ["add_regime", "window_percentile"]
