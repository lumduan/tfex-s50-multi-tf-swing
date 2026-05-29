"""Unit tests for :mod:`tfex_s50_multi_tf_swing.data.session`."""

from __future__ import annotations

from datetime import UTC, date, datetime, timezone

import pytest

from tfex_s50_multi_tf_swing.data.errors import SessionError
from tfex_s50_multi_tf_swing.data.session import (
    BKK,
    SessionCalendar,
)


@pytest.fixture
def cal() -> SessionCalendar:
    return SessionCalendar()


def _bkk(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=BKK)


# ---------------------------------------------------------------------------
# Holidays / business days
# ---------------------------------------------------------------------------


def test_is_business_day_weekend(cal: SessionCalendar) -> None:
    assert not cal.is_business_day(date(2026, 5, 30))  # Saturday
    assert not cal.is_business_day(date(2026, 5, 31))  # Sunday


def test_is_business_day_holiday(cal: SessionCalendar) -> None:
    assert not cal.is_business_day(date(2026, 1, 1))  # NYE 2026
    assert cal.is_holiday(date(2026, 1, 1))


def test_is_business_day_normal(cal: SessionCalendar) -> None:
    assert cal.is_business_day(date(2026, 5, 27))  # Thursday, non-holiday


# ---------------------------------------------------------------------------
# Session boundaries — every minute that matters
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (9, 44, "closed"),  # 1 minute before open
        (9, 45, "morning"),  # exactly at open
        (12, 29, "morning"),  # 1 minute before close
        (12, 30, "lunch"),  # exactly at close
        (13, 30, "lunch"),
        (14, 29, "lunch"),  # 1 minute before afternoon
        (14, 30, "afternoon"),
        (16, 54, "afternoon"),
        (16, 55, "closed"),  # exactly at afternoon close
        (18, 44, "closed"),
        (18, 45, "night"),
        (23, 59, "night"),
        (0, 0, "night"),  # crosses midnight
        (2, 59, "night"),  # last minute of night
        (3, 0, "closed"),  # exactly at night close
    ],
)
def test_session_of_minute_boundaries(
    cal: SessionCalendar, hour: int, minute: int, expected: str
) -> None:
    dt = _bkk(2026, 5, 27, hour, minute)
    assert cal.session_of(dt) == expected


def test_session_of_holiday_returns_closed(cal: SessionCalendar) -> None:
    # Even at 10:00 BKK on a holiday, market is closed.
    dt = _bkk(2026, 1, 1, 10, 0)
    assert cal.session_of(dt) == "closed"


def test_session_of_accepts_utc(cal: SessionCalendar) -> None:
    # 02:45 UTC == 09:45 BKK == morning open.
    dt = datetime(2026, 5, 27, 2, 45, tzinfo=UTC)
    assert cal.session_of(dt) == "morning"


def test_session_of_rejects_naive_dt(cal: SessionCalendar) -> None:
    with pytest.raises(SessionError):
        cal.session_of(datetime(2026, 5, 27, 10, 0))


def test_session_of_accepts_arbitrary_tz(cal: SessionCalendar) -> None:
    # New York at 22:45 EDT (UTC-4) = 09:45 BKK next day. Use May 26 NY so the
    # BKK landing date (May 27) is a non-holiday business day.
    ny = timezone(__import__("datetime").timedelta(hours=-4))
    dt = datetime(2026, 5, 26, 22, 45, tzinfo=ny)
    assert cal.session_of(dt) == "morning"


# ---------------------------------------------------------------------------
# Lunch dead-zone
# ---------------------------------------------------------------------------


def test_lunch_dead_zone(cal: SessionCalendar) -> None:
    assert cal.is_lunch_dead_zone(_bkk(2026, 5, 27, 12, 0))
    assert cal.is_lunch_dead_zone(_bkk(2026, 5, 27, 13, 59))
    assert not cal.is_lunch_dead_zone(_bkk(2026, 5, 27, 11, 59))
    assert not cal.is_lunch_dead_zone(_bkk(2026, 5, 27, 14, 0))


# ---------------------------------------------------------------------------
# Time-of-day buckets
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (8, 0, "pre-open"),
        (9, 45, "open"),
        (10, 14, "open"),  # 29 min in
        (10, 15, "mid-morning"),  # 30 min in
        (12, 29, "mid-morning"),
        (12, 30, "lunch"),
        (14, 29, "lunch"),
        (14, 30, "afternoon"),
        (16, 39, "afternoon"),  # 15 min before close
        (16, 40, "pre-close"),
        (16, 54, "pre-close"),
        (18, 45, "night"),
        (1, 0, "night"),  # crosses midnight
    ],
)
def test_time_of_day_bucket(cal: SessionCalendar, hour: int, minute: int, expected: str) -> None:
    dt = _bkk(2026, 5, 27, hour, minute)
    assert cal.time_of_day_bucket(dt) == expected


# ---------------------------------------------------------------------------
# Expiry / rollover flags
# ---------------------------------------------------------------------------


def test_is_expiry_week() -> None:
    cal = SessionCalendar(roll_offset_days=0)
    expiry = date(2026, 6, 30)  # Tue
    # Expiry ISO week is 2026-W27 (Mon 29 Jun – Sun 5 Jul).
    assert cal.is_expiry_week(date(2026, 6, 29), expiry=expiry)
    assert cal.is_expiry_week(date(2026, 7, 5), expiry=expiry)  # same ISO week
    assert cal.is_expiry_week(date(2026, 7, 6), expiry=expiry) is False
    assert cal.is_expiry_week(date(2026, 6, 28), expiry=expiry) is False


def test_is_rollover_week_default_5d() -> None:
    cal = SessionCalendar(roll_offset_days=5)
    expiry = date(2026, 6, 30)
    assert cal.is_rollover_week(date(2026, 6, 25), expiry=expiry)  # exactly 5 days
    assert cal.is_rollover_week(date(2026, 6, 30), expiry=expiry)  # expiry itself
    assert cal.is_rollover_week(date(2026, 6, 24), expiry=expiry) is False  # 6 days
    assert cal.is_rollover_week(date(2026, 7, 1), expiry=expiry) is False  # post-expiry


def test_constructor_rejects_negative_offset() -> None:
    with pytest.raises(ValueError):
        SessionCalendar(roll_offset_days=-1)
