"""Execution layer (ROADMAP Phase 5 — §5.4).

The 5m execution engine simulates a trade from a setup signal (``signals.SetupSignal``):
next-bar-open entry, a structure-and-volatility-aware stop, a hybrid partial-TP + trailing exit,
breakeven, and a time stop. Pure offline library code — one-way dependency
``signals/ → execution/``; nothing here builds ``risk/`` (Phase 7) or applies a cost model
(Phase 8). PnL is reported in points + R-multiples.
"""

from __future__ import annotations

from tfex_s50_multi_tf_swing.execution.engine import simulate_signals, simulate_trade
from tfex_s50_multi_tf_swing.execution.errors import ExecutionError, ExecutionInputError
from tfex_s50_multi_tf_swing.execution.models import (
    EXIT_REASONS,
    ExecutionConfig,
    ExitReason,
    Trade,
)

__all__: list[str] = [
    "EXIT_REASONS",
    "ExecutionConfig",
    "ExecutionError",
    "ExecutionInputError",
    "ExitReason",
    "Trade",
    "simulate_signals",
    "simulate_trade",
]
