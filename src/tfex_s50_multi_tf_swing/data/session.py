"""TFEX trading-session boundaries, Thai holiday calendar, time-of-day buckets.

ROADMAP §1.3 sessions (Asia/Bangkok, UTC+7, no DST):

* Morning   09:45 – 12:30
* Afternoon 14:30 – 16:55
* Night     18:45 – 03:00 (crosses midnight; bars labelled by *start* day)

The lunch dead zone 12:00 – 14:00 BKK is a **no-trade regime**
(``TFEX CLAUDE.md`` hard rule #5). Time-of-day buckets are documented per the
ROADMAP's *pre-open / open / mid-morning / lunch / afternoon / pre-close / night*
classification.

This module is intentionally I/O-free: holiday data is an embedded constant
(small, easy to inspect, easy to revise yearly) and the rest is pure-Python
arithmetic. ``BKK`` is fixed UTC+7 because Thailand does not observe DST.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Final, Literal

from tfex_s50_multi_tf_swing.data.errors import SessionError

BKK: Final[timezone] = timezone(timedelta(hours=7))
"""Asia/Bangkok is a fixed offset of UTC+7. Thailand does not observe DST."""

# Half-open ``[start, end)`` minutes-of-day in BKK. The night session crosses
# midnight, so its ``end`` minute is on the *next* calendar day; we represent
# that as 1620 (= 27:00, i.e. 03:00 next day).
SESSION_BOUNDS_BKK: Final[dict[str, tuple[int, int]]] = {
    "morning": (9 * 60 + 45, 12 * 60 + 30),  # 09:45 – 12:30
    "afternoon": (14 * 60 + 30, 16 * 60 + 55),  # 14:30 – 16:55
    "night": (18 * 60 + 45, 27 * 60 + 0),  # 18:45 – next-day 03:00
}

LUNCH_DEAD_ZONE_BKK: Final[tuple[int, int]] = (12 * 60, 14 * 60)
"""[12:00, 14:00) BKK — explicit no-trade window."""

SessionName = Literal["morning", "lunch", "afternoon", "night", "closed"]
TimeOfDayBucket = Literal[
    "pre-open", "open", "mid-morning", "lunch", "afternoon", "pre-close", "night"
]

# A pragmatic 2024–2026 Thai public-holiday list. Year-end maintenance: refresh
# this from https://www.set.or.th/en/about/calendar/holiday-schedule annually.
# (Holiday accuracy here only matters for expiry resolution and the
# missing-candle validator; the strategy never trades on holidays anyway.)
THAI_HOLIDAYS_2024_2026: Final[frozenset[date]] = frozenset(
    {
        # 2024
        date(2024, 1, 1),  # New Year
        date(2024, 2, 26),  # Makha Bucha (observed)
        date(2024, 4, 8),  # Chakri Memorial Day (observed)
        date(2024, 4, 15),
        date(2024, 4, 16),  # Songkran
        date(2024, 5, 1),  # Labour Day
        date(2024, 5, 6),  # Coronation Day (observed)
        date(2024, 5, 22),  # Visakha Bucha
        date(2024, 6, 3),  # Queen Suthida's Birthday
        date(2024, 7, 22),  # Asanha Bucha (observed)
        date(2024, 7, 29),  # King's Birthday (observed)
        date(2024, 8, 12),  # Queen Mother's Birthday
        date(2024, 10, 14),  # Chulalongkorn Day (observed)
        date(2024, 10, 23),  # Chulalongkorn Day
        date(2024, 12, 5),  # King Bhumibol's Birthday / Father's Day
        date(2024, 12, 10),  # Constitution Day
        date(2024, 12, 31),  # NYE
        # 2025
        date(2025, 1, 1),
        date(2025, 2, 12),  # Makha Bucha
        date(2025, 4, 7),  # Chakri Memorial (observed)
        date(2025, 4, 14),
        date(2025, 4, 15),
        date(2025, 5, 1),
        date(2025, 5, 5),  # Coronation Day (observed)
        date(2025, 5, 12),  # Visakha Bucha (observed)
        date(2025, 6, 2),  # Queen Suthida (observed)
        date(2025, 7, 10),  # Asanha Bucha
        date(2025, 7, 28),  # King's Birthday
        date(2025, 8, 12),  # Queen Mother's
        date(2025, 10, 13),  # Chulalongkorn Day
        date(2025, 12, 5),
        date(2025, 12, 10),
        date(2025, 12, 31),
        # 2026
        date(2026, 1, 1),
        date(2026, 1, 2),  # Substitution day (NYE 2025 → Jan 2)
        date(2026, 3, 2),  # Makha Bucha
        date(2026, 4, 6),  # Chakri Memorial
        date(2026, 4, 13),
        date(2026, 4, 14),
        date(2026, 4, 15),  # Songkran
        date(2026, 5, 1),
        date(2026, 5, 4),  # Coronation Day (observed)
        date(2026, 5, 28),  # Visakha Bucha (observed)
        date(2026, 6, 1),  # Queen Suthida (observed)
        date(2026, 7, 29),  # Asanha Bucha + King's Birthday
        date(2026, 8, 12),
        date(2026, 10, 13),
        date(2026, 12, 7),  # King Bhumibol (observed)
        date(2026, 12, 10),
        date(2026, 12, 31),
    }
)


class SessionCalendar:
    """Pure-Python TFEX trading-session calendar.

    All public methods accept tz-aware ``datetime`` instances. Inputs are
    normalised to ``Asia/Bangkok`` internally; callers may pass UTC or any
    other tz-aware datetime — naive datetimes raise.

    The calendar exposes:

    * Holiday / weekend / business-day classification (used by
      :func:`tfex_s50_multi_tf_swing.data.contracts.expiry_for`).
    * Session-name lookup (``morning`` / ``lunch`` / ``afternoon`` / ``night`` /
      ``closed``).
    * Time-of-day bucket classification per the ROADMAP labels.
    * Lunch dead-zone gate.
    * Expiry-week and rollover-week flags driven by a configurable
      ``roll_offset_days``.
    """

    def __init__(
        self,
        *,
        holidays: frozenset[date] = THAI_HOLIDAYS_2024_2026,
        roll_offset_days: int = 5,
    ) -> None:
        if roll_offset_days < 0:
            raise ValueError(f"roll_offset_days must be ≥ 0, got {roll_offset_days}")
        self._holidays: frozenset[date] = holidays
        self._roll_offset_days: int = roll_offset_days

    # ------------------------------------------------------------------
    # Business-day classification
    # ------------------------------------------------------------------

    def is_holiday(self, d: date) -> bool:
        """Return ``True`` if ``d`` is a Thai market holiday."""
        return d in self._holidays

    def is_business_day(self, d: date) -> bool:
        """``True`` for Mon–Fri that is not in the holiday list."""
        return d.weekday() < 5 and d not in self._holidays

    # ------------------------------------------------------------------
    # Session classification
    # ------------------------------------------------------------------

    def session_of(self, dt: datetime) -> SessionName:
        """Return the named session containing ``dt`` (BKK-converted).

        Names: ``morning`` / ``afternoon`` / ``night`` are open trading
        sessions; ``lunch`` is the closed gap between morning end and
        afternoon start (12:30–14:30 BKK); ``closed`` is everything else
        (overnight gap, pre-open, and any non-business day).
        """
        bkk_dt = _to_bkk(dt)
        if not self.is_business_day(bkk_dt.date()):
            return "closed"
        minute_of_day: int = bkk_dt.hour * 60 + bkk_dt.minute
        morn_start, morn_end = SESSION_BOUNDS_BKK["morning"]
        aft_start, aft_end = SESSION_BOUNDS_BKK["afternoon"]
        night_start, night_end_mins = SESSION_BOUNDS_BKK["night"]
        # Night-session post-midnight tail (00:00..03:00) must be checked first.
        if minute_of_day < (night_end_mins - 24 * 60):
            return "night"
        if morn_start <= minute_of_day < morn_end:
            return "morning"
        if morn_end <= minute_of_day < aft_start:
            return "lunch"
        if aft_start <= minute_of_day < aft_end:
            return "afternoon"
        if minute_of_day >= night_start:
            return "night"
        return "closed"

    def is_lunch_dead_zone(self, dt: datetime) -> bool:
        """``True`` iff ``dt`` falls in the 12:00–14:00 BKK no-trade overlay.

        This is independent of :meth:`session_of` — at 12:00–12:30 the morning
        session is still open but the strategy must not trade (TFEX
        ``CLAUDE.md`` hard rule #5).
        """
        bkk_dt = _to_bkk(dt)
        minute_of_day: int = bkk_dt.hour * 60 + bkk_dt.minute
        return LUNCH_DEAD_ZONE_BKK[0] <= minute_of_day < LUNCH_DEAD_ZONE_BKK[1]

    def time_of_day_bucket(self, dt: datetime) -> TimeOfDayBucket:
        """Classify a bar's BKK time into one of the ROADMAP buckets.

        Buckets:

        * ``pre-open`` — before the morning session
        * ``open`` — first 30 minutes of the morning session
        * ``mid-morning`` — rest of the morning session
        * ``lunch`` — 12:00 BKK to start of afternoon session
        * ``afternoon`` — afternoon session
        * ``pre-close`` — final 15 minutes of the afternoon session
        * ``night`` — night session window
        """
        bkk_dt = _to_bkk(dt)
        m: int = bkk_dt.hour * 60 + bkk_dt.minute
        morn_start, morn_end = SESSION_BOUNDS_BKK["morning"]
        aft_start, aft_end = SESSION_BOUNDS_BKK["afternoon"]
        night_start, night_end_mins = SESSION_BOUNDS_BKK["night"]
        # Night session crosses midnight, so the post-midnight tail must be
        # checked BEFORE the "before morning" pre-open branch.
        if m < (night_end_mins - 24 * 60):
            return "night"
        if m < morn_start:
            return "pre-open"
        if morn_start <= m < morn_start + 30:
            return "open"
        if morn_start + 30 <= m < morn_end:
            return "mid-morning"
        if morn_end <= m < aft_start:
            return "lunch"
        if aft_start <= m < aft_end - 15:
            return "afternoon"
        if aft_end - 15 <= m < aft_end:
            return "pre-close"
        if m >= night_start:
            return "night"
        return "pre-open"

    # ------------------------------------------------------------------
    # Expiry / rollover flags
    # ------------------------------------------------------------------

    def is_expiry_week(self, d: date, *, expiry: date) -> bool:
        """``True`` iff ``d`` and ``expiry`` are in the same ISO calendar week."""
        return d.isocalendar()[:2] == expiry.isocalendar()[:2]

    def is_rollover_week(self, d: date, *, expiry: date) -> bool:
        """``True`` iff ``d`` lies within the configured roll window before expiry.

        The roll window is ``[expiry - roll_offset_days, expiry]`` (inclusive on
        both ends — the strategy's continuous-contract roll completes by
        ``expiry``).
        """
        if d > expiry:
            return False
        delta_days: int = (expiry - d).days
        return 0 <= delta_days <= self._roll_offset_days


def _to_bkk(dt: datetime) -> datetime:
    """Convert a tz-aware datetime to Asia/Bangkok; reject naive datetimes."""
    if dt.tzinfo is None:
        raise SessionError("datetime must be timezone-aware")
    return dt.astimezone(BKK)


__all__: list[str] = [
    "BKK",
    "LUNCH_DEAD_ZONE_BKK",
    "SESSION_BOUNDS_BKK",
    "SessionCalendar",
    "SessionName",
    "THAI_HOLIDAYS_2024_2026",
    "TimeOfDayBucket",
]
