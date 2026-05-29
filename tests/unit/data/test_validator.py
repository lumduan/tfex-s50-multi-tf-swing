"""Unit tests for :class:`tfex_s50_multi_tf_swing.data.validator.Validator`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import polars as pl
import pytest

from tfex_s50_multi_tf_swing.data.errors import ValidationError
from tfex_s50_multi_tf_swing.data.session import BKK, SessionCalendar
from tfex_s50_multi_tf_swing.data.validator import (
    DEFAULT_CROSS_CHECK_TOLERANCE,
    Validator,
)

_BUSINESS_DAY = datetime(2026, 5, 27, tzinfo=BKK)
_AS_OF = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)


def _build_morning_5m_frame(*, drop_middle: int = 0, dupes: int = 0) -> pl.DataFrame:
    """Build a synthetic 5m frame covering the morning session 09:45–12:30 BKK.

    ``drop_middle`` removes that many bars from near the middle of the frame
    (preserving day_min / day_max) — used to simulate a true gap.
    """
    # 165-minute morning → 33 bars at 5m.
    rows: list[dict[str, object]] = []
    base_close = 800.0
    for i in range(33):
        t_bkk = _BUSINESS_DAY.replace(hour=9, minute=45) + timedelta(minutes=5 * i)
        t_utc = t_bkk.astimezone(UTC)
        rows.append(
            {
                "time": t_utc,
                "open": Decimal(f"{base_close + i * 0.1:.4f}"),
                "high": Decimal(f"{base_close + i * 0.1 + 0.5:.4f}"),
                "low": Decimal(f"{base_close + i * 0.1 - 0.5:.4f}"),
                "close": Decimal(f"{base_close + i * 0.1 + 0.2:.4f}"),
                "volume": Decimal("1000.0000"),
            }
        )
    frame = pl.DataFrame(rows)
    if drop_middle:
        # Drop ``drop_middle`` bars starting at index 10 to create a real gap.
        kept = pl.concat([frame.head(10), frame.tail(frame.height - 10 - drop_middle)])
        frame = kept
    if dupes:
        frame = pl.concat([frame, frame.head(dupes)])
    return frame.with_columns(pl.col("time").dt.replace_time_zone("UTC"))


def test_validate_clean_frame_no_issues() -> None:
    v = Validator()
    df = _build_morning_5m_frame()
    report = v.validate(df, timeframe="5m", contract="S50M2026", as_of=_AS_OF)
    assert report.bar_count == 33
    assert report.duplicate_timestamps == 0
    assert report.missing_bars == 0
    assert report.is_clean


def test_validate_detects_duplicates() -> None:
    v = Validator()
    df = _build_morning_5m_frame(dupes=3)
    report = v.validate(df, timeframe="5m", contract="S50M2026", as_of=_AS_OF)
    assert report.duplicate_timestamps == 3
    assert any(i.kind == "duplicate_timestamp" for i in report.issues)


def test_validate_detects_missing_bars() -> None:
    v = Validator()
    df = _build_morning_5m_frame(drop_middle=5)
    report = v.validate(df, timeframe="5m", contract="S50M2026", as_of=_AS_OF)
    # The 5 dropped bars sit inside [day_min, day_max] so they ARE counted.
    assert report.missing_bars == 5
    assert any(i.kind == "missing_bar" for i in report.issues)


def test_validate_rejects_missing_columns() -> None:
    v = Validator()
    bad = pl.DataFrame({"time": []})
    with pytest.raises(ValidationError):
        v.validate(bad, timeframe="5m", contract="S50M2026", as_of=_AS_OF)


def test_validate_rejects_non_utc_time() -> None:
    v = Validator()
    df = _build_morning_5m_frame().with_columns(pl.col("time").dt.replace_time_zone("Asia/Bangkok"))
    with pytest.raises(ValidationError):
        v.validate(df, timeframe="5m", contract="S50M2026", as_of=_AS_OF)


def test_validate_flags_abnormal_spread() -> None:
    v = Validator()
    df = _build_morning_5m_frame()
    # Inject one giant spread at the last bar.
    last_idx = df.height - 1
    df = df.with_columns(
        pl.when(pl.int_range(df.height) == last_idx)
        .then(pl.lit(Decimal("100000.0000")).cast(pl.Decimal(18, 4)))
        .otherwise(pl.col("high"))
        .alias("high")
    )
    report = v.validate(df, timeframe="5m", contract="S50M2026", as_of=_AS_OF)
    assert report.abnormal_spread_bars >= 1


def test_cross_tf_consistency_5m_to_1h_match() -> None:
    v = Validator()
    finer = _build_morning_5m_frame()
    # Aggregate manually to construct the matching 1H frame.
    coarser = (
        finer.with_columns(pl.col("time").dt.truncate("60m").alias("bucket"))
        .group_by("bucket")
        .agg(
            [
                pl.col("open").first().alias("open"),
                pl.col("high").max().alias("high"),
                pl.col("low").min().alias("low"),
                pl.col("close").last().alias("close"),
                pl.col("volume").sum().alias("volume"),
            ]
        )
        .sort("bucket")
        .rename({"bucket": "time"})
    )
    mismatches = v.cross_timeframe_consistency(
        finer=finer, finer_tf="5m", coarser=coarser, coarser_tf="1h"
    )
    assert mismatches == 0


def test_cross_tf_consistency_rejects_invalid_pair() -> None:
    v = Validator()
    df = _build_morning_5m_frame()
    with pytest.raises(ValidationError):
        v.cross_timeframe_consistency(finer=df, finer_tf="4h", coarser=df, coarser_tf="5m")


def test_validate_continuous_against_reference_matches() -> None:
    v = Validator()
    base = _build_morning_5m_frame().select(["time", pl.col("close").cast(pl.Decimal(18, 4))])
    result = v.validate_continuous_against_reference(
        our_continuous=base,
        s501_reference=base,
        timeframe="5m",
    )
    assert result.aligned_bars >= 32  # we drop the first row's NaN return
    assert result.max_abs_return_diff == Decimal("0E-8")
    assert result.flagged == []
    assert result.tolerance == DEFAULT_CROSS_CHECK_TOLERANCE


def test_validate_continuous_against_reference_flags_divergence() -> None:
    v = Validator()
    base = _build_morning_5m_frame().select(["time", pl.col("close").cast(pl.Decimal(18, 4))])
    # Inject a 5% divergence on the second row's close in the reference series.
    rows = base.to_dicts()
    rows[1]["close"] = rows[1]["close"] * Decimal("1.05")
    ref = pl.DataFrame(rows)
    result = v.validate_continuous_against_reference(
        our_continuous=base,
        s501_reference=ref,
        timeframe="5m",
        tolerance=Decimal("0.0010"),
    )
    assert result.aligned_bars >= 32
    assert len(result.flagged) >= 1
    assert result.max_abs_return_diff > Decimal("0.001")


def test_validate_continuous_too_few_bars() -> None:
    v = Validator()
    empty = pl.DataFrame(
        {
            "time": [datetime(2026, 5, 27, 2, 45, tzinfo=UTC)],
            "close": [Decimal("800.0000")],
        }
    )
    result = v.validate_continuous_against_reference(
        our_continuous=empty,
        s501_reference=empty,
        timeframe="5m",
    )
    assert result.aligned_bars == 1
    assert result.flagged == []


def test_validator_uses_custom_calendar() -> None:
    cal = SessionCalendar(roll_offset_days=2)
    v = Validator(calendar=cal)
    df = _build_morning_5m_frame()
    report = v.validate(df, timeframe="5m", contract="S50M2026", as_of=_AS_OF)
    assert report.is_clean
