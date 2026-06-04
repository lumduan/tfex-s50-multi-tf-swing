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

SignalFilter = Callable[[list[SetupSignal], pl.DataFrame], list[SetupSignal]]
"""An optional Phase-6 gate: ``(signals, aligned_inputs) → kept subset`` (order-preserving).

Bind the ML config + loaded model into a closure / ``functools.partial`` over
:func:`tfex_s50_multi_tf_swing.ml.filter.filter_signals` at the call site. ``None`` (the
default) means *no filter* — the backtest is byte-for-byte the Phase-5 behaviour."""


def run_per_strategy_backtest(
    detect: DetectFn,
    inputs: pl.DataFrame,
    bars: pl.DataFrame,
    *,
    strategy_id: StrategyId,
    config: ExecutionConfig | None = None,
    ml_filter: SignalFilter | None = None,
) -> BacktestMetrics:
    """Detect setups on ``inputs``, optionally ML-gate them, simulate, and report the metrics.

    Args:
        detect: maps the aligned signal-input frame to a list of :class:`SetupSignal` (typically
            ``lambda df: strategy_x.to_signals(strategy_x.classify_frame(df, config=...))``).
        inputs: the aligned 5m signal-input frame (see ``signals.build_signal_inputs``).
        bars: the 5m execution frame (``time``/``open``/``high``/``low``/``close``/``atr``).
        strategy_id: which strategy this run is for (recorded on the metrics).
        config: execution knobs (defaults to :class:`ExecutionConfig`).
        ml_filter: optional Phase-6 probability gate applied to the detected signals before
            simulation. ``None`` (the default) is a no-op — the result is identical to Phase 5.
    """
    signals = detect(inputs)
    if ml_filter is not None:
        signals = ml_filter(signals, inputs)
    trades = simulate_signals(signals, bars, config=config)
    return compute_metrics(trades, strategy_id=strategy_id)


__all__: list[str] = ["DetectFn", "SignalFilter", "run_per_strategy_backtest"]
