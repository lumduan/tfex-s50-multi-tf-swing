"""Shared fixtures and builders for regime tests.

Two flavours of input:

* :func:`inputs_frame` — a hand-built frame carrying exactly the columns
  :func:`tfex_s50_multi_tf_swing.regime.rules.classify_frame` reads, so each rule
  branch can be exercised deterministically without the feature pipeline.
* :func:`rising_ohlcv` — a continuous OHLCV frame for the end-to-end
  :func:`build_regime_inputs` bridge test.

All prices are deterministic so every test is reproducible.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import polars as pl
import pytest

from tfex_s50_multi_tf_swing.features.models import FeatureConfig

# A single fully-specified "trend_up" row; tests override individual keys.
_TREND_UP_ROW: dict[str, object] = {
    "ema_fast_minus_slow": 2.0,
    "ema_slope_fast": 1.0,
    "structure": "HH",
    "dist_from_vwap": 1.5,
    "rv_percentile": 0.50,
    "trend_persistence": 0.6,
    "volume_expansion": 0.0,
    "range_compression": 0,
}


def inputs_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    """Build a regime-input frame from explicit per-row column values."""
    return pl.DataFrame(rows)


def row(**overrides: object) -> dict[str, object]:
    """Return a trend_up baseline row with ``overrides`` applied."""
    merged = dict(_TREND_UP_ROW)
    merged.update(overrides)
    return merged


def neutral(**overrides: object) -> dict[str, object]:
    """Return a row with all trend signals off (no trend_up / trend_down)."""
    return row(
        ema_fast_minus_slow=0.0,
        ema_slope_fast=0.0,
        structure=None,
        dist_from_vwap=0.0,
        trend_persistence=0.0,
        **overrides,
    )


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
