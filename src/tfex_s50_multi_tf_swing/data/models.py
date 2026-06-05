"""Pydantic models for the data layer.

All money/price fields are :class:`decimal.Decimal`. All timestamps are
timezone-aware UTC :class:`datetime`. Floats are rejected at the boundary;
they may appear in intermediate Polars frames for arithmetic, but never in a
persisted model.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Timeframe = Literal["5m", "1h", "4h", "1d"]
"""Supported timeframes. ``1d`` added for the 1H-execution migration (Daily HTF regime/bias)."""

TIMEFRAMES: tuple[Timeframe, ...] = ("5m", "1h", "4h", "1d")

TIMEFRAME_MINUTES: dict[Timeframe, int] = {"5m": 5, "1h": 60, "4h": 240, "1d": 1440}
"""Bar duration in minutes — used by validators and the cross-TF consistency check."""


def _reject_float(v: object) -> object:
    """Reject ``float`` values at Decimal-field validation time."""
    if isinstance(v, float):
        raise ValueError("float values are forbidden in persisted models; pass Decimal or str")
    return v


def _enforce_utc(v: datetime) -> datetime:
    """Reject tz-naive datetimes and non-UTC offsets."""
    if v.tzinfo is None:
        raise ValueError("datetime must be timezone-aware (UTC required)")
    if v.utcoffset() != UTC.utcoffset(v):
        raise ValueError(f"datetime must be UTC, got {v.tzinfo}")
    return v


class OhlcvBar(BaseModel):
    """One OHLCV bar for a single contract + timeframe.

    ``open_interest`` is optional because TradingView does not always supply it
    for TFEX futures; the persistence layer accepts ``None`` and stores SQL
    ``NULL``.
    """

    model_config = ConfigDict(frozen=True)

    time: datetime
    contract: str = Field(min_length=1)
    timeframe: Timeframe
    open: Decimal = Field(max_digits=18, decimal_places=4)
    high: Decimal = Field(max_digits=18, decimal_places=4)
    low: Decimal = Field(max_digits=18, decimal_places=4)
    close: Decimal = Field(max_digits=18, decimal_places=4)
    volume: Decimal = Field(max_digits=18, decimal_places=4, ge=0)
    open_interest: Decimal | None = Field(default=None, max_digits=18, decimal_places=4)

    @field_validator("time")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _enforce_utc(v)

    @field_validator("open", "high", "low", "close", "volume", "open_interest", mode="before")
    @classmethod
    def _no_float(cls, v: object) -> object:
        if v is None:
            return v
        return _reject_float(v)


class ContinuousBar(BaseModel):
    """One bar of the back-adjusted continuous series at a single timeframe.

    ``contract_at_time`` records which quarterly contract was active when this
    bar was originally observed; ``adjustment_factor`` is the cumulative ratio
    applied to historical prices to remove the rollover gap.
    """

    model_config = ConfigDict(frozen=True)

    time: datetime
    timeframe: Timeframe
    open: Decimal = Field(max_digits=18, decimal_places=4)
    high: Decimal = Field(max_digits=18, decimal_places=4)
    low: Decimal = Field(max_digits=18, decimal_places=4)
    close: Decimal = Field(max_digits=18, decimal_places=4)
    volume: Decimal = Field(max_digits=18, decimal_places=4, ge=0)
    contract_at_time: str = Field(min_length=1)
    adjustment_factor: Decimal = Field(max_digits=18, decimal_places=8, gt=0)

    @field_validator("time")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _enforce_utc(v)

    @field_validator("open", "high", "low", "close", "volume", "adjustment_factor", mode="before")
    @classmethod
    def _no_float(cls, v: object) -> object:
        return _reject_float(v)


class ContractSpec(BaseModel):
    """Static metadata for one quarterly S50 futures contract."""

    model_config = ConfigDict(frozen=True)

    code: str = Field(min_length=4, max_length=8)  # e.g. "S50H2026"
    month_code: Literal["H", "M", "U", "Z"]  # Mar / Jun / Sep / Dec
    year: int = Field(ge=2000, le=2099)
    expiry: date  # last trading day per TFEX convention


class RollRecord(BaseModel):
    """A single rollover event in the continuous series."""

    model_config = ConfigDict(frozen=True)

    roll_time: datetime
    from_contract: str = Field(min_length=1)
    to_contract: str = Field(min_length=1)
    ratio: Decimal = Field(max_digits=18, decimal_places=8, gt=0)

    @field_validator("roll_time")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _enforce_utc(v)

    @field_validator("ratio", mode="before")
    @classmethod
    def _no_float(cls, v: object) -> object:
        return _reject_float(v)


class SessionWindow(BaseModel):
    """A contiguous trading session as half-open ``[start, end)`` BKK times."""

    model_config = ConfigDict(frozen=True)

    name: Literal["morning", "afternoon", "night"]
    # Stored as minutes-of-day in Asia/Bangkok (0–1440). The night session may
    # cross midnight, in which case ``end_minute_bkk`` is on the next day.
    start_minute_bkk: int = Field(ge=0, le=1440)
    end_minute_bkk: int = Field(ge=0, le=2880)


ValidationIssueLevel = Literal["info", "warning", "error"]


class ValidationIssue(BaseModel):
    """One row of the per-frame validation report."""

    model_config = ConfigDict(frozen=True)

    level: ValidationIssueLevel
    kind: str = Field(min_length=1)
    detail: str
    count: int = Field(default=1, ge=0)


class CrossCheckPoint(BaseModel):
    """A timestamp where our continuous series diverged from ``S501!`` by more than tolerance."""

    model_config = ConfigDict(frozen=True)

    time: datetime
    our_return: Decimal = Field(max_digits=12, decimal_places=8)
    reference_return: Decimal = Field(max_digits=12, decimal_places=8)
    difference: Decimal = Field(max_digits=12, decimal_places=8)

    @field_validator("time")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _enforce_utc(v)

    @field_validator("our_return", "reference_return", "difference", mode="before")
    @classmethod
    def _no_float(cls, v: object) -> object:
        return _reject_float(v)


class ContinuousCrossCheck(BaseModel):
    """Informational comparison between our back-adjusted continuous and ``S501!``."""

    model_config = ConfigDict(frozen=True)

    timeframe: Timeframe
    aligned_bars: int = Field(ge=0)
    max_abs_return_diff: Decimal = Field(max_digits=12, decimal_places=8, ge=0)
    mean_abs_return_diff: Decimal = Field(max_digits=12, decimal_places=8, ge=0)
    flagged: list[CrossCheckPoint] = Field(default_factory=list)
    tolerance: Decimal = Field(max_digits=12, decimal_places=8, gt=0)

    @field_validator("max_abs_return_diff", "mean_abs_return_diff", "tolerance", mode="before")
    @classmethod
    def _no_float(cls, v: object) -> object:
        return _reject_float(v)


class ValidationReport(BaseModel):
    """Aggregate report produced by :class:`Validator.validate` and persisted to JSON."""

    model_config = ConfigDict(frozen=True)

    as_of: datetime
    contract: str = Field(min_length=1)
    timeframe: Timeframe
    bar_count: int = Field(ge=0)
    missing_bars: int = Field(ge=0)
    duplicate_timestamps: int = Field(ge=0)
    abnormal_spread_bars: int = Field(ge=0)
    cross_tf_inconsistencies: int = Field(default=0, ge=0)
    issues: list[ValidationIssue] = Field(default_factory=list)
    cross_check: ContinuousCrossCheck | None = Field(default=None)

    @field_validator("as_of")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _enforce_utc(v)

    @property
    def is_clean(self) -> bool:
        """``True`` when no ``error``-level issues were recorded."""
        return not any(issue.level == "error" for issue in self.issues)


__all__: list[str] = [
    "TIMEFRAMES",
    "TIMEFRAME_MINUTES",
    "ContinuousBar",
    "ContinuousCrossCheck",
    "ContractSpec",
    "CrossCheckPoint",
    "OhlcvBar",
    "RollRecord",
    "SessionWindow",
    "Timeframe",
    "ValidationIssue",
    "ValidationIssueLevel",
    "ValidationReport",
]
