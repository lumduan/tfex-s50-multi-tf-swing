"""Unit tests for the Phase 5.1 wire mirrors + sim-loop value objects (execution.models)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from tfex_s50_multi_tf_swing.execution.errors import SimLoopError
from tfex_s50_multi_tf_swing.execution.models import (
    TERMINAL_STATES,
    FillEvent,
    NormalizedOrder,
    NormalizedOrderResult,
    OrderInstruction,
    OrderUpdateEvent,
    SimPosition,
    build_order_instruction,
    infer_position_effect,
)
from tfex_s50_multi_tf_swing.signals.models import SetupSignal

_TS = datetime(2026, 6, 12, 9, 0, tzinfo=UTC)


def _order(**overrides: object) -> NormalizedOrder:
    base: dict[str, object] = {
        "client_order_id": "cid-1",
        "broker": "sim",
        "account": "SIM-1",
        "symbol": "S50Z2026",
        "side": "BUY",
        "price": Decimal("970.5"),
        "quantity": 1,
        "position_effect": "OPEN",
    }
    base.update(overrides)
    return NormalizedOrder(**base)  # type: ignore[arg-type]


class TestNormalizedOrder:
    def test_price_serialized_as_plain_string(self) -> None:
        body = _order(price=Decimal("970.50")).wire_dump()
        assert body["price"] == "970.50"
        assert isinstance(body["price"], str)

    def test_no_scientific_notation_for_tiny_price(self) -> None:
        body = _order(price=Decimal("0.0001")).wire_dump()
        assert body["price"] == "0.0001"
        assert "E" not in body["price"] and "e" not in body["price"]

    def test_wire_dump_carries_market_and_position_effect(self) -> None:
        body = _order(price=Decimal("970")).wire_dump()
        assert body["market"] == "TFEX"
        assert body["position_effect"] == "OPEN"
        assert "stop_price" not in body  # None dropped

    def test_wire_dump_close_effect(self) -> None:
        body = _order(side="SELL", position_effect="CLOSE").wire_dump()
        assert body["position_effect"] == "CLOSE"

    def test_wire_dump_is_json_serializable(self) -> None:
        # exclude_none + mode=json means no Decimal leaks through.
        json.dumps(_order().wire_dump())

    def test_position_effect_required(self) -> None:
        # A NormalizedOrder built without position_effect must fail validation (TFEX delta).
        fields: dict[str, object] = {
            "client_order_id": "cid-1",
            "broker": "sim",
            "account": "SIM-1",
            "symbol": "S50Z2026",
            "side": "BUY",
            "price": Decimal("970"),
            "quantity": 1,
        }
        with pytest.raises(ValidationError):
            NormalizedOrder.model_validate(fields)

    def test_market_pinned_to_tfex(self) -> None:
        with pytest.raises(ValidationError):
            _order(market="SET")

    def test_quantity_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            _order(quantity=0)

    def test_account_min_length(self) -> None:
        with pytest.raises(ValidationError):
            _order(account="")

    def test_is_frozen(self) -> None:
        order = _order()
        with pytest.raises(ValidationError):
            order.quantity = 5


class TestNormalizedOrderResult:
    def test_parses_avg_fill_price_string(self) -> None:
        result = NormalizedOrderResult.model_validate(
            {
                "client_order_id": "cid-1",
                "broker": "sim",
                "status": "FILLED",
                "engine_state": "FILLED",
                "filled_qty": 1,
                "remaining_qty": 0,
                "avg_fill_price": "970.55",
                "created_at": _TS.isoformat(),
                "updated_at": _TS.isoformat(),
            }
        )
        assert result.avg_fill_price == Decimal("970.55")
        assert result.is_terminal is True

    def test_numeric_string_broker_order_id_stays_str(self) -> None:
        # TFEX (Settrade) order_no can arrive as a numeric string; it must stay str.
        result = NormalizedOrderResult.model_validate(
            {
                "client_order_id": "cid-1",
                "broker_order_id": "123456789",
                "broker": "sim",
                "status": "FILLED",
                "engine_state": "FILLED",
                "filled_qty": 1,
                "remaining_qty": 0,
                "avg_fill_price": "970.55",
                "created_at": _TS.isoformat(),
                "updated_at": _TS.isoformat(),
            }
        )
        assert result.broker_order_id == "123456789"
        assert isinstance(result.broker_order_id, str)

    def test_non_terminal_state(self) -> None:
        result = NormalizedOrderResult.model_validate(
            {
                "client_order_id": "cid-1",
                "broker": "sim",
                "status": "PARTIALLY_FILLED",
                "engine_state": "PARTIALLY_FILLED",
                "filled_qty": 1,
                "remaining_qty": 1,
                "avg_fill_price": "970.55",
                "created_at": _TS.isoformat(),
                "updated_at": _TS.isoformat(),
            }
        )
        assert result.is_terminal is False


class TestOrderUpdateEvent:
    def test_parses_fill_and_terminal(self) -> None:
        event = OrderUpdateEvent.model_validate_json(
            json.dumps(
                {
                    "seq": 7,
                    "client_order_id": "cid-1",
                    "strategy_id": "tfex-s50-multi-tf-swing",
                    "engine_state": "FILLED",
                    "status": "FILLED",
                    "broker_order_id": "987654321",
                    "price": "970.50",
                    "quantity": 1,
                    "fill": {
                        "broker_fill_id": "F-1",
                        "price": "970.55",
                        "quantity": 1,
                        "exec_ts": _TS.isoformat(),
                    },
                    "ts": _TS.isoformat(),
                }
            )
        )
        assert event.seq == 7
        assert event.is_terminal is True
        assert event.fill is not None
        assert event.fill.price == Decimal("970.55")
        assert isinstance(event.fill, FillEvent)
        assert event.broker_order_id == "987654321"
        assert isinstance(event.broker_order_id, str)

    def test_non_terminal_partial(self) -> None:
        event = OrderUpdateEvent.model_validate_json(
            json.dumps(
                {
                    "seq": 3,
                    "client_order_id": "cid-1",
                    "engine_state": "PARTIALLY_FILLED",
                    "status": "PARTIALLY_FILLED",
                    "ts": _TS.isoformat(),
                }
            )
        )
        assert event.is_terminal is False
        assert event.fill is None
        assert event.strategy_id is None


class TestTerminalStates:
    def test_membership(self) -> None:
        assert frozenset({"FILLED", "CANCELLED", "REJECTED", "EXPIRED"}) == TERMINAL_STATES


class TestOrderInstruction:
    def test_requires_positive_contracts_and_price(self) -> None:
        with pytest.raises(ValidationError):
            OrderInstruction(
                symbol="S50Z2026", direction="long", contracts=0, limit_price=Decimal("1")
            )
        with pytest.raises(ValidationError):
            OrderInstruction(
                symbol="S50Z2026", direction="long", contracts=1, limit_price=Decimal("0")
            )

    def test_is_frozen(self) -> None:
        ins = OrderInstruction(
            symbol="S50Z2026", direction="long", contracts=1, limit_price=Decimal("970")
        )
        with pytest.raises(ValidationError):
            ins.contracts = 2


class TestInferPositionEffect:
    def test_no_position_opens(self) -> None:
        assert infer_position_effect(None, "long", 1) == "OPEN"

    def test_zero_contract_position_opens(self) -> None:
        flat = SimPosition(direction="long", contracts=0, avg_entry=Decimal("0"))
        assert infer_position_effect(flat, "short", 1) == "OPEN"

    def test_same_direction_opens(self) -> None:
        pos = SimPosition(direction="long", contracts=2, avg_entry=Decimal("970"))
        assert infer_position_effect(pos, "long", 1) == "OPEN"

    def test_opposite_within_size_closes(self) -> None:
        pos = SimPosition(direction="long", contracts=2, avg_entry=Decimal("970"))
        assert infer_position_effect(pos, "short", 2) == "CLOSE"
        assert infer_position_effect(pos, "short", 1) == "CLOSE"

    def test_opposite_oversize_flip_raises(self) -> None:
        pos = SimPosition(direction="long", contracts=2, avg_entry=Decimal("970"))
        with pytest.raises(SimLoopError, match="flip"):
            infer_position_effect(pos, "short", 3)


class TestBuildOrderInstruction:
    def test_builds_from_signal(self) -> None:
        signal = SetupSignal(
            strategy_id="B",
            time=_TS,
            direction="long",
            trigger_price=Decimal("970.5"),
            stop_reference=Decimal("960.0"),
        )
        ins = build_order_instruction(signal, 2, symbol="S50Z2026")
        assert ins.symbol == "S50Z2026"
        assert ins.direction == "long"
        assert ins.contracts == 2
        assert ins.limit_price == Decimal("970.5")

    def test_short_signal_direction(self) -> None:
        signal = SetupSignal(
            strategy_id="B",
            time=_TS,
            direction="short",
            trigger_price=Decimal("955.0"),
            stop_reference=Decimal("965.0"),
        )
        ins = build_order_instruction(signal, 1, symbol="S50Z2026")
        assert ins.direction == "short"
        assert ins.limit_price == Decimal("955.0")
