"""Unit tests for :mod:`tfex_s50_multi_tf_swing.execution.engine_adapter` (Phase 5.1)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

from tfex_s50_multi_tf_swing.execution.engine_adapter import (
    EXECUTION_ORDERS_PATH,
    EXECUTION_STREAM_PATH,
    STRATEGY_ID,
    ExecutionEngineAdapter,
)
from tfex_s50_multi_tf_swing.execution.errors import (
    EngineAdapterError,
    OrderRejectedError,
    StreamError,
    StreamResetError,
)
from tfex_s50_multi_tf_swing.execution.models import NormalizedOrder

BASE_URL = "http://gateway.test"
API_KEY = "secret-test-key"
_TS = datetime(2026, 6, 12, 9, 0, tzinfo=UTC).isoformat()


def _order(cid: str = "cid-1") -> NormalizedOrder:
    return NormalizedOrder(
        client_order_id=cid,
        broker="sim",
        account="SIM-1",
        symbol="S50Z2026",
        side="BUY",
        price=Decimal("970.5"),
        quantity=1,
        position_effect="OPEN",
    )


def _result_body(cid: str = "cid-1", state: str = "FILLED") -> dict[str, Any]:
    return {
        "client_order_id": cid,
        "broker_order_id": "123456789",
        "broker": "sim",
        "status": state,
        "engine_state": state,
        "filled_qty": 1,
        "remaining_qty": 0,
        "avg_fill_price": "970.55",
        "created_at": _TS,
        "updated_at": _TS,
    }


def _envelope(code: str, message: str, cid: str | None = "cid-1") -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if cid is not None:
        err["client_order_id"] = cid
    return {"error": err}


def _sse(*frames: str) -> bytes:
    """Join SSE frames (each already ending without trailing blank line) into a body."""
    return ("".join(f + "\n\n" for f in frames)).encode()


# Engine-true mapping (quant-execution-engine ``to_public_status``):
# PENDING_NEW surfaces as NEW; every other state maps onto itself.
_PUBLIC_STATUS = {
    "PENDING_NEW": "NEW",
    "NEW": "NEW",
    "PARTIALLY_FILLED": "PARTIALLY_FILLED",
    "FILLED": "FILLED",
    "CANCELLED": "CANCELLED",
    "REJECTED": "REJECTED",
    "EXPIRED": "EXPIRED",
}


def _event_frame(
    seq: int, state: str, *, fill_qty: int | None = None, fill_price: str = "970.55"
) -> str:
    data: dict[str, Any] = {
        "seq": seq,
        "client_order_id": "cid-1",
        "strategy_id": STRATEGY_ID,
        "engine_state": state,
        "status": _PUBLIC_STATUS[state],
        "ts": _TS,
    }
    if fill_qty is not None:
        data["fill"] = {
            "broker_fill_id": f"F-{seq}",
            "price": fill_price,
            "quantity": fill_qty,
            "exec_ts": _TS,
        }
    return f"id: {seq}\nevent: {state}\ndata: {json.dumps(data)}"


class _Sequencer:
    """MockTransport handler that pops a queued response per call and records requests."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self._responses:
            raise AssertionError("unexpected extra request")
        return self._responses.pop(0)


# --- submit_order ------------------------------------------------------------


