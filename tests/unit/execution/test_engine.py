"""Simulated-bar-sequence tests for the 5m execution engine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import polars as pl
import pytest

from tfex_s50_multi_tf_swing.execution.engine import simulate_signals, simulate_trade
from tfex_s50_multi_tf_swing.execution.errors import ExecutionInputError
from tfex_s50_multi_tf_swing.execution.models import ExecutionConfig
from tfex_s50_multi_tf_swing.signals.models import SetupDirection, SetupSignal

_T0 = datetime(2026, 1, 5, 3, 0, tzinfo=UTC)
_BAR_SCHEMA: dict[str, pl.DataType] = {
    "time": pl.Datetime(time_unit="us", time_zone="UTC"),
    "open": pl.Float64(),
    "high": pl.Float64(),
    "low": pl.Float64(),
    "close": pl.Float64(),
    "atr": pl.Float64(),
}


def make_bars(ohlc: list[tuple[float, float, float, float]], *, atr: float = 2.0) -> pl.DataFrame:
    rows = [
        {
            "time": _T0 + timedelta(minutes=5 * i),
            "open": o,
            "high": h,
            "low": low,
            "close": c,
            "atr": atr,
        }
        for i, (o, h, low, c) in enumerate(ohlc)
    ]
    return pl.DataFrame(rows, schema=_BAR_SCHEMA)


def make_signal(
    trigger_index: int,
    direction: SetupDirection,
    stop_reference: float,
    *,
    trigger_price: float = 100.0,
) -> SetupSignal:
    return SetupSignal(
        strategy_id="A",
        time=_T0 + timedelta(minutes=5 * trigger_index),
        direction=direction,
        trigger_price=Decimal(str(trigger_price)),
        stop_reference=Decimal(str(stop_reference)),
        regime="trend_up",
    )


# The worked numeric examples below are pinned to k_atr_stop=1.5 (the default is now 2.0, a risk
# mitigation); they validate the stop-clamp / TP / trail math at a fixed k, not the default value.
_K15 = ExecutionConfig(k_atr_stop=1.5)


def test_long_stop_loss() -> None:
    bars = make_bars(
        [(100, 101, 99, 100), (100, 101, 99, 100), (99, 99, 96, 97)]  # trigger, entry, stop hit
    )
    trade = simulate_trade(make_signal(0, "long", 98.0), bars, config=_K15)
    assert trade is not None
    assert trade.exit_reason == "stop_loss"
    assert trade.entry == Decimal("100.0")
    assert trade.stop == Decimal("97.0")  # min(entry-1.5*atr=97, stop_ref=98)
    assert trade.r_multiple == Decimal("-1")
    assert trade.regime == "trend_up"


def test_long_take_profit_full_when_partial_fraction_one() -> None:
    config = ExecutionConfig(partial_fraction=1.0, k_atr_stop=1.5)
    bars = make_bars([(100, 101, 99, 100), (100, 101, 99, 100), (101, 104, 100, 103)])
    trade = simulate_trade(make_signal(0, "long", 98.0), bars, config=config)
    assert trade is not None
    assert trade.exit_reason == "take_profit"
    assert trade.exit_price == Decimal("103.0")  # target = entry + 1R (risk = 3)
    assert trade.r_multiple == Decimal("1")


def test_long_partial_then_trailing_stop() -> None:
    # Target (103) hit on bar2 → bank 50%, stop to breakeven; bar3 retraces to BE → trailing exit.
    bars = make_bars(
        [(100, 101, 99, 100), (100, 101, 99, 100), (101, 104, 101, 103), (101, 101, 99, 100)]
    )
    trade = simulate_trade(make_signal(0, "long", 98.0), bars, config=_K15)
    assert trade is not None
    assert trade.exit_reason == "trailing_stop"
    # 0.5 * (103 - 100) + 0.5 * (100 - 100) = 1.5 points; r = 1.5 / 3 = 0.5
    assert trade.pnl_points == Decimal("1.5")
    assert trade.r_multiple == Decimal("0.5")


def test_long_time_stop() -> None:
    config = ExecutionConfig(time_stop_bars=2)
    flat = [(100.0, 101.0, 99.0, 100.0)] * 5
    trade = simulate_trade(make_signal(0, "long", 98.0), make_bars(flat), config=config)
    assert trade is not None
    assert trade.exit_reason == "time_stop"
    assert trade.bars_held == 2


def test_long_end_of_data() -> None:
    # Rising after the partial, never retracing to the trail, frame ends → end_of_data.
    bars = make_bars(
        [(100, 101, 99, 100), (100, 101, 99, 100), (101, 104, 101, 103.5), (104, 106, 104, 106)]
    )
    trade = simulate_trade(make_signal(0, "long", 98.0), bars)
    assert trade is not None
    assert trade.exit_reason == "end_of_data"
    assert trade.exit_price == Decimal("106.0")


def test_short_stop_loss() -> None:
    bars = make_bars(
        [(100, 101, 99, 100), (100, 101, 99, 100), (101, 104, 101, 103)]  # entry 100, rises to stop
    )
    trade = simulate_trade(make_signal(0, "short", 102.0), bars, config=_K15)
    assert trade is not None
    assert trade.exit_reason == "stop_loss"
    assert trade.stop == Decimal("103.0")  # max(entry+1.5*atr=103, stop_ref=102)
    assert trade.r_multiple == Decimal("-1")


def test_spread_rejected() -> None:
    # Entry bar (index 1) range 20 ≫ 3 × median range (2) → no fill.
    bars = make_bars([(100, 101, 99, 100), (100, 110, 90, 100), (100, 101, 99, 100)])
    assert simulate_trade(make_signal(0, "long", 98.0), bars) is None


def test_trigger_on_last_bar_unfillable() -> None:
    bars = make_bars([(100, 101, 99, 100), (100, 101, 99, 100)])
    assert simulate_trade(make_signal(1, "long", 98.0), bars) is None


def test_unknown_trigger_time_returns_none() -> None:
    bars = make_bars([(100, 101, 99, 100), (100, 101, 99, 100)])
    stray = SetupSignal(
        strategy_id="A",
        time=datetime(2030, 1, 1, tzinfo=UTC),
        direction="long",
        trigger_price=Decimal("100"),
        stop_reference=Decimal("98"),
    )
    assert simulate_trade(stray, bars) is None


def test_non_positive_atr_returns_none() -> None:
    bars = make_bars([(100, 101, 99, 100), (100, 101, 99, 100), (99, 99, 96, 97)], atr=0.0)
    assert simulate_trade(make_signal(0, "long", 98.0), bars) is None


def test_missing_column_raises() -> None:
    bars = make_bars([(100, 101, 99, 100), (100, 101, 99, 100)]).drop("atr")
    with pytest.raises(ExecutionInputError, match="missing columns"):
        simulate_trade(make_signal(0, "long", 98.0), bars)


def test_simulate_signals_collects_fillable() -> None:
    bars = make_bars([(100, 101, 99, 100)] * 6)
    config = ExecutionConfig(time_stop_bars=1)
    signals = [make_signal(0, "long", 98.0), make_signal(1, "long", 98.0)]
    trades = simulate_signals(signals, bars, config=config)
    assert len(trades) == 2
    assert all(t.exit_reason == "time_stop" for t in trades)
