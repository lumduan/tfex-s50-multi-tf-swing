"""Per-strategy backtest runner (ROADMAP §5.5).

Wires the three Phase-5 layers end-to-end for a single strategy:
``detect(inputs) → list[SetupSignal]`` → :func:`simulate_signals` → :func:`compute_metrics`.
Each strategy is backtested **independently** (before any composite), exactly as the ROADMAP
requires. The walk-forward harness, cost model, and Sharpe/Sortino are Phase 8.

> The real-data positive-expectancy *magnitude* claim (ROADMAP §5 exit criterion) is data-gated
> on the 5-year backfill (blocked on a TVKIT token / engine TFEX data) and a cost model. This
> runner is the harness those tests will use; ``scripts/per_strategy_backtest_demo.py`` exercises
> it on a public-safe synthetic proxy.
"""

from __future__ import annotations

from collections.abc import Callable

import polars as pl

from tfex_s50_multi_tf_swing.backtest.metrics import compute_metrics
from tfex_s50_multi_tf_swing.backtest.models import BacktestMetrics
from tfex_s50_multi_tf_swing.execution.engine import simulate_signals
from tfex_s50_multi_tf_swing.execution.models import ExecutionConfig
from tfex_s50_multi_tf_swing.signals.models import SetupSignal, StrategyId

DetectFn = Callable[[pl.DataFrame], list[SetupSignal]]
"""A strategy's detect step: aligned signal-input frame → fired setup signals."""


def run_per_strategy_backtest(
    detect: DetectFn,
    inputs: pl.DataFrame,
    bars: pl.DataFrame,
    *,
    strategy_id: StrategyId,
    config: ExecutionConfig | None = None,
) -> BacktestMetrics:
    """Detect setups on ``inputs``, simulate them over ``bars``, and report the metrics.

    Args:
        detect: maps the aligned signal-input frame to a list of :class:`SetupSignal` (typically
            ``lambda df: strategy_x.to_signals(strategy_x.classify_frame(df, config=...))``).
        inputs: the aligned 5m signal-input frame (see ``signals.build_signal_inputs``).
        bars: the 5m execution frame (``time``/``open``/``high``/``low``/``close``/``atr``).
        strategy_id: which strategy this run is for (recorded on the metrics).
        config: execution knobs (defaults to :class:`ExecutionConfig`).
    """
    signals = detect(inputs)
    trades = simulate_signals(signals, bars, config=config)
    return compute_metrics(trades, strategy_id=strategy_id)


__all__: list[str] = ["DetectFn", "run_per_strategy_backtest"]