class TestSubmitOrder:
    @pytest.mark.asyncio
    async def test_201_accept(self) -> None:
        seq = _Sequencer([httpx.Response(201, json=_result_body())])
        async with ExecutionEngineAdapter(
            base_url=BASE_URL, api_key=API_KEY, transport=httpx.MockTransport(seq)
        ) as adapter:
            result = await adapter.submit_order(_order())
        assert result.engine_state == "FILLED"
        assert result.avg_fill_price == Decimal("970.55")
        assert result.broker_order_id == "123456789"
        req = seq.requests[0]
        assert req.url.path == EXECUTION_ORDERS_PATH
        assert req.headers["X-API-Key"] == API_KEY
        assert req.headers["X-Strategy-Id"] == STRATEGY_ID
        body = json.loads(req.content)
        assert body["market"] == "TFEX"
        assert body["position_effect"] == "OPEN"

    @pytest.mark.asyncio
    async def test_200_idempotent_resend_same_handling(self) -> None:
        seq = _Sequencer([httpx.Response(200, json=_result_body())])
        async with ExecutionEngineAdapter(
            base_url=BASE_URL, api_key=API_KEY, transport=httpx.MockTransport(seq)
        ) as adapter:
            result = await adapter.submit_order(_order())
        assert result.engine_state == "FILLED"

    @pytest.mark.asyncio
    async def test_typed_4xx_raises_with_original_code(self) -> None:
        seq = _Sequencer(
            [httpx.Response(422, json=_envelope("risk_rejected", "ptrm cap exceeded"))]
        )
        async with ExecutionEngineAdapter(
            base_url=BASE_URL, api_key=API_KEY, transport=httpx.MockTransport(seq)
        ) as adapter:
            with pytest.raises(OrderRejectedError) as ei:
                await adapter.submit_order(_order())
        assert ei.value.code == "risk_rejected"
        assert ei.value.message == "ptrm cap exceeded"
        assert ei.value.status_code == 422
        assert ei.value.client_order_id == "cid-1"
        assert len(seq.requests) == 1  # terminal, no retry

    @pytest.mark.asyncio
    async def test_enveloped_503_kill_switch_is_terminal(self) -> None:
        seq = _Sequencer([httpx.Response(503, json=_envelope("kill_switch_engaged", "halted"))])
        async with ExecutionEngineAdapter(
            base_url=BASE_URL, api_key=API_KEY, transport=httpx.MockTransport(seq)
        ) as adapter:
            with pytest.raises(OrderRejectedError) as ei:
                await adapter.submit_order(_order())
        assert ei.value.code == "kill_switch_engaged"
        assert len(seq.requests) == 1  # NOT retried

    @pytest.mark.asyncio
    async def test_bare_5xx_retried_then_success_same_cid(self) -> None:
        seq = _Sequencer(
            [
                httpx.Response(502, text="bad gateway"),
                httpx.Response(503, text="unavailable"),
                httpx.Response(201, json=_result_body()),
            ]
        )
        async with ExecutionEngineAdapter(
            base_url=BASE_URL,
            api_key=API_KEY,
            transport=httpx.MockTransport(seq),
            backoff_seconds=(0.0,),
        ) as adapter:
            result = await adapter.submit_order(_order("cid-X"))
        assert result.engine_state == "FILLED"
        assert len(seq.requests) == 3
        for req in seq.requests:
            assert json.loads(req.content)["client_order_id"] == "cid-X"

    @pytest.mark.asyncio
    async def test_bare_5xx_exhausts_then_raises(self) -> None:
        seq = _Sequencer([httpx.Response(500, text="boom")] * 3)
        async with ExecutionEngineAdapter(
            base_url=BASE_URL,
            api_key=API_KEY,
            transport=httpx.MockTransport(seq),
            backoff_seconds=(0.0,),
        ) as adapter:
            with pytest.raises(EngineAdapterError, match="after 3 attempts"):
                await adapter.submit_order(_order())
        assert len(seq.requests) == 3

    @pytest.mark.asyncio
    async def test_unparseable_4xx_raises_engine_error(self) -> None:
        seq = _Sequencer([httpx.Response(400, text="<html>nope</html>")])
        async with ExecutionEngineAdapter(
            base_url=BASE_URL, api_key=API_KEY, transport=httpx.MockTransport(seq)
        ) as adapter:
            with pytest.raises(EngineAdapterError, match="unparseable 400"):
                await adapter.submit_order(_order())
        assert len(seq.requests) == 1

    @pytest.mark.asyncio
    async def test_transport_error_retried(self) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if len(calls) < 2:
                raise httpx.ConnectError("dns blip")
            return httpx.Response(201, json=_result_body())

        async with ExecutionEngineAdapter(
            base_url=BASE_URL,
            api_key=API_KEY,
            transport=httpx.MockTransport(handler),
            backoff_seconds=(0.0,),
        ) as adapter:
            result = await adapter.submit_order(_order())
        assert result.engine_state == "FILLED"
        assert len(calls) == 2


# --- get_order ---------------------------------------------------------------


