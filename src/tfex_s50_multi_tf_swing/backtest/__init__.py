"""Per-strategy backtest layer (ROADMAP Phase 5 — §5.5).

Reports expectancy / profit factor / max drawdown / win rate / regime-stratified PnL (in
R-multiples) for a single strategy, run independently before any composite. Pure offline library
code — one-way dependency ``signals/ + execution/ → backtest/``. The walk-forward harness, cost
model, and Sharpe/Sortino are Phase 8.
"""

from __future__ import annotations

from tfex_s50_multi_tf_swing.backtest.errors import BacktestError
from tfex_s50_multi_tf_swing.backtest.metrics import (
    compute_metrics,
    expectancy,
    max_drawdown,
    profit_factor,
    regime_stratified,
    win_rate,
)
from tfex_s50_multi_tf_swing.backtest.models import BacktestMetrics, RegimeMetrics
from tfex_s50_multi_tf_swing.backtest.per_strategy import DetectFn, run_per_strategy_backtest

__all__: list[str] = [
    "BacktestError",
    "BacktestMetrics",
    "DetectFn",
    "RegimeMetrics",
    "compute_metrics",
    "expectancy",
    "max_drawdown",
    "profit_factor",
    "regime_stratified",
    "run_per_strategy_backtest",
    "win_rate",
]
