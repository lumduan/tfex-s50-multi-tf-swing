"""Shared fixtures and builders for bias tests.

Two flavours of input:

* :func:`inputs_frame` — a hand-built frame carrying exactly the columns
  :func:`tfex_s50_multi_tf_swing.bias.htf.classify_frame` reads, so each gate / composition
  branch can be exercised deterministically without the feature pipeline (``structure`` is
  frequently null on sparse synthetic pivots, so we never rely on the pipeline emitting a
  specific label).
* :func:`rising_ohlcv` — a continuous 4h OHLCV frame for the end-to-end
  :func:`tfex_s50_multi_tf_swing.bias.htf.build_bias_inputs` bridge test.

All values are deterministic so every test is reproducible.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import polars as pl
import pytest

from tfex_s50_multi_tf_swing.bias.models import BiasFeatures
from tfex_s50_multi_tf_swing.features.models import FeatureConfig

# A single fully-specified "long" bias-input row; tests override individual keys.
_LONG_ROW: dict[str, object] = {
    "ema_fast_minus_slow": 2.0,
    "ema_slope_fast": 1.0,
    "structure": "HH",
    "dist_from_vwap": 1.5,
    "regime": "trend_up",
}

# The exact mirror — every gate votes short.
_SHORT_ROW: dict[str, object] = {
    "ema_fast_minus_slow": -2.0,
    "ema_slope_fast": -1.0,
    "structure": "LL",
    "dist_from_vwap": -1.5,
    "regime": "trend_down",
}


def long_row(**overrides: object) -> dict[str, object]:
    """Return a clean long-bias row with ``overrides`` applied."""
    merged = dict(_LONG_ROW)
    merged.update(overrides)
    return merged


def short_row(**overrides: object) -> dict[str, object]:
    """Return a clean short-bias row with ``overrides`` applied."""
    merged = dict(_SHORT_ROW)
    merged.update(overrides)
    return merged


def inputs_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    """Build a bias-input frame from explicit per-row column values."""
    return pl.DataFrame(rows)


def make_features(**overrides: object) -> BiasFeatures:
    """Build a :class:`BiasFeatures` from the long baseline with ``overrides`` applied."""
    return BiasFeatures(**long_row(**overrides))  # type: ignore[arg-type]


def rising_ohlcv(*, n: int = 80, base: float = 800.0) -> pl.DataFrame:
    """Continuous 4h OHLCV frame trending gently upward (UTC, Decimal prices)."""
    start = datetime(2026, 1, 5, 2, 45, tzinfo=UTC)
    out: list[dict[str, object]] = []
    for i in range(n):
        t = start + timedelta(hours=4 * i)
        mid = base + i * 0.8 + 3.0 * math.sin(i / 11.0)
        out.append(
            {
                "time": t,
                "open": Decimal(f"{mid:.4f}"),
                "high": Decimal(f"{mid + 1.5:.4f}"),
                "low": Decimal(f"{mid - 1.5:.4f}"),
                "close": Decimal(f"{mid + 0.6:.4f}"),
                "volume": Decimal(f"{1000.0 + (i % 7) * 15.0:.4f}"),
            }
        )
    return pl.DataFrame(out).with_columns(pl.col("time").dt.replace_time_zone("UTC"))


@pytest.fixture
def small_config() -> FeatureConfig:
    """Short windows so the OHLCV fixture stays small (max_lookback == 20)."""
    return FeatureConfig(
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