class TestGetOrder:
    @pytest.mark.asyncio
    async def test_200_parsed(self) -> None:
        seq = _Sequencer([httpx.Response(200, json=_result_body())])
        async with ExecutionEngineAdapter(
            base_url=BASE_URL, api_key=API_KEY, transport=httpx.MockTransport(seq)
        ) as adapter:
            result = await adapter.get_order("cid-1")
        assert result.filled_qty == 1
        assert seq.requests[0].url.path == f"{EXECUTION_ORDERS_PATH}/cid-1"
        assert seq.requests[0].headers["X-Strategy-Id"] == STRATEGY_ID

    @pytest.mark.asyncio
    async def test_typed_envelope_raises(self) -> None:
        seq = _Sequencer([httpx.Response(404, json=_envelope("not_found", "no such order"))])
        async with ExecutionEngineAdapter(
            base_url=BASE_URL, api_key=API_KEY, transport=httpx.MockTransport(seq)
        ) as adapter:
            with pytest.raises(OrderRejectedError) as ei:
                await adapter.get_order("cid-1")
        assert ei.value.code == "not_found"

    @pytest.mark.asyncio
    async def test_unparseable_4xx_raises_engine_error(self) -> None:
        seq = _Sequencer([httpx.Response(400, text="nope")])
        async with ExecutionEngineAdapter(
            base_url=BASE_URL, api_key=API_KEY, transport=httpx.MockTransport(seq)
        ) as adapter:
            with pytest.raises(EngineAdapterError, match="unparseable 400"):
                await adapter.get_order("cid-1")

    @pytest.mark.asyncio
    async def test_transport_error_retried_then_success(self) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if len(calls) < 2:
                raise httpx.ConnectError("blip")
            return httpx.Response(200, json=_result_body())

        async with ExecutionEngineAdapter(
            base_url=BASE_URL,
            api_key=API_KEY,
            transport=httpx.MockTransport(handler),
            backoff_seconds=(0.0,),
        ) as adapter:
            result = await adapter.get_order("cid-1")
        assert result.filled_qty == 1
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_bare_5xx_exhausts_then_raises(self) -> None:
        seq = _Sequencer([httpx.Response(500, text="boom")] * 3)
        async with ExecutionEngineAdapter(
            base_url=BASE_URL,
            api_key=API_KEY,
            transport=httpx.MockTransport(seq),
            backoff_seconds=(0.0,),
        ) as adapter:
            with pytest.raises(EngineAdapterError, match="after 3 attempts"):
                await adapter.get_order("cid-1")
        assert len(seq.requests) == 3


# --- stream_updates ----------------------------------------------------------


def _sse_response(body: bytes) -> httpx.Response:
    return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})


async def _collect(adapter: ExecutionEngineAdapter, expected: int, **kw: Any) -> list[Any]:
    """Collect ``expected`` events then break (a real consumer is cancelled, never drains EOF)."""
    out: list[Any] = []
    async for event in adapter.stream_updates(**kw):
        out.append(event)
        if len(out) >= expected:
            break
    return out


