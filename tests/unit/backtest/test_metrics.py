"""Known-value tests for the per-strategy backtest metrics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tfex_s50_multi_tf_swing.backtest.metrics import (
    compute_metrics,
    expectancy,
    max_drawdown,
    profit_factor,
    regime_stratified,
    win_rate,
)
from tfex_s50_multi_tf_swing.execution.models import Trade
from tfex_s50_multi_tf_swing.regime.models import Regime

_T0 = datetime(2026, 1, 5, 3, 0, tzinfo=UTC)


def make_trade(r: str, *, regime: Regime | None = None, i: int = 0) -> Trade:
    r_dec = Decimal(r)
    return Trade(
        strategy_id="A",
        direction="long",
        entry_time=_T0 + timedelta(minutes=5 * i),
        exit_time=_T0 + timedelta(minutes=5 * i + 5),
        entry=Decimal("100"),
        stop=Decimal("97"),
        exit_price=Decimal("100") + r_dec * Decimal("3"),
        pnl_points=r_dec * Decimal("3"),
        r_multiple=r_dec,
        bars_held=1,
        exit_reason="take_profit" if r_dec > 0 else "stop_loss",
        regime=regime,
    )


def test_expectancy_mean_r() -> None:
    trades = [make_trade("1"), make_trade("-1"), make_trade("2")]
    assert expectancy(trades) == Decimal(2) / Decimal(3)


def test_expectancy_empty_is_zero() -> None:
    assert expectancy([]) == Decimal(0)


def test_profit_factor() -> None:
    trades = [make_trade("1"), make_trade("2"), make_trade("-1")]
    assert profit_factor(trades) == Decimal(3)


def test_profit_factor_none_without_losses() -> None:
    assert profit_factor([make_trade("1"), make_trade("2")]) is None
    assert profit_factor([]) is None


def test_max_drawdown() -> None:
    # equity: +1 -> 1, -1 -> 0 (dd 1 from peak 1), +2 -> 2
    assert max_drawdown([make_trade("1"), make_trade("-1"), make_trade("2")]) == Decimal(1)


def test_max_drawdown_empty_is_zero() -> None:
    assert max_drawdown([]) == Decimal(0)


def test_win_rate() -> None:
    trades = [make_trade("1"), make_trade("-1"), make_trade("2")]
    assert win_rate(trades) == Decimal(2) / Decimal(3)
    assert win_rate([]) == Decimal(0)


def test_regime_stratified_groups_and_skips_none() -> None:
    trades = [
        make_trade("1", regime="trend_up"),
        make_trade("-1", regime="trend_up"),
        make_trade("2", regime="range_high_vol"),
        make_trade("1", regime=None),  # omitted from the per-regime view
    ]
    per_regime = regime_stratified(trades)
    assert set(per_regime) == {"trend_up", "range_high_vol"}
    assert per_regime["trend_up"].n_trades == 2
    assert per_regime["trend_up"].expectancy_r == Decimal(0)
    assert per_regime["range_high_vol"].win_rate == Decimal(1)


def test_compute_metrics_assembles_report() -> None:
    trades = [make_trade("1", regime="trend_up"), make_trade("-1", regime="trend_up")]
    metrics = compute_metrics(trades, strategy_id="A")
    assert metrics.strategy_id == "A"
    assert metrics.n_trades == 2
    assert metrics.expectancy_r == Decimal(0)
    assert metrics.profit_factor == Decimal(1)
    assert metrics.win_rate == Decimal(1) / Decimal(2)
    assert "trend_up" in metrics.per_regime


def test_compute_metrics_empty_safe() -> None:
    metrics = compute_metrics([])
    assert metrics.n_trades == 0
    assert metrics.expectancy_r == Decimal(0)
    assert metrics.profit_factor is None
    assert metrics.max_drawdown_r == Decimal(0)
    assert metrics.win_rate == Decimal(0)
    assert metrics.per_regime == {}
