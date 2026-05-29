"""§2.2 volatility feature tests."""

from __future__ import annotations

import polars as pl

from tfex_s50_multi_tf_swing.features.models import FeatureConfig
from tfex_s50_multi_tf_swing.features.volatility import add_volatility

from .conftest import as_float, as_floats, ohlcv, working_frame


def test_volatility_columns_present_and_finite(small_config: FeatureConfig) -> None:
    df = ohlcv(n=120, interval_minutes=5)
    out = add_volatility(working_frame(df, small_config), small_config)
    for col in ("atr_ratio", "bollinger_squeeze", "realised_vol_5", "realised_vol_10"):
        assert col in out.columns
    assert as_float(out["atr_ratio"].drop_nulls().min()) > 0
    assert as_float(out["bollinger_squeeze"].drop_nulls().min()) >= 0
    assert as_float(out["realised_vol_5"].drop_nulls().min()) >= 0


def test_atr_ratio_expands_when_range_expands(small_config: FeatureConfig) -> None:
    # Flat then a volatility burst: short ATR should outpace long ATR (ratio rises).
    closes = [800.0] * 40 + [800.0 + (i % 2) * 30.0 for i in range(40)]
    rows = []
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    start = datetime(2026, 1, 5, 2, 45, tzinfo=UTC)
    for i, c in enumerate(closes):
        span = 1.0 if i < 40 else 20.0
        rows.append(
            {
                "time": start + timedelta(minutes=5 * i),
                "open": Decimal(f"{c:.4f}"),
                "high": Decimal(f"{c + span:.4f}"),
                "low": Decimal(f"{c - span:.4f}"),
                "close": Decimal(f"{c:.4f}"),
                "volume": Decimal("1000.0000"),
            }
        )
    df = pl.DataFrame(rows).with_columns(pl.col("time").dt.replace_time_zone("UTC"))
    out = add_volatility(working_frame(df, small_config), small_config)
    ratio = as_floats(out["atr_ratio"].to_list())
    assert ratio[-1] > ratio[39]  # ratio is higher inside the burst than in the calm
