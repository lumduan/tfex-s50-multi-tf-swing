"""End-to-end sim trade loop (Phase 5.1).

Turns a sequence of :class:`~tfex_s50_multi_tf_swing.execution.models.OrderInstruction`
into NormalizedOrders, submits them through the gateway proxy to the Execution engine
SimAdapter, and applies the resulting SSE fill events to a local, evolving
:class:`~tfex_s50_multi_tf_swing.execution.models.SimPosition`.

Loop invariants (per the approved plan; full notes in
``.claude/knowledge/execution-mode.md``): subscribe-before-submit (one stream task
opened, with a bounded connect handshake, before the first POST); sequential against
the evolving position (submit → await terminal → apply → next, so ``position_effect``
reflects each prior fill); single-source fills (positions move only from stream ``fill``
events, never the POST ack); and a ``GET /orders/{cid}`` residual reconcile on per-order
timeout or a degraded (reset) stream.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from tfex_s50_multi_tf_swing.config.settings import Settings
from tfex_s50_multi_tf_swing.execution.engine_adapter import ExecutionEngineAdapter
from tfex_s50_multi_tf_swing.execution.errors import (
    ExecutionModeError,
    OrderRejectedError,
    StreamResetError,
)
from tfex_s50_multi_tf_swing.execution.models import (
    EngineState,
    NormalizedOrder,
    OrderInstruction,
    OrderSide,
    OrderUpdateEvent,
    PositionEffect,
    SimPosition,
    infer_position_effect,
)
from tfex_s50_multi_tf_swing.signals.models import SetupDirection

logger: logging.Logger = logging.getLogger(__name__)

DEFAULT_ORDER_TIMEOUT_SECONDS: float = 30.0
DEFAULT_STREAM_CONNECT_TIMEOUT_SECONDS: float = 10.0


class OrderOutcome(BaseModel):
    """The terminal (or timed-out) outcome of one submitted order."""

    model_config = ConfigDict(frozen=True)

    instruction: OrderInstruction
    client_order_id: str
    position_effect: PositionEffect
    final_state: EngineState | None = None
    filled_qty: int = 0
    avg_fill_price: Decimal | None = None
    rejected: bool = False
    reject_code: str | None = None
    reject_message: str | None = None


class SimLoopResult(BaseModel):
    """Aggregate result of one sim-loop run."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    position: SimPosition | None
    outcomes: list[OrderOutcome]
    skipped: list[str] = []


@dataclass
class _OrderTracker:
    """Per-order mutable state shared between the consumer and awaiter."""

    instruction: OrderInstruction
    position_effect: PositionEffect
    side: OrderSide
    applied_qty: int = 0
    applied_cost: Decimal = Decimal("0")
    final_state: EngineState | None = None
    avg_fill_price: Decimal | None = None
    reject: OrderRejectedError | None = None
    done: asyncio.Event = field(default_factory=asyncio.Event)


def _build_adapter(settings: Settings) -> ExecutionEngineAdapter:
    """Construct an adapter from settings (validation normally guarantees the fields)."""
    if not settings.gateway_base_url:
        raise ExecutionModeError(
            "TFEX_S50_MULTI_TF_SWING_GATEWAY_BASE_URL is required for execution_mode='sim'"
        )
    if not settings.gateway_api_key.get_secret_value():
        raise ExecutionModeError(
            "TFEX_S50_MULTI_TF_SWING_GATEWAY_API_KEY is required for execution_mode='sim'"
        )
    return ExecutionEngineAdapter(
        base_url=settings.gateway_base_url,
        api_key=settings.gateway_api_key.get_secret_value(),
    )


def _side_for(direction: SetupDirection) -> OrderSide:
    """Map a setup direction to an order side (long → BUY, short → SELL)."""
    return "BUY" if direction == "long" else "SELL"


