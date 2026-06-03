"""Tests for :func:`build_signal_inputs` — the aligned 5m substrate.

Covers the column contract, the look-ahead-free alignment (no HTF value leaks onto an earlier
5m bar), and the engine-vs-mirror ``4h`` paths: when the 4H frame is absent (the ``engine``
source declines ``4h``), ``4h_bias_direction`` defaults to ``"neutral"`` so A / B emit no signals
while C — gated on the 1H regime — can still run.
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
    opening_range_minutes=(15, 30),
    initial_balance_minutes=30,
    liquidity_lookback=10,
    adx_period=5,
    rv_percentile_window=20,
    trend_persistence_window=10,
    volume_zscore_window=10,
    zscore_window=20,
)


def _frames(*, with_4h: bool) -> dict[Timeframe, pl.DataFrame]:
    frames: dict[Timeframe, pl.DataFrame] = {
        "5m": ohlcv(n=120, interval_minutes=5),
        "1h": ohlcv(n=60, interval_minutes=60),
    }
    if with_4h:
        frames["4h"] = ohlcv(n=40, interval_minutes=240)
    return frames


def test_columns_present_with_4h() -> None:
    out = build_signal_inputs(_frames(with_4h=True), feature_config=_SMALL)
    for col in (
        COL_BIAS,
        COL_REGIME,
        "close",
        "swing_high",
        "swing_low",
        "atr_ratio",
        "or_high_15",
    ):
        assert col in out.columns


def test_alignment_is_causal_no_leak() -> None:
    # The first 5m bar (02:45) predates the first 1H close (03:45), so the 1H regime is unknown.
    out = build_signal_inputs(_frames(with_4h=True), feature_config=_SMALL).sort("time")
    assert out.get_column(COL_REGIME).to_list()[0] is None
    assert out.get_column(COL_REGIME).null_count() < out.height  # later rows do resolve


def test_missing_4h_defaults_bias_neutral() -> None:
    out = build_signal_inputs(_frames(with_4h=False), feature_config=_SMALL)
    assert set(out.get_column(COL_BIAS).to_list()) == {"neutral"}


def test_requires_5m_and_1h() -> None:
    with pytest.raises(SignalInputError, match="'5m'"):
        build_signal_inputs({"1h": ohlcv(n=60, interval_minutes=60)}, feature_config=_SMALL)
    with pytest.raises(SignalInputError, match="'1h'"):
        build_signal_inputs({"5m": ohlcv(n=120, interval_minutes=5)}, feature_config=_SMALL)
