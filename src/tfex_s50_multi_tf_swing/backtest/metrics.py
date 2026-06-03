"""Per-strategy backtest metrics (ROADMAP §5.5).

Pure functions over a ``list[Trade]`` — expectancy (mean R), profit factor (gross-win-R /
gross-loss-R), max drawdown (on the cumulative-R equity curve), win rate, and a regime
stratification. Everything is :class:`~decimal.Decimal` in R-multiples; all functions are
empty-safe (no divide-by-zero, no exceptions on an empty list).
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from tfex_s50_multi_tf_swing.backtest.models import BacktestMetrics, RegimeMetrics
from tfex_s50_multi_tf_swing.execution.models import Trade
from tfex_s50_multi_tf_swing.regime.models import Regime
from tfex_s50_multi_tf_swing.signals.models import StrategyId

_ZERO = Decimal(0)


def expectancy(trades: list[Trade]) -> Decimal:
    """Mean R-multiple per trade (``0`` when there are no trades)."""
    if not trades:
        return _ZERO
    total = sum((t.r_multiple for t in trades), _ZERO)
    return total / Decimal(len(trades))


def profit_factor(trades: list[Trade]) -> Decimal | None:
    """Gross-win-R / gross-loss-R; ``None`` when there are no losses (undefined / infinite)."""
    gross_win = sum((t.r_multiple for t in trades if t.r_multiple > 0), _ZERO)
    gross_loss = sum((-t.r_multiple for t in trades if t.r_multiple < 0), _ZERO)
    if gross_loss == _ZERO:
        return None
    return gross_win / gross_loss


def max_drawdown(trades: list[Trade]) -> Decimal:
    """Max peak-to-trough drop of the cumulative-R equity curve, as a non-negative Decimal."""
    equity = _ZERO
    peak = _ZERO
    worst = _ZERO
    for trade in trades:
        equity += trade.r_multiple
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def win_rate(trades: list[Trade]) -> Decimal:
    """Fraction of trades with positive R (``0`` when there are no trades)."""
    if not trades:
        return _ZERO
    wins = sum(1 for t in trades if t.r_multiple > 0)
    return Decimal(wins) / Decimal(len(trades))


def regime_stratified(trades: list[Trade]) -> dict[Regime, RegimeMetrics]:
    """Per-regime metrics; trades with no regime label are omitted (still in the aggregate)."""
    buckets: dict[Regime, list[Trade]] = defaultdict(list)
    for trade in trades:
        if trade.regime is not None:
            buckets[trade.regime].append(trade)
    return {
        regime: RegimeMetrics(
            regime=regime,
            n_trades=len(group),
            expectancy_r=expectancy(group),
            profit_factor=profit_factor(group),
            win_rate=win_rate(group),
        )
        for regime, group in buckets.items()
    }


def compute_metrics(
    trades: list[Trade], *, strategy_id: StrategyId | None = None
) -> BacktestMetrics:
    """Assemble the full :class:`BacktestMetrics` report (empty-safe)."""
    return BacktestMetrics(
        strategy_id=strategy_id,
        n_trades=len(trades),
        expectancy_r=expectancy(trades),
        profit_factor=profit_factor(trades),
        max_drawdown_r=max_drawdown(trades),
        win_rate=win_rate(trades),
        per_regime=regime_stratified(trades),
    )


__all__: list[str] = [
    "compute_metrics",
    "expectancy",
    "max_drawdown",
    "profit_factor",
    "regime_stratified",
    "win_rate",
]
