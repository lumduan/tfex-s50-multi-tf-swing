"""Type contracts for the 5m execution engine (ROADMAP §5.4).

* :data:`ExitReason` — how a simulated trade closed.
* :class:`ExecutionConfig` — the entry / stop / take-profit / breakeven / time-stop knobs, frozen
  and bounded so an out-of-range env override fails at load (mirrors the other config models).
* :class:`Trade` — one fully-simulated trade. Prices and PnL are **Decimal** (money). PnL is
  expressed in **points** and **R-multiples** only — the THB conversion (the 200-THB/point S50
  multiplier) belongs to the Phase-7 risk engine and the cost model to Phase-8, both out of scope
  here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from tfex_s50_multi_tf_swing.execution.errors import SimLoopError
from tfex_s50_multi_tf_swing.regime.models import Regime
from tfex_s50_multi_tf_swing.signals.models import SetupDirection, SetupSignal, StrategyId

ExitReason = Literal[
    "take_profit",
    "stop_loss",
    "trailing_stop",
    "time_stop",
    "end_of_data",
]
"""How a simulated trade closed its (remaining) position."""

EXIT_REASONS: tuple[ExitReason, ...] = get_args(ExitReason)
"""Tuple of every :data:`ExitReason`, for iteration / parametrised tests."""


class ExecutionConfig(BaseModel):
    """Entry / exit / management knobs for :func:`simulate_trade`.

    ``k_atr_stop`` widens the structure stop to at least ``k·ATR`` from entry (noise buffer); the
    default is **2.0** (widened from 1.5 as a risk mitigation — a wider stop reduces noise /
    stop-hunt exits, and sizing shrinks proportionally so the per-trade risk budget is unchanged).
    At ``partial_tp_r`` (1R) the engine banks ``partial_fraction`` (50 %) and moves the stop to
    breakeven (entry ± ``breakeven_buffer``); the remainder trails ``trail_atr_mult·ATR`` behind
    the best close. ``time_stop_bars`` forces an exit if no target is reached; ``max_spread_mult``
    rejects an entry whose bar range exceeds ``mult × median`` (a spread proxy).
    """

    model_config = ConfigDict(frozen=True)

    k_atr_stop: float = Field(default=2.0, gt=0.0)
    partial_tp_r: float = Field(default=1.0, gt=0.0)
    partial_fraction: float = Field(default=0.5, ge=0.0, le=1.0)
    breakeven_buffer: float = Field(default=0.0, ge=0.0)
    trail_atr_mult: float = Field(default=1.5, gt=0.0)
    time_stop_bars: int = Field(default=8, ge=1)
    max_spread_mult: float = Field(default=3.0, gt=0.0)


class Trade(BaseModel):
    """One fully-simulated trade (partial + remainder folded into ``pnl_points``)."""

    model_config = ConfigDict(frozen=True)

    strategy_id: StrategyId
    direction: SetupDirection
    entry_time: datetime
    exit_time: datetime
    entry: Decimal
    stop: Decimal
    exit_price: Decimal
    pnl_points: Decimal
    r_multiple: Decimal
    bars_held: int = Field(ge=0)
    exit_reason: ExitReason
    regime: Regime | None = None

    @field_validator("entry_time", "exit_time")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(None):
            raise ValueError("trade timestamps must be UTC-aware")
        return value


# ============================================================================
# Phase 5.1 — engine wire mirrors + sim-loop value objects
# ============================================================================
#
# Local Pydantic mirrors of the ``quant-execution-engine`` order contract, close
# enough to (de)serialize requests and SSE events but **deliberately independent**
# — tfex never imports across the repo boundary. This mirror is TFEX-only: every
# order pins ``market`` to ``"TFEX"`` and carries a **required** ``position_effect``
# (the engine rejects a TFEX order without one), so ``wire_dump`` always emits it.
#
# Wire rules:
#   - Money is ``Decimal`` end-to-end. ``WireDecimal`` serializes to a plain
#     (non-scientific) string on the JSON wire; the engine rejects floats.
#   - ``NormalizedOrder.wire_dump`` uses ``exclude_none=True`` so null prices are
#     dropped, but ``market`` and ``position_effect`` (never None) always survive.
#
# Also defined here are the small sim-loop value objects (``OrderInstruction``,
# ``SimPosition``) and the helpers (``infer_position_effect``,
# ``build_order_instruction``) that have no engine counterpart.

BrokerName = Literal["sim", "liberator", "settrade"]
OrderSide = Literal["BUY", "SELL"]
OrderTypeName = Literal["MARKET", "LIMIT", "STOP", "STOP_LIMIT", "ICEBERG", "MTL", "ATO", "ATC"]
TifName = Literal["DAY", "IOC", "FOK", "GTC"]
PositionEffect = Literal["OPEN", "CLOSE"]
EngineState = Literal[
    "PENDING_NEW",
    "NEW",
    "PARTIALLY_FILLED",
    "FILLED",
    "PENDING_CANCEL",
    "PENDING_REPLACE",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
]
PublicStatus = Literal[
    "NEW",
    "PARTIALLY_FILLED",
    "FILLED",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
]

TERMINAL_STATES: frozenset[str] = frozenset({"FILLED", "CANCELLED", "REJECTED", "EXPIRED"})

# Decimal-as-string on the JSON wire (no scientific notation, never float).
WireDecimal = Annotated[
    Decimal,
    PlainSerializer(lambda d: format(d, "f"), return_type=str, when_used="json"),
]


class NormalizedOrder(BaseModel):
    """TFEX-only mirror of the engine ``NormalizedOrder`` request body.

    ``market`` is pinned to ``"TFEX"`` and ``position_effect`` is **required** (no
    default) — the engine rejects TFEX orders without it, so it is never sent as
    ``None``. ``wire_dump`` drops all ``None`` fields (null prices) but always
    emits ``market`` and ``position_effect``.
    """

    model_config = ConfigDict(frozen=True)

    client_order_id: str = Field(description="Caller-generated UUIDv4 order id.")
    broker: BrokerName = Field(description="Target broker.")
    account: str = Field(min_length=1, description="Broker account identifier.")
    market: Literal["TFEX"] = Field(default="TFEX", description="Always TFEX for this strategy.")
    symbol: str = Field(min_length=1, description="Dated TFEX contract, e.g. S50Z2026.")
    side: OrderSide = Field(description="Order side (BUY for long, SELL for short).")
    order_type: OrderTypeName = Field(default="LIMIT", description="Order type.")
    price: WireDecimal | None = Field(default=None, description="Limit price (Decimal).")
    stop_price: WireDecimal | None = Field(default=None, description="Stop trigger price.")
    quantity: int = Field(gt=0, description="Order quantity in contracts.")
    position_effect: PositionEffect = Field(
        description="OPEN or CLOSE — required for TFEX; the engine rejects an order without it."
    )
    tif: TifName = Field(default="DAY", description="Time in force.")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Opaque metadata.")

    def wire_dump(self) -> dict[str, Any]:
        """Return the JSON-ready request body with all ``None`` fields removed.

        ``market`` and ``position_effect`` are never ``None``, so they always survive.
        """
        return self.model_dump(mode="json", exclude_none=True)


class NormalizedOrderResult(BaseModel):
    """Mirror of the engine order result (POST ack / GET response body)."""

    model_config = ConfigDict(frozen=True)

    client_order_id: str
    broker_order_id: str | None = None
    broker: str
    status: PublicStatus
    engine_state: EngineState
    filled_qty: int = 0
    remaining_qty: int = 0
    avg_fill_price: Decimal | None = None
    reject_reason: str | None = None
    created_at: datetime
    updated_at: datetime

    @property
    def is_terminal(self) -> bool:
        """True when the order has reached a terminal engine state."""
        return self.engine_state in TERMINAL_STATES


class FillEvent(BaseModel):
    """A single execution (fill) embedded in an order-update event."""

    model_config = ConfigDict(frozen=True)

    broker_fill_id: str
    price: Decimal
    quantity: int
    exec_ts: datetime


class OrderUpdateEvent(BaseModel):
    """Mirror of the SSE ``OrderUpdateEvent`` payload (the ``data:`` field)."""

    model_config = ConfigDict(frozen=True)

    seq: int
    client_order_id: str
    strategy_id: str | None = None
    engine_state: EngineState
    status: PublicStatus
    broker_order_id: str | None = None
    price: Decimal | None = None
    quantity: int | None = None
    fill: FillEvent | None = None
    ts: datetime

    @property
    def is_terminal(self) -> bool:
        """True when this event marks the order terminal."""
        return self.engine_state in TERMINAL_STATES


# --- Sim-loop value objects (no engine counterpart) -------------------------


class OrderInstruction(BaseModel):
    """A resolved per-contract order intent prior to NormalizedOrder construction."""

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1, description="Dated TFEX contract, e.g. S50Z2026.")
    direction: SetupDirection = Field(description="long (→ BUY) or short (→ SELL).")
    contracts: int = Field(gt=0, description="Number of S50 contracts (whole contracts).")
    limit_price: Decimal = Field(gt=0, description="Limit price (Decimal).")


class SimPosition(BaseModel):
    """A single simulated directional position in S50 contracts.

    The S50 book is single-direction at a time: ``direction`` is the held side,
    ``contracts`` the open quantity (``0`` means flat — but the loop represents a
    flat book as ``None`` rather than a zero-contract position), and ``avg_entry``
    the weighted-average entry price.
    """

    model_config = ConfigDict(frozen=True)

    direction: SetupDirection
    contracts: int = Field(default=0, ge=0)
    avg_entry: Decimal = Decimal("0")


def infer_position_effect(
    position: SimPosition | None,
    direction: SetupDirection,
    contracts: int,
) -> PositionEffect:
    """Infer OPEN vs CLOSE for a TFEX order against the current position.

    Rules (Phase 5.1 — single-direction book, no flip):

    - No position, or the order is the **same** direction as the held position → ``OPEN``.
    - **Opposite** direction with ``contracts <= position.contracts`` → ``CLOSE``.
    - **Opposite** direction with ``contracts > position.contracts`` → a flip, which is
      **unsupported** in Phase 5.1 → :class:`SimLoopError`.

    Raises:
        SimLoopError: On an oversize opposite-direction order (a position flip).
    """
    if position is None or position.contracts == 0 or direction == position.direction:
        return "OPEN"
    # Opposite direction against a held position → closing (or attempting a flip).
    if contracts <= position.contracts:
        return "CLOSE"
    raise SimLoopError(
        f"position flip is unsupported in Phase 5.1: a {direction} order for {contracts} "
        f"contract(s) would oversize the held {position.direction} position of "
        f"{position.contracts} contract(s)"
    )


def build_order_instruction(
    signal: SetupSignal, contracts: int, *, symbol: str
) -> OrderInstruction:
    """Build an :class:`OrderInstruction` from a fired setup + a sized contract count.

    The loop does **not** size — ``contracts`` comes from the risk engine's
    ``PositionSizeResult`` upstream. The direction is the signal's direction and the
    limit price is the signal's ``trigger_price`` (already Decimal).

    Args:
        signal: The fired setup (``direction`` + ``trigger_price`` are read).
        contracts: The sized whole-contract count (must be > 0).
        symbol: The dated TFEX contract to route, e.g. ``S50Z2026``.
    """
    return OrderInstruction(
        symbol=symbol,
        direction=signal.direction,
        contracts=contracts,
        limit_price=signal.trigger_price,
    )


__all__: list[str] = [
    "EXIT_REASONS",
    "TERMINAL_STATES",
    "BrokerName",
    "EngineState",
    "ExecutionConfig",
    "ExitReason",
    "FillEvent",
    "NormalizedOrder",
    "NormalizedOrderResult",
    "OrderInstruction",
    "OrderSide",
    "OrderTypeName",
    "OrderUpdateEvent",
    "PositionEffect",
    "PublicStatus",
    "SimPosition",
    "TifName",
    "Trade",
    "WireDecimal",
    "build_order_instruction",
    "infer_position_effect",
]
