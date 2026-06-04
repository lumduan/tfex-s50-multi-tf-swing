"""Backtest layer — per-strategy metrics (ROADMAP §5.5) + walk-forward harness (§8).

Phase 5 reports expectancy / profit factor / max drawdown / win rate / regime-stratified PnL (in
R-multiples) for a single strategy, run independently. Phase 8 adds the anchored walk-forward
harness, a realistic cost model, the drawdown profile + Sharpe/Sortino + regime-concentration
metrics, and a source-agnostic OHLCV loader. Pure offline library code — one-way dependency
``signals/ + execution/ + risk/ + regime/ + ml/ + data/ → backtest/``; imports nothing from
``api/``.
"""

from __future__ import annotations

from tfex_s50_multi_tf_swing.backtest.costs import (
    CostedTrade,
    CostModel,
    apply_costs,
    is_illiquid_session,
)
from tfex_s50_multi_tf_swing.backtest.data_source import (
    build_execution_bars,
    load_continuous_frames,
)
from tfex_s50_multi_tf_swing.backtest.errors import BacktestError, WalkForwardDataError
from tfex_s50_multi_tf_swing.backtest.metrics import (
    compute_metrics,
    drawdown_profile,
    expectancy,
    max_drawdown,
    period_ratios,
    profit_factor,
    regime_concentration,
    regime_stratified,
    sharpe,
    sortino,
    win_rate,
)
from tfex_s50_multi_tf_swing.backtest.models import (
    BacktestMetrics,
    DrawdownProfile,
    PeriodRatios,
    RegimeConcentration,
    RegimeMetrics,
    WalkForwardConfig,
    WalkForwardReport,
    WalkForwardResult,
    WalkForwardWindow,
    WindowResult,
)
from tfex_s50_multi_tf_swing.backtest.per_strategy import DetectFn, run_per_strategy_backtest
from tfex_s50_multi_tf_swing.backtest.walk_forward import (
    drive_costed_trades,
    generate_windows,
    run_walk_forward,
)

__all__: list[str] = [
    "BacktestError",
    "BacktestMetrics",
    "CostModel",
    "CostedTrade",
    "DetectFn",
    "DrawdownProfile",
    "PeriodRatios",
    "RegimeConcentration",
    "RegimeMetrics",
    "WalkForwardConfig",
    "WalkForwardDataError",
    "WalkForwardReport",
    "WalkForwardResult",
    "WalkForwardWindow",
    "WindowResult",
    "apply_costs",
    "build_execution_bars",
    "compute_metrics",
    "drawdown_profile",
    "drive_costed_trades",
    "expectancy",
    "generate_windows",
    "is_illiquid_session",
    "load_continuous_frames",
    "max_drawdown",
    "period_ratios",
    "profit_factor",
    "regime_concentration",
    "regime_stratified",
    "run_per_strategy_backtest",
    "run_walk_forward",
    "sharpe",
    "sortino",
    "win_rate",
]
