"""Time-of-day features and the vectorised session-tagging backbone.

:func:`with_session_columns` mirrors the per-row logic in
:class:`tfex_s50_multi_tf_swing.data.session.SessionCalendar` as Polars
expressions so the whole panel can be tagged in one vectorised pass. It imports
the session *constants* from that module (single source of truth) and a test
asserts the vectorised classification agrees with ``SessionCalendar`` row-by-row
to guard against drift.

Columns added by :func:`with_session_columns`:

* ``_bkk_minute`` — minute-of-day in Asia/Bangkok (0–1439).
* ``session_name`` — ``morning`` / ``lunch`` / ``afternoon`` / ``night`` / ``closed``.
* ``session_phase`` — time-of-day bucket (ROADMAP labels).
* ``session_date`` — the *trading* date; the night tail (00:00–03:00 BKK) maps
  to the previous calendar day so a whole trading day shares one key.

All of these are deterministic functions of the bar timestamp — no look-ahead.
"""

from __future__ import annotations

import polars as pl

from tfex_s50_multi_tf_swing.data.models import Timeframe
from tfex_s50_multi_tf_swing.data.session import (
    LUNCH_DEAD_ZONE_BKK,
    SESSION_BOUNDS_BKK,
    THAI_HOLIDAYS_2024_2026,
)
from tfex_s50_multi_tf_swing.features.models import INTRADAY_TIMEFRAMES, FeatureConfig

_MORN_START, _MORN_END = SESSION_BOUNDS_BKK["morning"]
_AFT_START, _AFT_END = SESSION_BOUNDS_BKK["afternoon"]
_NIGHT_START, _NIGHT_END = SESSION_BOUNDS_BKK["night"]
_NIGHT_TAIL: int = _NIGHT_END - 24 * 60  # post-midnight tail end (180 == 03:00)
_LUNCH_START, _LUNCH_END = LUNCH_DEAD_ZONE_BKK


def with_session_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Append the vectorised session columns described in the module docstring.

    ``df`` must carry a tz-aware UTC ``time`` column. The frame is returned with
    the extra columns; row order is preserved.
    """
    bkk = pl.col("time").dt.convert_time_zone("Asia/Bangkok")
    # dt.hour()/dt.minute() are Int8; widen before arithmetic or 9*60 overflows.
    minute = (bkk.dt.hour().cast(pl.Int32) * 60 + bkk.dt.minute().cast(pl.Int32)).alias(
        "_bkk_minute"
    )
    out = df.with_columns(minute, bkk.dt.date().alias("_bkk_date"))

    # Trading date: night tail (00:00–03:00 BKK) belongs to the prior day's session.
    out = out.with_columns(
        pl.when(pl.col("_bkk_minute") < _NIGHT_TAIL)
        .then(pl.col("_bkk_date") - pl.duration(days=1))
        .otherwise(pl.col("_bkk_date"))
        .alias("session_date")
    )

    holidays = sorted(THAI_HOLIDAYS_2024_2026)
    is_business = (pl.col("_bkk_date").dt.weekday() <= 5) & ~pl.col("_bkk_date").is_in(holidays)

    out = out.with_columns(
        _session_name_expr(is_business).alias("session_name"),
        _session_phase_expr().alias("session_phase"),
    )
    return out


def _session_name_expr(is_business: pl.Expr) -> pl.Expr:
    """Mirror of ``SessionCalendar.session_of`` (business-day aware)."""
    m = pl.col("_bkk_minute")
    return (
        pl.when(~is_business)
        .then(pl.lit("closed"))
        .when(m < _NIGHT_TAIL)
        .then(pl.lit("night"))
        .when((m >= _MORN_START) & (m < _MORN_END))
        .then(pl.lit("morning"))
        .when((m >= _MORN_END) & (m < _AFT_START))
        .then(pl.lit("lunch"))
        .when((m >= _AFT_START) & (m < _AFT_END))
        .then(pl.lit("afternoon"))
        .when(m >= _NIGHT_START)
        .then(pl.lit("night"))
        .otherwise(pl.lit("closed"))
    )


def _session_phase_expr() -> pl.Expr:
    """Mirror of ``SessionCalendar.time_of_day_bucket`` (purely time-based)."""
    m = pl.col("_bkk_minute")
    return (
        pl.when(m < _NIGHT_TAIL)
        .then(pl.lit("night"))
        .when(m < _MORN_START)
        .then(pl.lit("pre-open"))
        .when((m >= _MORN_START) & (m < _MORN_START + 30))
        .then(pl.lit("open"))
        .when((m >= _MORN_START + 30) & (m < _MORN_END))
        .then(pl.lit("mid-morning"))
        .when((m >= _MORN_END) & (m < _AFT_START))
        .then(pl.lit("lunch"))
        .when((m >= _AFT_START) & (m < _AFT_END - 15))
        .then(pl.lit("afternoon"))
        .when((m >= _AFT_END - 15) & (m < _AFT_END))
        .then(pl.lit("pre-close"))
        .when(m >= _NIGHT_START)
        .then(pl.lit("night"))
        .otherwise(pl.lit("pre-open"))
    )


def add_time_of_day(df: pl.DataFrame, config: FeatureConfig, timeframe: Timeframe) -> pl.DataFrame:
    """Add §2.3 time-of-day features. Expects session columns already present."""
    m = pl.col("_bkk_minute")
    cam = config.close_auction_minutes
    out = df.with_columns(
        ((m >= _LUNCH_START) & (m < _LUNCH_END)).cast(pl.Int8).alias("lunch_zone_flag"),
        ((m >= _AFT_END - cam) & (m < _AFT_END)).cast(pl.Int8).alias("close_auction_flag"),
    )

    if timeframe in INTRADAY_TIMEFRAMES:
        out = _add_opening_range(out, config)
    return out


def _add_opening_range(df: pl.DataFrame, config: FeatureConfig) -> pl.DataFrame:
    """Opening-range high/low for the morning session, exposed only after the window closes.

    The window max/min is computed over the session via ``.over("session_date")``
    but is set to ``null`` until ``_bkk_minute`` has passed the window end — so
    the value is never visible before every window bar has closed (causal).
    """
    m = pl.col("_bkk_minute")
    is_morning = pl.col("session_name") == "morning"
    exprs: list[pl.Expr] = []
    for w in config.opening_range_minutes:
        in_window = is_morning & (m >= _MORN_START) & (m < _MORN_START + w)
        hi = pl.when(in_window).then(pl.col("high")).otherwise(None).max().over("session_date")
        lo = pl.when(in_window).then(pl.col("low")).otherwise(None).min().over("session_date")
        window_closed = m >= _MORN_START + w
        exprs.append(
            pl.when(window_closed).then(hi).otherwise(None).cast(pl.Float64).alias(f"or_high_{w}")
        )
        exprs.append(
            pl.when(window_closed).then(lo).otherwise(None).cast(pl.Float64).alias(f"or_low_{w}")
        )
    return df.with_columns(exprs)


__all__: list[str] = ["add_time_of_day", "with_session_columns"]
