"""Tests for the execution-layer models, config bounds, and error hierarchy."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from tfex_s50_multi_tf_swing.adapters.errors import TfexS50Error
from tfex_s50_multi_tf_swing.execution.errors import ExecutionError, ExecutionInputError
from tfex_s50_multi_tf_swing.execution.models import EXIT_REASONS, ExecutionConfig, Trade


def test_exit_reasons_tuple() -> None:
    assert set(EXIT_REASONS) == {
        "take_profit",
        "stop_loss",
        "trailing_stop",
        "time_stop",
        "end_of_data",
    }


def test_trade_rejects_naive_time() -> None:
    with pytest.raises(ValidationError, match="UTC-aware"):
        Trade(
            strategy_id="A",
            direction="long",
            entry_time=datetime(2026, 1, 5, 3, 0),
            exit_time=datetime(2026, 1, 5, 3, 5, tzinfo=UTC),
            entry=Decimal("100"),
            stop=Decimal("97"),
            exit_price=Decimal("103"),
            pnl_points=Decimal("3"),
            r_multiple=Decimal("1"),
            bars_held=1,
            exit_reason="take_profit",
        )


def test_execution_config_bounds() -> None:
    with pytest.raises(ValidationError):
        ExecutionConfig(k_atr_stop=0.0)
    with pytest.raises(ValidationError):
        ExecutionConfig(partial_fraction=1.5)
    with pytest.raises(ValidationError):
        ExecutionConfig(time_stop_bars=0)


def test_errors_inherit_base() -> None:
    assert issubclass(ExecutionError, TfexS50Error)
    assert issubclass(ExecutionInputError, ExecutionError)
