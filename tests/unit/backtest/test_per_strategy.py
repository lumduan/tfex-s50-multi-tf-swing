"""Wiring test for the per-strategy backtest runner (detect → simulate → metrics)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import polars as pl

from tfex_s50_multi_tf_swing.backtest.per_strategy import run_per_strategy_backtest
from tfex_s50_multi_tf_swing.execution.models import ExecutionConfig
from tfex_s50_multi_tf_swing.signals.models import SetupSignal

_T0 = datetime(2026, 1, 5, 3, 0, tzinfo=UTC)
_BAR_SCHEMA: dict[str, pl.DataType] = {
    "time": pl.Datetime(time_unit="us", time_zone="UTC"),
    "open": pl.Float64(),
    "high": pl.Float64(),
    "low": pl.Float64(),
    "close": pl.Float64(),
    "atr": pl.Float64(),
}


def _bars(n: int) -> pl.DataFrame:
    rows = [
        {
            "time": _T0 + timedelta(minutes=5 * i),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "atr": 2.0,
        }
        for i in range(n)
    ]
    return pl.DataFrame(rows, schema=_BAR_SCHEMA)


def _signal(i: int) -> SetupSignal:
    return SetupSignal(
        strategy_id="A",
        time=_T0 + timedelta(minutes=5 * i),
        direction="long",
        trigger_price=Decimal("100"),
        stop_reference=Decimal("98"),
        regime="trend_up",
    )


def test_run_per_strategy_backtest_wires_chain() -> None:
    detected = [_signal(0), _signal(1)]
    metrics = run_per_strategy_backtest(
        lambda _inputs: detected,
        pl.DataFrame({"time": []}),
        _bars(6),
        strategy_id="A",
        config=ExecutionConfig(time_stop_bars=1),
    )
    assert metrics.strategy_id == "A"
    assert metrics.n_trades == 2
    assert "trend_up" in metrics.per_regime


def test_run_per_strategy_backtest_no_signals() -> None:
    metrics = run_per_strategy_backtest(
        lambda _inputs: [], pl.DataFrame({"time": []}), _bars(4), strategy_id="B"
    )
    assert metrics.n_trades == 0
    assert metrics.strategy_id == "B"


def test_ml_filter_none_is_noop() -> None:
    detected = [_signal(0), _signal(1)]
    baseline = run_per_strategy_backtest(
        lambda _inputs: detected,
        pl.DataFrame({"time": []}),
        _bars(6),
        strategy_id="A",
        config=ExecutionConfig(time_stop_bars=1),
    )
    explicit = run_per_strategy_backtest(
        lambda _inputs: detected,
        pl.DataFrame({"time": []}),
        _bars(6),
        strategy_id="A",
        config=ExecutionConfig(time_stop_bars=1),
        ml_filter=None,
    )
    assert explicit == baseline


def test_ml_filter_applied_before_simulation() -> None:
    # A gate that drops every signal → zero trades, proving the hook runs pre-simulation.
    metrics = run_per_strategy_backtest(
        lambda _inputs: [_signal(0), _signal(1)],
        pl.DataFrame({"time": []}),
        _bars(6),
        strategy_id="A",
        config=ExecutionConfig(time_stop_bars=1),
        ml_filter=lambda _signals, _inputs: [],
    )
    assert metrics.n_trades == 0
