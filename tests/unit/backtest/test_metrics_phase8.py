"""Phase-8 metric tests — drawdown profile, Sharpe / Sortino, regime concentration."""

from __future__ import annotations

from decimal import Decimal

from tfex_s50_multi_tf_swing.backtest.metrics import (
    drawdown_profile,
    period_ratios,
    regime_concentration,
    sharpe,
    sortino,
)
from tfex_s50_multi_tf_swing.backtest.models import BacktestMetrics, RegimeMetrics
from tfex_s50_multi_tf_swing.regime.models import Regime

from .conftest import make_trade


def test_drawdown_profile_recovers() -> None:
    trades = [make_trade(r=r) for r in (Decimal("1"), Decimal("-2"), Decimal("3"))]
    dd = drawdown_profile(trades)
    assert dd.depth_r == Decimal("2")
    assert dd.time_underwater == 1
    assert dd.recovery_trades == 1


def test_drawdown_profile_never_recovers() -> None:
    trades = [make_trade(r=r) for r in (Decimal("1"), Decimal("1"), Decimal("-3"), Decimal("1"))]
    dd = drawdown_profile(trades)
    assert dd.depth_r == Decimal("3")
    assert dd.recovery_trades is None
    assert dd.time_underwater == 2


def test_drawdown_profile_empty() -> None:
    dd = drawdown_profile([])
    assert dd.depth_r == Decimal("0")
    assert dd.time_underwater == 0
    assert dd.recovery_trades is None


def test_sharpe() -> None:
    assert sharpe([1.0, 2.0, 3.0]) == 2.0  # mean 2, sample std 1
    assert sharpe([1.0]) is None
    assert sharpe([1.0, 1.0, 1.0]) is None  # zero variance


def test_sortino() -> None:
    assert sortino([1.0, 2.0, 3.0]) is None  # no downside
    assert sortino([1.0]) is None
    value = sortino([1.0, -1.0, 2.0])
    assert value is not None and value > 0


def test_period_ratios_bundles() -> None:
    ratios = period_ratios([1.0, 2.0, 3.0])
    assert ratios.n_periods == 3
    assert ratios.sharpe == 2.0


def _metrics(per_regime: dict[Regime, RegimeMetrics]) -> BacktestMetrics:
    return BacktestMetrics(
        n_trades=sum(rm.n_trades for rm in per_regime.values()),
        expectancy_r=Decimal("0"),
        max_drawdown_r=Decimal("0"),
        win_rate=Decimal("0"),
        per_regime=per_regime,
    )


def test_regime_concentration_fails_loudly() -> None:
    metrics = _metrics(
        {
            "trend_up": RegimeMetrics(
                regime="trend_up", n_trades=10, expectancy_r=Decimal("1"), win_rate=Decimal("0.6")
            ),
            "range_high_vol": RegimeMetrics(
                regime="range_high_vol",
                n_trades=1,
                expectancy_r=Decimal("0.1"),
                win_rate=Decimal("0.5"),
            ),
        }
    )
    conc = regime_concentration(metrics)
    assert conc.dominant_regime == "trend_up"
    assert conc.concentrated is True
    assert conc.share > 0.8


def test_regime_concentration_balanced() -> None:
    metrics = _metrics(
        {
            "trend_up": RegimeMetrics(
                regime="trend_up", n_trades=5, expectancy_r=Decimal("1"), win_rate=Decimal("0.5")
            ),
            "trend_down": RegimeMetrics(
                regime="trend_down", n_trades=5, expectancy_r=Decimal("1"), win_rate=Decimal("0.5")
            ),
        }
    )
    conc = regime_concentration(metrics)
    assert conc.concentrated is False
    assert conc.share == 0.5


def test_regime_concentration_single_regime_not_flagged() -> None:
    metrics = _metrics(
        {
            "trend_up": RegimeMetrics(
                regime="trend_up", n_trades=5, expectancy_r=Decimal("1"), win_rate=Decimal("0.5")
            )
        }
    )
    conc = regime_concentration(metrics)
    assert conc.share == 1.0
    assert conc.concentrated is False  # only one regime traded


def test_regime_concentration_empty() -> None:
    conc = regime_concentration(_metrics({}))
    assert conc.dominant_regime is None
    assert conc.share == 0.0
    assert conc.concentrated is False
