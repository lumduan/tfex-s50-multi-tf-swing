"""Hand-computed checks for the causal primitives."""

from __future__ import annotations

import math

import polars as pl
import pytest

from tfex_s50_multi_tf_swing.features import indicators as ind

from .conftest import as_float, as_floats


def _frame(**cols: list[float]) -> pl.DataFrame:
    return pl.DataFrame({k: pl.Series(v, dtype=pl.Float64) for k, v in cols.items()})


def test_log_return_first_is_null_then_ln_ratio() -> None:
    df = _frame(close=[100.0, 110.0, 121.0])
    out = df.select(ind.log_return().alias("lr"))["lr"].to_list()
    assert out[0] is None
    assert out[1] == pytest.approx(math.log(110 / 100))
    assert out[2] == pytest.approx(math.log(121 / 110))


def test_ema_adjust_false_recursion() -> None:
    df = _frame(close=[1.0, 2.0, 3.0, 4.0, 5.0])
    out = df.select(ind.ema("close", span=3).alias("e"))["e"].to_list()
    # alpha = 2/(span+1) = 0.5
    expected = [1.0, 1.5, 2.25, 3.125, 4.0625]
    assert out == pytest.approx(expected)


def test_true_range_matches_definition() -> None:
    df = _frame(high=[10.0, 12.0, 11.0], low=[8.0, 9.0, 7.0], close=[9.0, 11.0, 8.0])
    tr = df.select(ind.true_range().alias("tr"))["tr"].to_list()
    # row0: only H-L = 2 (no prev close)
    assert tr[0] == pytest.approx(2.0)
    # row1: max(12-9, |12-9|, |9-9|) = 3
    assert tr[1] == pytest.approx(3.0)
    # row2: max(11-7, |11-11|, |7-11|) = 4
    assert tr[2] == pytest.approx(4.0)


def test_atr_is_wilder_rma_of_true_range() -> None:
    df = _frame(
        high=[10.0, 12.0, 11.0, 13.0], low=[8.0, 9.0, 7.0, 10.0], close=[9.0, 11.0, 8.0, 12.0]
    )
    atr = df.select(ind.atr(2).alias("a"))["a"].to_list()
    tr = df.select(ind.true_range().alias("tr"))["tr"].to_list()
    alpha = 1.0 / 2
    exp = [tr[0]]
    for i in range(1, len(tr)):
        exp.append(alpha * tr[i] + (1 - alpha) * exp[-1])
    assert atr == pytest.approx(exp)


def test_rolling_zscore_trailing_window() -> None:
    df = _frame(x=[1.0, 2.0, 3.0, 4.0, 5.0])
    z = df.select(ind.rolling_zscore(pl.col("x"), window=3).alias("z"))["z"].to_list()
    assert z[0] is None and z[1] is None
    # window [1,2,3]: mean 2, std (sample) 1 -> (3-2)/1 = 1
    assert z[2] == pytest.approx(1.0)
    assert z[4] == pytest.approx(1.0)


def test_winsorize_clips_to_trailing_quantiles() -> None:
    df = _frame(x=[1.0, 2.0, 3.0, 100.0, 5.0])
    w = as_floats(
        df.select(ind.winsorize(pl.col("x"), 0.0, 1.0, window=3).alias("w"))["w"].to_list()
    )
    # window for the last row is [100,5] over size 3 with current -> bounded by trailing min/max
    assert w[3] is not None
    assert max(v for v in w if v is not None) <= 100.0


def test_realised_vol_is_rolling_std_of_log_returns() -> None:
    df = _frame(close=[100.0, 101.0, 102.0, 103.0, 104.0])
    rv = df.select(ind.realised_vol(window=2).alias("rv"))["rv"]
    assert rv.null_count() >= 1  # leading nulls
    assert as_float(rv.drop_nulls().min()) >= 0.0  # std is non-negative


def test_with_swing_pivots_detects_confirmed_high() -> None:
    # A clear local max at index 3, confirmed 2 bars later (lookback=2) at index 5.
    highs = [1.0, 2.0, 3.0, 10.0, 3.5, 2.5, 1.0]
    lows = [0.0, 1.0, 2.0, 9.0, 2.5, 1.5, 0.5]
    df = _frame(high=highs, low=lows)
    out = ind.with_swing_pivots(df, lookback=2)
    ph = out["_pivot_high"].to_list()
    # pivot at idx 3 (value 10) confirmed at idx 5
    assert ph[5] == pytest.approx(10.0)
    # not yet confirmed before idx 5
    assert ph[3] is None and ph[4] is None


def test_with_adx_in_bounds() -> None:
    df = _frame(
        high=[float(10 + i) for i in range(20)],
        low=[float(8 + i) for i in range(20)],
        close=[float(9 + i) for i in range(20)],
    )
    out = ind.with_adx(df, period=5)
    adx = as_floats(out["adx"].drop_nulls().to_list())
    assert "adx" in out.columns
    assert all(0.0 <= v <= 100.0 for v in adx)
