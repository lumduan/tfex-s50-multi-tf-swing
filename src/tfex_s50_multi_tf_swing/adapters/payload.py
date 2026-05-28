"""Pydantic models for the gateway daily-report ingestion contract.

Mirrors ``quant-api-gateway/src/schemas/strategy.py`` so payloads built
here serialise into a JSON shape the gateway accepts without coercion.
Monetary and ratio fields are :class:`decimal.Decimal` and are serialised
as JSON strings (``model_dump(mode="json")``) so the gateway's
``Decimal`` re-parse is lossless. Floats are rejected at validation
time — the umbrella + TFEX hard rule "no float across the gateway
boundary".

The ``ExtendedDataReport`` model embeds the TFEX-specific hard rule that
``margin_usage`` is a first-class field present on every daily snapshot.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
)

STRATEGY_TYPE: str = "TFEX_DERIVATIVES"
INGEST_PATH: str = "/api/v1/ingest/daily-report"


def _reject_float(v: object) -> object:
    """Reject Python ``float`` inputs for Decimal fields.

    Pydantic v2 would silently coerce floats to ``Decimal``; that allows
    binary-float precision noise into the wire payload. We reject explicitly.
    """
    if isinstance(v, float):
        raise ValueError("float values are forbidden; pass Decimal or str")
    return v


class StrategyMetadata(BaseModel):
    """Strategy identification metadata."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    id: str = Field(min_length=1)
    type: str = Field(min_length=1, default=STRATEGY_TYPE)
    last_updated: datetime

    @field_validator("last_updated")
    @classmethod
    def _enforce_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("last_updated must be timezone-aware (UTC required)")
        if v.utcoffset() != UTC.utcoffset(v):
            raise ValueError(f"last_updated must be UTC, got {v.tzinfo}")
        return v


class EquityPoint(BaseModel):
    """A single (date, value) point in an equity curve."""

    model_config = ConfigDict(frozen=True)

    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    value: Decimal = Field(max_digits=18, decimal_places=4)

    @field_validator("value", mode="before")
    @classmethod
    def _no_float(cls, v: object) -> object:
        return _reject_float(v)

    @field_serializer("value")
    def _value_to_str(self, v: Decimal) -> str:
        return f"{v:.4f}"


class PerformanceMetrics(BaseModel):
    """Performance metrics for a single reporting period."""

    model_config = ConfigDict(frozen=True)

    daily_pnl: Decimal = Field(max_digits=18, decimal_places=4)
    equity_curve: list[EquityPoint] = Field(min_length=1)
    max_drawdown: Decimal = Field(max_digits=8, decimal_places=4)
    sharpe_ratio: Decimal = Field(max_digits=8, decimal_places=4)

    @field_validator("daily_pnl", "max_drawdown", "sharpe_ratio", mode="before")
    @classmethod
    def _no_float(cls, v: object) -> object:
        return _reject_float(v)

    @field_validator("max_drawdown")
    @classmethod
    def _max_drawdown_not_positive(cls, v: Decimal) -> Decimal:
        if v > 0:
            raise ValueError(f"max_drawdown must be ≤ 0, got {v}")
        return v

    @field_serializer("daily_pnl", "max_drawdown", "sharpe_ratio")
    def _to_str(self, v: Decimal) -> str:
        return f"{v:.4f}"


class CurrentExposure(BaseModel):
    """Snapshot of current positions and capital."""

    model_config = ConfigDict(frozen=True)

    total_value: Decimal = Field(max_digits=18, decimal_places=4, ge=0)
    cash_balance: Decimal = Field(max_digits=18, decimal_places=4, ge=0)
    positions_count: int = Field(ge=0)

    @field_validator("total_value", "cash_balance", mode="before")
    @classmethod
    def _no_float(cls, v: object) -> object:
        return _reject_float(v)

    @field_serializer("total_value", "cash_balance")
    def _to_str(self, v: Decimal) -> str:
        return f"{v:.4f}"


class ExtendedDataReport(BaseModel):
    """TFEX-specific extended report block.

    ``margin_usage`` is **mandatory** per TFEX CLAUDE.md hard rule #2: every
    daily snapshot the strategy posts to the gateway must carry the current
    margin commitment as a Decimal-as-string.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    margin_usage: Decimal = Field(max_digits=18, decimal_places=4, ge=0)

    @field_validator("margin_usage", mode="before")
    @classmethod
    def _no_float(cls, v: object) -> object:
        return _reject_float(v)

    @field_serializer("margin_usage")
    def _to_str(self, v: Decimal) -> str:
        return f"{v:.4f}"


class ExtendedData(BaseModel):
    """Wrapper for ``extended_data`` so ``report`` is required for TFEX."""

    model_config = ConfigDict(frozen=True, extra="allow")

    report: ExtendedDataReport


class StrategyPayload(BaseModel):
    """Top-level ingestion payload posted to ``POST /api/v1/ingest/daily-report``."""

    model_config = ConfigDict(frozen=True)

    strategy_metadata: StrategyMetadata
    performance_metrics: PerformanceMetrics
    current_exposure: CurrentExposure
    extended_data: ExtendedData


def build_ingestion_payload(
    *,
    strategy_id: str,
    last_updated: datetime,
    daily_pnl: Decimal,
    equity_curve: list[tuple[str, Decimal]],
    max_drawdown: Decimal,
    sharpe_ratio: Decimal,
    total_value: Decimal,
    cash_balance: Decimal,
    positions_count: int,
    margin_usage: Decimal,
    extra_report: dict[str, Any] | None = None,
) -> StrategyPayload:
    """Build a validated :class:`StrategyPayload` from explicit components.

    Args:
        strategy_id: Stable identifier (e.g. ``"tfex-s50-multi-tf-swing"``).
        last_updated: UTC-aware "as-of" timestamp for this report.
        daily_pnl: Realised PnL for the day (Decimal).
        equity_curve: List of ``(YYYY-MM-DD, value)`` tuples — must be non-empty.
        max_drawdown: Fractional drawdown (≤ 0).
        sharpe_ratio: Sharpe ratio over the equity curve.
        total_value: Total portfolio value.
        cash_balance: Cash + margin reserve (≥ 0).
        positions_count: Number of open contract positions (≥ 0).
        margin_usage: Margin currently committed to open positions.
        extra_report: Optional additional report fields (merged into
            ``extended_data.report``).

    Returns:
        A validated :class:`StrategyPayload` ready for
        :meth:`pydantic.BaseModel.model_dump` ``mode="json"`` serialisation.
    """
    report_payload: dict[str, Any] = {"margin_usage": margin_usage}
    if extra_report:
        report_payload.update(extra_report)
    return StrategyPayload(
        strategy_metadata=StrategyMetadata(id=strategy_id, last_updated=last_updated),
        performance_metrics=PerformanceMetrics(
            daily_pnl=daily_pnl,
            equity_curve=[EquityPoint(date=d, value=v) for d, v in equity_curve],
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
        ),
        current_exposure=CurrentExposure(
            total_value=total_value,
            cash_balance=cash_balance,
            positions_count=positions_count,
        ),
        extended_data=ExtendedData(report=ExtendedDataReport(**report_payload)),
    )


__all__: list[str] = [
    "INGEST_PATH",
    "STRATEGY_TYPE",
    "CurrentExposure",
    "EquityPoint",
    "ExtendedData",
    "ExtendedDataReport",
    "PerformanceMetrics",
    "StrategyMetadata",
    "StrategyPayload",
    "build_ingestion_payload",
]
