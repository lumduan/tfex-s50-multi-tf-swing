"""§2.2 Volatility features.

* ``atr_ratio`` — ``ATR_short / ATR_long`` (>1 expansion, <1 compression).
* ``bollinger_squeeze`` — Bollinger-band width / Keltner-channel width
  (<1 ⇒ squeeze).
* ``realised_vol_{h}`` — rolling realised volatility at each configured horizon.

All inputs are trailing; see
:mod:`tfex_s50_multi_tf_swing.features.indicators` for the primitives.
"""

from __future__ import annotations

import polars as pl

from tfex_s50_multi_tf_swing.features.indicators import (
    atr,
    bollinger_width,
    keltner_width,
    realised_vol,
)
from tfex_s50_multi_tf_swing.features.models import FeatureConfig


def add_volatility(df: pl.DataFrame, config: FeatureConfig) -> pl.DataFrame:
    """Add the §2.2 volatility feature columns."""
    atr_ratio = atr(config.atr_short) / atr(config.atr_long)
    bb = bollinger_width(config.bb_period, config.bb_k)
    kc = keltner_width(config.keltner_period, config.keltner_m)
    squeeze = bb / kc

    exprs: list[pl.Expr] = [
        atr_ratio.alias("atr_ratio"),
        squeeze.alias("bollinger_squeeze"),
    ]
    exprs.extend(
        realised_vol(window=h).alias(f"realised_vol_{h}") for h in config.realised_vol_windows
    )
    return df.with_columns(exprs)


__all__: list[str] = ["add_volatility"]
