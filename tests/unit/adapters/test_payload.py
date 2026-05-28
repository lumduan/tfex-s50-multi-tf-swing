"""Tests for ``tfex_s50_multi_tf_swing.adapters.payload``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from tfex_s50_multi_tf_swing.adapters.payload import (
    INGEST_PATH,
    STRATEGY_TYPE,
    CurrentExposure,
    EquityPoint,
    ExtendedData,
    ExtendedDataReport,
    PerformanceMetrics,
    StrategyMetadata,
    StrategyPayload,
    build_ingestion_payload,
)

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------


def test_module_constants() -> None:
    assert STRATEGY_TYPE == "TFEX_DERIVATIVES"
    assert INGEST_PATH == "/api/v1/ingest/daily-report"


# ---------------------------------------------------------------------------
# StrategyMetadata — UTC enforcement + defaulted type
# ---------------------------------------------------------------------------


def test_metadata_defaults_type_to_tfex_derivatives() -> None:
    meta = StrategyMetadata(
        id="tfex-s50-multi-tf-swing",
        last_updated=datetime(2026, 5, 28, tzinfo=UTC),
    )
    assert meta.type == STRATEGY_TYPE


def test_metadata_strips_id_whitespace() -> None:
    meta = StrategyMetadata(
        id="  tfex-s50-multi-tf-swing  ",
        last_updated=datetime(2026, 5, 28, tzinfo=UTC),
    )
    assert meta.id == "tfex-s50-multi-tf-swing"


def test_metadata_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        StrategyMetadata(id="x", last_updated=datetime(2026, 5, 28))


def test_metadata_rejects_non_utc_datetime() -> None:
    bangkok = timezone(timedelta(hours=7))
    with pytest.raises(ValidationError, match="must be UTC"):
        StrategyMetadata(id="x", last_updated=datetime(2026, 5, 28, tzinfo=bangkok))


def test_metadata_rejects_empty_id() -> None:
    with pytest.raises(ValidationError):
        StrategyMetadata(id="", last_updated=datetime(2026, 5, 28, tzinfo=UTC))


# ---------------------------------------------------------------------------
# EquityPoint — date pattern + Decimal serialisation
# ---------------------------------------------------------------------------


def test_equity_point_serialises_value_as_string() -> None:
    point = EquityPoint(date="2026-05-28", value=Decimal("12345.6789"))
    dumped = point.model_dump(mode="json")
    assert dumped == {"date": "2026-05-28", "value": "12345.6789"}


def test_equity_point_pads_to_four_decimals() -> None:
    point = EquityPoint(date="2026-05-28", value=Decimal("10"))
    assert point.model_dump(mode="json")["value"] == "10.0000"


def test_equity_point_rejects_float_value() -> None:
    with pytest.raises(ValidationError, match="float values are forbidden"):
        EquityPoint(date="2026-05-28", value=1234.5)  # type: ignore[arg-type]


def test_equity_point_rejects_bad_date_format() -> None:
    with pytest.raises(ValidationError):
        EquityPoint(date="28-05-2026", value=Decimal("1"))


# ---------------------------------------------------------------------------
# PerformanceMetrics — drawdown sign + float rejection + curve length
# ---------------------------------------------------------------------------


def _curve() -> list[EquityPoint]:
    return [EquityPoint(date="2026-05-28", value=Decimal("100.0000"))]


def test_performance_metrics_rejects_positive_drawdown() -> None:
    with pytest.raises(ValidationError, match="max_drawdown must be ≤ 0"):
        PerformanceMetrics(
            daily_pnl=Decimal("0"),
            equity_curve=_curve(),
            max_drawdown=Decimal("0.05"),
            sharpe_ratio=Decimal("1.0"),
        )


def test_performance_metrics_requires_non_empty_curve() -> None:
    with pytest.raises(ValidationError):
        PerformanceMetrics(
            daily_pnl=Decimal("0"),
            equity_curve=[],
            max_drawdown=Decimal("0"),
            sharpe_ratio=Decimal("1.0"),
        )


def test_performance_metrics_rejects_float_pnl() -> None:
    with pytest.raises(ValidationError, match="float values are forbidden"):
        PerformanceMetrics(
            daily_pnl=12.5,  # type: ignore[arg-type]
            equity_curve=_curve(),
            max_drawdown=Decimal("0"),
            sharpe_ratio=Decimal("1.0"),
        )


def test_performance_metrics_serialises_all_decimals_as_string() -> None:
    pm = PerformanceMetrics(
        daily_pnl=Decimal("12.5500"),
        equity_curve=_curve(),
        max_drawdown=Decimal("-0.0460"),
        sharpe_ratio=Decimal("1.4200"),
    )
    dumped = pm.model_dump(mode="json")
    assert dumped["daily_pnl"] == "12.5500"
    assert dumped["max_drawdown"] == "-0.0460"
    assert dumped["sharpe_ratio"] == "1.4200"
    assert dumped["equity_curve"][0]["value"] == "100.0000"


# ---------------------------------------------------------------------------
# CurrentExposure — ge=0 constraints + serialisation
# ---------------------------------------------------------------------------


def test_current_exposure_rejects_negative_total_value() -> None:
    with pytest.raises(ValidationError):
        CurrentExposure(
            total_value=Decimal("-1"),
            cash_balance=Decimal("0"),
            positions_count=0,
        )


def test_current_exposure_rejects_negative_positions_count() -> None:
    with pytest.raises(ValidationError):
        CurrentExposure(
            total_value=Decimal("0"),
            cash_balance=Decimal("0"),
            positions_count=-1,
        )


def test_current_exposure_rejects_float() -> None:
    with pytest.raises(ValidationError, match="float values are forbidden"):
        CurrentExposure(
            total_value=1.0,  # type: ignore[arg-type]
            cash_balance=Decimal("0"),
            positions_count=0,
        )


def test_current_exposure_serialises_decimals_as_string() -> None:
    exp = CurrentExposure(
        total_value=Decimal("999999.1234"),
        cash_balance=Decimal("100.0000"),
        positions_count=3,
    )
    dumped = exp.model_dump(mode="json")
    assert dumped == {
        "total_value": "999999.1234",
        "cash_balance": "100.0000",
        "positions_count": 3,
    }


# ---------------------------------------------------------------------------
# ExtendedDataReport — margin_usage is mandatory and Decimal-as-string
# ---------------------------------------------------------------------------


def test_extended_report_requires_margin_usage() -> None:
    with pytest.raises(ValidationError):
        ExtendedDataReport()  # type: ignore[call-arg]


def test_extended_report_rejects_float_margin() -> None:
    with pytest.raises(ValidationError, match="float values are forbidden"):
        ExtendedDataReport(margin_usage=1.0)  # type: ignore[arg-type]


def test_extended_report_rejects_negative_margin() -> None:
    with pytest.raises(ValidationError):
        ExtendedDataReport(margin_usage=Decimal("-1"))


def test_extended_report_allows_additional_fields() -> None:
    report = ExtendedDataReport.model_validate(
        {
            "margin_usage": Decimal("142500.0000"),
            "contracts_long": 3,
            "regime": "trend_up",
        }
    )
    dumped = report.model_dump(mode="json")
    assert dumped["margin_usage"] == "142500.0000"
    assert dumped["contracts_long"] == 3
    assert dumped["regime"] == "trend_up"


def test_extended_data_round_trips() -> None:
    ed = ExtendedData(report=ExtendedDataReport(margin_usage=Decimal("0")))
    assert ed.report.margin_usage == Decimal("0")


# ---------------------------------------------------------------------------
# StrategyPayload — top-level shape + builder
# ---------------------------------------------------------------------------


def test_build_ingestion_payload_produces_valid_payload() -> None:
    payload = build_ingestion_payload(
        strategy_id="tfex-s50-multi-tf-swing",
        last_updated=datetime(2026, 5, 28, 12, 0, tzinfo=UTC),
        daily_pnl=Decimal("0.0000"),
        equity_curve=[("2026-05-28", Decimal("100000.0000"))],
        max_drawdown=Decimal("0.0000"),
        sharpe_ratio=Decimal("0.0000"),
        total_value=Decimal("100000.0000"),
        cash_balance=Decimal("100000.0000"),
        positions_count=0,
        margin_usage=Decimal("0.0000"),
    )
    assert isinstance(payload, StrategyPayload)
    assert payload.strategy_metadata.type == "TFEX_DERIVATIVES"


def test_build_ingestion_payload_merges_extra_report_fields() -> None:
    payload = build_ingestion_payload(
        strategy_id="tfex-s50-multi-tf-swing",
        last_updated=datetime(2026, 5, 28, tzinfo=UTC),
        daily_pnl=Decimal("0"),
        equity_curve=[("2026-05-28", Decimal("1"))],
        max_drawdown=Decimal("0"),
        sharpe_ratio=Decimal("0"),
        total_value=Decimal("0"),
        cash_balance=Decimal("0"),
        positions_count=0,
        margin_usage=Decimal("100.0000"),
        extra_report={"contracts_long": 2, "regime": "trend_up"},
    )
    dumped = payload.model_dump(mode="json")
    report = dumped["extended_data"]["report"]
    assert report["margin_usage"] == "100.0000"
    assert report["contracts_long"] == 2
    assert report["regime"] == "trend_up"


def test_strategy_payload_full_json_dump_shape() -> None:
    payload = build_ingestion_payload(
        strategy_id="tfex-s50-multi-tf-swing",
        last_updated=datetime(2026, 5, 28, 0, 0, tzinfo=UTC),
        daily_pnl=Decimal("12.5500"),
        equity_curve=[("2026-05-28", Decimal("991892.7100"))],
        max_drawdown=Decimal("-0.0460"),
        sharpe_ratio=Decimal("1.4200"),
        total_value=Decimal("991892.7100"),
        cash_balance=Decimal("37699.7100"),
        positions_count=5,
        margin_usage=Decimal("142500.0000"),
    )
    dumped = payload.model_dump(mode="json")
    assert set(dumped) == {
        "strategy_metadata",
        "performance_metrics",
        "current_exposure",
        "extended_data",
    }
    assert dumped["performance_metrics"]["daily_pnl"] == "12.5500"
    assert dumped["current_exposure"]["positions_count"] == 5
    assert dumped["extended_data"]["report"]["margin_usage"] == "142500.0000"