async def run_sim_loop(
    instructions: Sequence[OrderInstruction],
    *,
    settings: Settings,
    position: SimPosition | None = None,
    adapter: ExecutionEngineAdapter | None = None,
    order_timeout_seconds: float = DEFAULT_ORDER_TIMEOUT_SECONDS,
    stream_connect_timeout_seconds: float = DEFAULT_STREAM_CONNECT_TIMEOUT_SECONDS,
) -> SimLoopResult:
    """Run the full instruction → order → fill loop against the engine SimAdapter.

    Instructions are processed **sequentially** against the evolving position so the
    ``position_effect`` of each order reflects every prior fill (an entry-then-exit
    pair in one run exercises OPEN then CLOSE).

    Args:
        instructions: Pre-built per-contract instructions (sizing happens upstream).
        settings: Application settings; ``execution_mode`` must be ``"sim"``.
        position: Optional starting position (defaults to flat / ``None``).
        adapter: Optional injected adapter (defaults to one built from settings).
        order_timeout_seconds: Per-order wait for a terminal state before GET fallback.
        stream_connect_timeout_seconds: Bounded wait for the stream connect
            handshake before the first submit (timeout logs a WARNING and proceeds).

    Raises:
        ExecutionModeError: When ``execution_mode != "sim"``.
        SimLoopError: On an unsupported position flip.
    """
    if settings.execution_mode != "sim":
        raise ExecutionModeError(
            f"run_sim_loop requires TFEX_S50_MULTI_TF_SWING_EXECUTION_MODE='sim', got "
            f"{settings.execution_mode!r} ('off' disables execution; 'live' is not "
            f"implemented in Phase 5.1)"
        )

    owns_adapter = adapter is None
    engine = adapter if adapter is not None else _build_adapter(settings)

    state = _LoopState(position=position, settings=settings)
    connected = asyncio.Event()

    async def _run() -> None:
        async with asyncio.TaskGroup() as tg:
            stream_task = tg.create_task(_consume_stream(engine, state, connected))
            try:
                await asyncio.wait_for(connected.wait(), timeout=stream_connect_timeout_seconds)
            except TimeoutError:
                logger.warning(
                    "stream not connected after %.1fs — submitting anyway "
                    "(GET-residual reconcile still guarantees correctness)",
                    stream_connect_timeout_seconds,
                )
            for instruction in instructions:
                await _process_one(engine, instruction, state, order_timeout_seconds)
            stream_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stream_task

    if owns_adapter:
        async with engine:
            await _run()
    else:
        await _run()

    return SimLoopResult(position=state.position, outcomes=state.outcomes)


class _LoopState:
    """Mutable loop state: the evolving position, per-cid trackers, outcomes, degraded flag.

    The stream consumer reads ``trackers`` by client_order_id and flips ``degraded`` on a
    reset; the per-order driver appends to ``outcomes`` and rolls ``position`` forward.
    """

    def __init__(self, *, position: SimPosition | None, settings: Settings) -> None:
        self.position: SimPosition | None = position
        self.settings: Settings = settings
        self.trackers: dict[str, _OrderTracker] = {}
        self.outcomes: list[OrderOutcome] = []
        self.degraded: bool = False


async def _process_one(
    engine: ExecutionEngineAdapter,
    instruction: OrderInstruction,
    state: _LoopState,
    order_timeout_seconds: float,
) -> None:
    """Submit one instruction, await terminal (or reconcile), then roll the position."""
    effect = infer_position_effect(state.position, instruction.direction, instruction.contracts)
    side = _side_for(instruction.direction)
    cid = str(uuid.uuid4())
    tracker = _OrderTracker(instruction=instruction, position_effect=effect, side=side)
    state.trackers[cid] = tracker

    order = NormalizedOrder(
        client_order_id=cid,
        broker="sim",
        account=state.settings.execution_account or "",
        symbol=instruction.symbol,
        side=side,
        order_type="LIMIT",
        price=instruction.limit_price,
        quantity=instruction.contracts,
        position_effect=effect,
        tif="DAY",
    )

    try:
        await engine.submit_order(order)
    except OrderRejectedError as exc:
        logger.warning("order rejected cid=%s code=%s: %s", cid, exc.code, exc.message)
        tracker.final_state = "REJECTED"
        tracker.reject = exc
        tracker.done.set()
    # The ack never moves the position — fills arrive only via the stream.

    await _await_terminal(engine, cid, tracker, state, order_timeout_seconds)
    state.outcomes.append(_build_outcome(cid, tracker))


async def _consume_stream(
    engine: ExecutionEngineAdapter,
    state: _LoopState,
    connected: asyncio.Event,
) -> None:
    """Apply fill events to known orders; mark degraded and return on a stream reset."""
    try:
        async for event in engine.stream_updates(connected=connected):
            tracker = state.trackers.get(event.client_order_id)
            if tracker is None:
                continue  # not one of ours
            _apply_event(event, tracker, state)
    except StreamResetError as exc:
        logger.warning("stream reset (after_seq=%d) — degrading to GET polling", exc.after_seq)
        state.degraded = True


