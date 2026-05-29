"""Shared fixtures and synthetic-data builders for feature tests.

Two builders:

* :func:`ohlcv` — a plain continuous 5m/1h/4h OHLCV frame stepping at a fixed
  interval from a UTC start. Good for pure-math primitives and the look-ahead
  regression test.
* :func:`intraday_5m` — a session-aware 5m frame across business days, with bars
  only inside the morning and afternoon TFEX sessions (and the lunch gap
  removed), so time-of-day / structure features have realistic content.

Prices are deterministic so every test is reproducible.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import polars as pl
import pytest

from tfex_s50_multi_tf_swing.features.indicators import atr, with_adx, with_swing_pivots
from tfex_s50_multi_tf_swing.features.models import FeatureConfig
from tfex_s50_multi_tf_swing.features.time_of_day import with_session_columns

# Asia/Bangkok is UTC+7; BKK 09:45 == 02:45 UTC.
_BKK_OFFSET = timedelta(hours=7)


def working_frame(df: pl.DataFrame, config: FeatureConfig) -> pl.DataFrame:
    """Replicate the pipeline's pre-feature-group steps for group-level tests."""
    work = df.sort("time").with_columns(
        pl.col("open").cast(pl.Float64),
        pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64),
        pl.col("close").cast(pl.Float64),
        pl.col("volume").cast(pl.Float64),
    )
    work = with_session_columns(work)
    work = work.with_columns(atr(config.atr_period).alias("_atr"))
    work = with_swing_pivots(work, config.swing_lookback)
    return with_adx(work, config.adx_period)


def _to_decimal(x: float) -> Decimal:
    return Decimal(f"{x:.4f}")


def as_float(x: object) -> float:
    """Cast a Polars scalar (broadly typed) to ``float`` for ordering asserts."""
    return cast(float, x)


def as_floats(values: list[object]) -> list[float]:
    """Cast a Polars ``to_list()`` result to ``list[float]``."""
    return cast(list[float], values)


def ohlcv(
    *, n: int, interval_minutes: int, start: datetime | None = None, base: float = 800.0
) -> pl.DataFrame:
    """Continuous OHLCV frame with a gentle deterministic sine wiggle."""
    start = start or datetime(2026, 1, 5, 2, 45, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    for i in range(n):
        t = start + timedelta(minutes=interval_minutes * i)
        mid = base + 10.0 * math.sin(i / 7.0) + i * 0.02
        rows.append(
            {
                "time": t,
                "open": _to_decimal(mid),
                "high": _to_decimal(mid + 1.5 + (i % 5) * 0.1),
                "low": _to_decimal(mid - 1.5 - (i % 3) * 0.1),
                "close": _to_decimal(mid + 0.4),
                "volume": _to_decimal(1000.0 + (i % 50) * 25.0),
            }
        )
    return pl.DataFrame(rows).with_columns(pl.col("time").dt.replace_time_zone("UTC"))


def intraday_5m(*, days: int = 12, base: float = 800.0) -> pl.DataFrame:
    """Session-aware 5m bars across ``days`` consecutive Mon-onward business days."""
    rows: list[dict[str, object]] = []
    day = datetime(2026, 1, 5)  # a Monday
    emitted_days = 0
    i = 0
    while emitted_days < days:
        if day.weekday() < 5:
            for bkk_minute in _session_minutes():
                bkk_dt = datetime(day.year, day.month, day.day) + timedelta(minutes=bkk_minute)
                t = (bkk_dt - _BKK_OFFSET).replace(tzinfo=UTC)
                mid = base + 8.0 * math.sin(i / 9.0) + i * 0.01
                rows.append(
                    {
                        "time": t,
                        "open": _to_decimal(mid),
                        "high": _to_decimal(mid + 1.2 + (i % 4) * 0.1),
                        "low": _to_decimal(mid - 1.2 - (i % 3) * 0.1),
                        "close": _to_decimal(mid + 0.3),
                        "volume": _to_decimal(1000.0 + (i % 40) * 20.0),
                    }
                )
                i += 1
            emitted_days += 1
        day += timedelta(days=1)
    return pl.DataFrame(rows).with_columns(pl.col("time").dt.replace_time_zone("UTC")).sort("time")


def _session_minutes() -> list[int]:
    """BKK minute-of-day for morning (09:45–12:30) and afternoon (14:30–16:55) 5m bars."""
    minutes: list[int] = []
    minutes.extend(range(9 * 60 + 45, 12 * 60 + 30, 5))
    minutes.extend(range(14 * 60 + 30, 16 * 60 + 55, 5))
    return minutes


@pytest.fixture
def small_config() -> FeatureConfig:
    """Short windows so fixtures stay small and tests run fast."""
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