class _DropStream(httpx.AsyncByteStream):
    """Yields frames then raises ReadError mid-stream (simulates a dropped connection)."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self._body
        raise httpx.ReadError("connection dropped")

    async def aclose(self) -> None:
        return None


class TestStreamUpdates:
    @pytest.mark.asyncio
    async def test_happy_parse_yields_events(self) -> None:
        body = _sse(
            _event_frame(1, "NEW"),
            _event_frame(2, "FILLED", fill_qty=1),
        )
        seq = _Sequencer([_sse_response(body)])
        async with ExecutionEngineAdapter(
            base_url=BASE_URL, api_key=API_KEY, transport=httpx.MockTransport(seq)
        ) as adapter:
            events = await _collect(adapter, 2)
        assert [e.seq for e in events] == [1, 2]
        assert events[1].is_terminal
        # default filter applies strategy_id
        assert seq.requests[0].url.params["strategy_id"] == STRATEGY_ID
        assert seq.requests[0].url.path == EXECUTION_STREAM_PATH

    @pytest.mark.asyncio
    async def test_keep_alive_comments_ignored(self) -> None:
        body = (": keep-alive\n\n" + _event_frame(1, "FILLED", fill_qty=1) + "\n\n").encode()
        seq = _Sequencer([_sse_response(body)])
        async with ExecutionEngineAdapter(
            base_url=BASE_URL, api_key=API_KEY, transport=httpx.MockTransport(seq)
        ) as adapter:
            events = await _collect(adapter, 1)
        assert len(events) == 1 and events[0].seq == 1

    @pytest.mark.asyncio
    async def test_gap_advisory_warns_and_continues(self) -> None:
        body = (
            'event: gap\ndata: {"dropped": 3}\n\n' + _event_frame(5, "FILLED", fill_qty=1) + "\n\n"
        ).encode()
        seq = _Sequencer([_sse_response(body)])
        async with ExecutionEngineAdapter(
            base_url=BASE_URL, api_key=API_KEY, transport=httpx.MockTransport(seq)
        ) as adapter:
            events = await _collect(adapter, 1)
        assert [e.seq for e in events] == [5]

    @pytest.mark.asyncio
    async def test_resync_required_raises_stream_reset(self) -> None:
        body = b'event: resync_required\ndata: {"after_seq": 42}\n\n'
        seq = _Sequencer([_sse_response(body)])
        async with ExecutionEngineAdapter(
            base_url=BASE_URL, api_key=API_KEY, transport=httpx.MockTransport(seq)
        ) as adapter:
            with pytest.raises(StreamResetError) as ei:
                async for _ in adapter.stream_updates():
                    pass
        assert ei.value.after_seq == 42

    @pytest.mark.asyncio
    async def test_reconnect_sends_last_event_id_and_skips_duplicate_seq(self) -> None:
        # First connection drops after seq 1; reconnect replays seq 1 (skipped) then seq 2.
        first = httpx.Response(
            200,
            stream=_DropStream(_sse(_event_frame(1, "NEW"))),
            headers={"content-type": "text/event-stream"},
        )
        second = _sse_response(_sse(_event_frame(1, "NEW"), _event_frame(2, "FILLED", fill_qty=1)))
        seq = _Sequencer([first, second])
        async with ExecutionEngineAdapter(
            base_url=BASE_URL,
            api_key=API_KEY,
            transport=httpx.MockTransport(seq),
            backoff_seconds=(0.0,),
        ) as adapter:
            events = await _collect(adapter, 2)
        # seq 1 yielded once, the replayed seq 1 skipped by watermark, seq 2 yielded.
        assert [e.seq for e in events] == [1, 2]
        assert len(seq.requests) == 2
        assert seq.requests[1].headers["Last-Event-ID"] == "1"

    @pytest.mark.asyncio
    async def test_stream_open_typed_4xx_no_reconnect(self) -> None:
        seq = _Sequencer([httpx.Response(403, json=_envelope("public_mode", "read only"))])
        async with ExecutionEngineAdapter(
            base_url=BASE_URL,
            api_key=API_KEY,
            transport=httpx.MockTransport(seq),
            backoff_seconds=(0.0,),
        ) as adapter:
            with pytest.raises(OrderRejectedError) as ei:
                async for _ in adapter.stream_updates():
                    pass
        assert ei.value.code == "public_mode"
        assert len(seq.requests) == 1

    @pytest.mark.asyncio
    async def test_stream_open_unparseable_error_raises_stream_error(self) -> None:
        seq = _Sequencer([httpx.Response(500, text="boom")])
        async with ExecutionEngineAdapter(
            base_url=BASE_URL,
            api_key=API_KEY,
            transport=httpx.MockTransport(seq),
            backoff_seconds=(0.0,),
        ) as adapter:
            with pytest.raises(StreamError, match="stream open got 500"):
                async for _ in adapter.stream_updates():
                    pass

    @pytest.mark.asyncio
    async def test_reconnect_exhausts_then_raises(self) -> None:
        responses = [
            httpx.Response(
                200,
                stream=_DropStream(b""),
                headers={"content-type": "text/event-stream"},
            )
            for _ in range(3)
        ]
        seq = _Sequencer(responses)
        async with ExecutionEngineAdapter(
            base_url=BASE_URL,
            api_key=API_KEY,
            transport=httpx.MockTransport(seq),
            backoff_seconds=(0.0,),
        ) as adapter:
            with pytest.raises(StreamError, match="consecutive reconnects"):
                async for _ in adapter.stream_updates():
                    pass
        assert len(seq.requests) == 3

    @pytest.mark.asyncio
    async def test_connected_event_set_on_successful_open(self) -> None:
        import asyncio

        body = _sse(_event_frame(1, "FILLED", fill_qty=1))
        seq = _Sequencer([_sse_response(body)])
        connected = asyncio.Event()
        async with ExecutionEngineAdapter(
            base_url=BASE_URL, api_key=API_KEY, transport=httpx.MockTransport(seq)
        ) as adapter:
            assert not connected.is_set()
            _ = await _collect(adapter, 1, connected=connected)
        assert connected.is_set()

    @pytest.mark.asyncio
    async def test_client_order_id_filter_passed(self) -> None:
        body = _sse(_event_frame(1, "FILLED", fill_qty=1))
        seq = _Sequencer([_sse_response(body)])
        async with ExecutionEngineAdapter(
            base_url=BASE_URL, api_key=API_KEY, transport=httpx.MockTransport(seq)
        ) as adapter:
            _ = await _collect(adapter, 1, client_order_id="cid-1")
        assert seq.requests[0].url.params["client_order_id"] == "cid-1"


class TestConstructor:
    def test_rejects_empty_base_url(self) -> None:
        with pytest.raises(ValueError, match="base_url"):
            ExecutionEngineAdapter(base_url="", api_key=API_KEY)

    def test_rejects_empty_api_key(self) -> None:
        with pytest.raises(ValueError, match="api_key"):
            ExecutionEngineAdapter(base_url=BASE_URL, api_key="")

    def test_rejects_zero_max_attempts(self) -> None:
        with pytest.raises(ValueError, match="max_attempts"):
            ExecutionEngineAdapter(base_url=BASE_URL, api_key=API_KEY, max_attempts=0)

    def test_strategy_id_property(self) -> None:
        adapter = ExecutionEngineAdapter(base_url=BASE_URL, api_key=API_KEY)
        assert adapter.strategy_id == STRATEGY_ID