def _apply_event(event: OrderUpdateEvent, tracker: _OrderTracker, state: _LoopState) -> None:
    """Apply one order-update event's fill and terminal state to a tracker.

    ``avg_fill_price`` is the quantity-weighted average of the *applied fills*
    (``applied_cost / applied_qty``) — never the event's top-level ``price``
    field, which on the wire is the replace/amend price, not an average.
    """
    if event.fill is not None:
        state.position = _apply_fill(
            state.position,
            tracker.instruction.direction,
            tracker.position_effect,
            event.fill.quantity,
            event.fill.price,
        )
        tracker.applied_qty += event.fill.quantity
        tracker.applied_cost += event.fill.price * event.fill.quantity
    if event.is_terminal:
        tracker.final_state = event.engine_state
        if tracker.applied_qty > 0:
            tracker.avg_fill_price = tracker.applied_cost / tracker.applied_qty
        tracker.done.set()


def _apply_fill(
    position: SimPosition | None,
    direction: SetupDirection,
    effect: PositionEffect,
    contracts: int,
    price: Decimal,
) -> SimPosition | None:
    """Roll the evolving position forward by one fill.

    OPEN raises the weighted-average entry and contract count (on the order's
    direction). CLOSE reduces the held contract count (average unchanged); when the
    count reaches zero the position becomes flat (``None``).
    """
    if effect == "OPEN":
        if position is None or position.contracts == 0:
            return SimPosition(direction=direction, contracts=contracts, avg_entry=price)
        new_qty = position.contracts + contracts
        total_cost = position.avg_entry * position.contracts + price * contracts
        return SimPosition(
            direction=position.direction,
            contracts=new_qty,
            avg_entry=total_cost / new_qty,
        )
    # CLOSE — reduce the held position; flat → None.
    held = position.contracts if position is not None else 0
    new_qty = held - contracts
    if new_qty <= 0 or position is None:
        return None
    return SimPosition(
        direction=position.direction,
        contracts=new_qty,
        avg_entry=position.avg_entry,
    )


async def _await_terminal(
    engine: ExecutionEngineAdapter,
    cid: str,
    tracker: _OrderTracker,
    state: _LoopState,
    order_timeout_seconds: float,
) -> None:
    """Wait for one order to terminate; reconcile via GET on timeout / degraded stream."""
    if tracker.done.is_set():
        return
    if not state.degraded:
        try:
            async with asyncio.timeout(order_timeout_seconds):
                await tracker.done.wait()
            return
        except TimeoutError:
            logger.warning("order cid=%s timed out after %.1fs", cid, order_timeout_seconds)
    await _reconcile_via_get(engine, cid, tracker, state)


async def _reconcile_via_get(
    engine: ExecutionEngineAdapter,
    cid: str,
    tracker: _OrderTracker,
    state: _LoopState,
) -> None:
    """GET the order and apply the residual (filled_qty − applied_qty) if terminal."""
    result = await engine.get_order(cid)
    if result.is_terminal:
        residual = result.filled_qty - tracker.applied_qty
        if residual > 0 and result.avg_fill_price is not None:
            state.position = _apply_fill(
                state.position,
                tracker.instruction.direction,
                tracker.position_effect,
                residual,
                result.avg_fill_price,
            )
            tracker.applied_qty += residual
            tracker.applied_cost += result.avg_fill_price * residual
        tracker.final_state = result.engine_state
        if result.avg_fill_price is not None:
            # Engine truth preferred over the locally-accumulated average.
            tracker.avg_fill_price = result.avg_fill_price
        tracker.done.set()
    else:
        logger.warning(
            "order cid=%s still non-terminal after GET (state=%s) — recording timeout",
            cid,
            result.engine_state,
        )
        tracker.final_state = None


def _build_outcome(cid: str, tracker: _OrderTracker) -> OrderOutcome:
    """Materialize an OrderOutcome from a tracker's final state."""
    if tracker.reject is not None:
        return OrderOutcome(
            instruction=tracker.instruction,
            client_order_id=cid,
            position_effect=tracker.position_effect,
            final_state="REJECTED",
            filled_qty=tracker.applied_qty,
            avg_fill_price=tracker.avg_fill_price,
            rejected=True,
            reject_code=tracker.reject.code,
            reject_message=tracker.reject.message,
        )
    return OrderOutcome(
        instruction=tracker.instruction,
        client_order_id=cid,
        position_effect=tracker.position_effect,
        final_state=tracker.final_state,
        filled_qty=tracker.applied_qty,
        avg_fill_price=tracker.avg_fill_price,
    )


__all__: list[str] = [
    "DEFAULT_ORDER_TIMEOUT_SECONDS",
    "DEFAULT_STREAM_CONNECT_TIMEOUT_SECONDS",
    "OrderOutcome",
    "SimLoopResult",
    "run_sim_loop",
]
