"""§2.5 regime feature tests."""

from __future__ import annotations

import math

import polars as pl

from tfex_s50_multi_tf_swing.features.models import FeatureConfig
from tfex_s50_multi_tf_swing.features.regime import add_regime, window_percentile
from tfex_s50_multi_tf_swing.features.volatility import add_volatility

from .conftest import as_floats, ohlcv, working_frame


def test_window_percentile_known_values() -> None:
    # current (last) is the max of the window -> rank 1.0
    assert window_percentile(pl.Series([1.0, 2.0, 3.0])) == 1.0
    # current is the median -> 2 of 3 values are <= it
    assert window_percentile(pl.Series([1.0, 3.0, 2.0])) == 2.0 / 3.0
    # null current -> nan
    assert math.isnan(window_percentile(pl.Series([1.0, None], dtype=pl.Float64)))
    # all-null window -> nan
    assert math.isnan(window_percentile(pl.Series([None, None], dtype=pl.Float64)))


def test_regime_columns_in_bounds(small_config: FeatureConfig) -> None:
    df = ohlcv(n=120, interval_minutes=5)
    work = add_volatility(working_frame(df, small_config), small_config)
    out = add_regime(work, small_config)
    for col in ("rv_percentile", "trend_persistence", "range_compression", "volume_expansion"):
        assert col in out.columns

    rvp = as_floats(out["rv_percentile"].drop_nulls().to_list())
    assert all(0.0 <= v <= 1.0 for v in rvp)

    tp = as_floats(out["trend_persistence"].drop_nulls().to_list())
    assert all(-1.0 <= v <= 1.0 for v in tp)

    assert set(out["range_compression"].unique().to_list()) <= {0, 1}


def test_trend_persistence_positive_on_uptrend(small_config: FeatureConfig) -> None:
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    import polars as pl

    start = datetime(2026, 1, 5, 2, 45, tzinfo=UTC)
    rows = [
        {
            "time": start + timedelta(minutes=5 * i),
            "open": Decimal(f"{800 + i:.4f}"),
            "high": Decimal(f"{800 + i + 1:.4f}"),
            "low": Decimal(f"{800 + i - 1:.4f}"),
            "close": Decimal(f"{800 + i:.4f}"),
            "volume": Decimal("1000.0000"),
        }
        for i in range(40)
    ]
    df = pl.DataFrame(rows).with_columns(pl.col("time").dt.replace_time_zone("UTC"))
    work = add_volatility(working_frame(df, small_config), small_config)
    out = add_regime(work, small_config)
    # Every return is positive -> sign agreement == +1.
    assert out["trend_persistence"].drop_nulls().to_list()[-1] == 1.0
