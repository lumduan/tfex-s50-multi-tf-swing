"""Tests for :func:`build_signal_inputs` — the aligned 1H substrate.

Covers the column contract, the look-ahead-free alignment (no 1D value leaks onto an
earlier 1H bar), and the path when the 1D frame is absent: ``1d_bias_direction`` defaults
to ``"neutral"`` so A / B emit no signals.

Updated for the 1H-execution migration (2026-06-05): the required frames are ``1h`` + ``1d``.
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.unit.features.conftest import ohlcv
from tfex_s50_multi_tf_swing.data.models import Timeframe
from tfex_s50_multi_tf_swing.features.models import FeatureConfig
from tfex_s50_multi_tf_swing.signals.errors import SignalInputError
from tfex_s50_multi_tf_swing.signals.inputs import COL_BIAS, COL_REGIME, build_signal_inputs

_SMALL = FeatureConfig(
    ema_spans=(5, 10),
    swing_lookback=2,
    atr_period=5,
    atr_short=5,
    atr_long=10,
    bb_period=10,
    keltner_period=10,
    realised_vol_windows=(5, 10),
    opening_range_minutes=(15, 30, 60),
    initial_balance_minutes=30,
    liquidity_lookback=10,
    adx_period=5,
    rv_percentile_window=20,
    trend_persistence_window=10,
    volume_zscore_window=10,
    zscore_window=20,
)


def _frames(*, with_1d: bool = True) -> dict[Timeframe, pl.DataFrame]:
    frames: dict[Timeframe, pl.DataFrame] = {
        "1h": ohlcv(n=120, interval_minutes=60),
    }
    if with_1d:
        frames["1d"] = ohlcv(n=40, interval_minutes=1440)
    return frames


def test_columns_present_with_1d() -> None:
    out = build_signal_inputs(_frames(with_1d=True), feature_config=_SMALL)
    for col in (
        COL_BIAS,  # "1d_bias_direction"
        COL_REGIME,  # "1d_regime"
        "close",
        "swing_high",
        "swing_low",
        "atr_ratio",
        "or_high_60",
    ):
        assert col in out.columns


def test_alignment_is_causal_no_leak() -> None:
    # The first 1H bar predates the first 1D close, so the 1D regime is null on the first bar.
    out = build_signal_inputs(_frames(with_1d=True), feature_config=_SMALL).sort("time")
    assert out.get_column(COL_REGIME).to_list()[0] is None
    assert out.get_column(COL_REGIME).null_count() < out.height  # later rows do resolve


def test_missing_1d_raises() -> None:
    # In the 1H-execution migration, 1d is a required frame — it carries both regime and bias.
    with pytest.raises(SignalInputError, match="'1d'"):
        build_signal_inputs(_frames(with_1d=False), feature_config=_SMALL)


def test_requires_1h_and_1d() -> None:
    with pytest.raises(SignalInputError, match="'1h'"):
        build_signal_inputs({"1d": ohlcv(n=40, interval_minutes=1440)}, feature_config=_SMALL)
    with pytest.raises(SignalInputError, match="'1d'"):
        build_signal_inputs({"1h": ohlcv(n=120, interval_minutes=60)}, feature_config=_SMALL)
