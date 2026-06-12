"""Execution layer (ROADMAP Phase 5 — §5.4; Phase 5.1 — sim trade loop).

The 5m execution engine simulates a trade from a setup signal (``signals.SetupSignal``):
next-bar-open entry, a structure-and-volatility-aware stop, a hybrid partial-TP + trailing exit,
breakeven, and a time stop. Pure offline library code — one-way dependency
``signals/ → execution/``; nothing here builds ``risk/`` (Phase 7) or applies a cost model
(Phase 8). PnL is reported in points + R-multiples.

Phase 5.1 adds an opt-in, **library-only** sim trade loop (feature-execution-engine): an
``ExecutionEngineAdapter`` (HTTP/SSE client for the gateway-proxied Execution engine), the
local wire mirrors (``NormalizedOrder`` etc.), and ``run_sim_loop`` (instruction →
NormalizedOrder → POST /orders → SSE fill events → local ``SimPosition``). No broker code
lives here; the Execution engine is the sole order-routing-credential owner.
"""

from __future__ import annotations

from tfex_s50_multi_tf_swing.execution.engine import simulate_signals, simulate_trade
from tfex_s50_multi_tf_swing.execution.engine_adapter import (
    EXECUTION_ORDERS_PATH,
    EXECUTION_STREAM_PATH,
    STRATEGY_ID,
    ExecutionEngineAdapter,
)
from tfex_s50_multi_tf_swing.execution.errors import (
    EngineAdapterError,
    ExecutionError,
    ExecutionInputError,
    ExecutionModeError,
    OrderRejectedError,
    OrderTimeoutError,
    SimLoopError,
    StreamError,
    StreamResetError,
)
from tfex_s50_multi_tf_swing.execution.models import (
    EXIT_REASONS,
    TERMINAL_STATES,
    ExecutionConfig,
    ExitReason,
    FillEvent,
    NormalizedOrder,
    NormalizedOrderResult,
    OrderInstruction,
    OrderUpdateEvent,
    SimPosition,
    Trade,
    build_order_instruction,
    infer_position_effect,
)
from tfex_s50_multi_tf_swing.execution.sim_loop import (
    OrderOutcome,
    SimLoopResult,
    run_sim_loop,
)

__all__: list[str] = [
    "EXECUTION_ORDERS_PATH",
    "EXECUTION_STREAM_PATH",
    "EXIT_REASONS",
    "STRATEGY_ID",
    "TERMINAL_STATES",
    "EngineAdapterError",
    "ExecutionConfig",
    "ExecutionEngineAdapter",
    "ExecutionError",
    "ExecutionInputError",
    "ExecutionModeError",
    "ExitReason",
    "FillEvent",
    "NormalizedOrder",
    "NormalizedOrderResult",
    "OrderInstruction",
    "OrderOutcome",
    "OrderRejectedError",
    "OrderTimeoutError",
    "OrderUpdateEvent",
    "SimLoopError",
    "SimLoopResult",
    "SimPosition",
    "StreamError",
    "StreamResetError",
    "Trade",
    "build_order_instruction",
    "infer_position_effect",
    "run_sim_loop",
    "simulate_signals",
    "simulate_trade",
]
