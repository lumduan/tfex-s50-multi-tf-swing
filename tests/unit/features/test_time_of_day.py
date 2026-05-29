"""Session tagging (anti-drift vs SessionCalendar) and time-of-day features."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from tfex_s50_multi_tf_swing.data.session import SessionCalendar
from tfex_s50_multi_tf_swing.features.models import FeatureConfig
from tfex_s50_multi_tf_swing.features.time_of_day import add_time_of_day, with_session_columns

from .conftest import intraday_5m


def _sweep_frame() -> pl.DataFrame:
    """Every 15 minutes across five consecutive days (incl. a weekend)."""
    start = datetime(2026, 1, 2, 0, 0, tzinfo=UTC)  # Fri 07:00 BKK
    rows = [{"time": start + timedelta(minutes=15 * i)} for i in range(5 * 96)]
    return pl.DataFrame(rows).with_columns(pl.col("time").dt.replace_time_zone("UTC"))


def test_session_tagging_agrees_with_calendar() -> None:
    cal = SessionCalendar()
    df = _sweep_frame()
    tagged = with_session_columns(df)
    times = tagged["time"].to_list()
    names = tagged["session_name"].to_list()
    phases = tagged["session_phase"].to_list()
    for t, name, phase in zip(times, names, phases, strict=True):
        assert name == cal.session_of(t), f"session_name mismatch at {t}"
        assert phase == cal.time_of_day_bucket(t), f"session_phase mismatch at {t}"


def test_lunch_and_close_auction_flags() -> None:
    df = intraday_5m(days=2)
    cfg = FeatureConfig()
    out = add_time_of_day(with_session_columns(df), cfg, "5m")
    cal = SessionCalendar()
    for t, flag in zip(out["time"].to_list(), out["lunch_zone_flag"].to_list(), strict=True):
        assert bool(flag) == cal.is_lunch_dead_zone(t)
    # close-auction flag only fires inside the last 15m of the afternoon session.
    aff = out.filter(pl.col("close_auction_flag") == 1)
    assert aff.height > 0
    assert set(aff["session_name"].unique().to_list()) == {"afternoon"}


def test_opening_range_exposed_only_after_window_closes(small_config: FeatureConfig) -> None:
    df = intraday_5m(days=3)
    out = add_time_of_day(with_session_columns(df), small_config, "5m")
    assert "or_high_15" in out.columns
    # Before 10:00 BKK (09:45 + 15m) the 15m opening range is still forming -> null.
    early = out.filter(
        (pl.col("session_name") == "morning") & (pl.col("_bkk_minute") < 9 * 60 + 45 + 15)
    )
    assert early["or_high_15"].null_count() == early.height
    # After the window closes it is populated and constant within each session.
    per_day = (
        out.filter(pl.col("or_high_15").is_not_null())
        .group_by("session_date")
        .agg(pl.col("or_high_15").n_unique().alias("u"))
    )
    assert per_day["u"].max() == 1
