"""Unit tests for :mod:`tfex_s50_multi_tf_swing.execution.sim_loop` (Phase 5.1 loop)."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from tfex_s50_multi_tf_swing.config.settings import Settings
from tfex_s50_multi_tf_swing.execution.engine_adapter import ExecutionEngineAdapter
from tfex_s50_multi_tf_swing.execution.errors import ExecutionModeError
from tfex_s50_multi_tf_swing.execution.models import OrderInstruction, SimPosition
from tfex_s50_multi_tf_swing.execution.sim_loop import run_sim_loop

_TS = datetime(2026, 6, 12, 9, 0, tzinfo=UTC).isoformat()
_SYM = "S50Z2026"
# Engine-true mapping (quant-execution-engine ``to_public_status``).
_PUBLIC_STATUS = {
    "NEW": "NEW",
    "PARTIALLY_FILLED": "PARTIALLY_FILLED",
    "FILLED": "FILLED",
    "REJECTED": "REJECTED",
}


def _sim_settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        execution_mode="sim",
        execution_account="SIM-1",
        gateway_base_url="http://gateway.test",
        gateway_api_key=SecretStr("key"),
    )


def _ins(direction: str, contracts: int, price: str = "970.5") -> OrderInstruction:
    return OrderInstruction(
        symbol=_SYM,
        direction=direction,  # type: ignore[arg-type]
        contracts=contracts,
        limit_price=Decimal(price),
    )


def _result_body(cid: str, qty: int, state: str = "FILLED") -> dict[str, Any]:
    return {
        "client_order_id": cid,
        "broker": "sim",
        "status": _PUBLIC_STATUS[state],
        "engine_state": state,
        "filled_qty": qty if state in ("FILLED", "PARTIALLY_FILLED") else 0,
        "remaining_qty": 0 if state == "FILLED" else qty,
        "avg_fill_price": "970.55",
        "created_at": _TS,
        "updated_at": _TS,
    }


def _result_body_pending(cid: str) -> dict[str, Any]:
    # A fresh ack is engine-true: status="NEW" with engine_state="PENDING_NEW".
    return {
        "client_order_id": cid,
        "broker": "sim",
        "status": "NEW",
        "engine_state": "PENDING_NEW",
        "filled_qty": 0,
        "remaining_qty": 0,
        "avg_fill_price": None,
        "created_at": _TS,
        "updated_at": _TS,
    }


# --- A stateful fake engine over httpx.MockTransport -------------------------


class _StreamBody(httpx.AsyncByteStream):
    """Yields SSE frames from a shared queue until a sentinel ``None`` is enqueued."""

    def __init__(self, queue: asyncio.Queue[bytes | None]) -> None:
        self._queue = queue

    async def __aiter__(self) -> AsyncIterator[bytes]:
        while True:
            chunk = await self._queue.get()
            if chunk is None:
                return
            yield chunk

    async def aclose(self) -> None:
        return None


class _FakeEngine:
    """Records submitted orders; serves POST/GET/stream with scripted fills.

    ``fill_plan`` maps a submission ordinal (1-based, in submit order) to a list of
    (engine_state, fill_qty[, fill_price]) event steps; a missing ordinal defaults to a
    single FILLED for the full quantity. The stream task emits those events per order.
    """

    def __init__(
        self,
        *,
        fill_plan: dict[int, list[tuple[str, int] | tuple[str, int, str]]] | None = None,
        post_status: int = 201,
        reject_ordinals: dict[int, dict[str, Any]] | None = None,
        get_filled_qty: int | None = None,
        ack_state: dict[int, str] | None = None,
    ) -> None:
        self._fill_plan = fill_plan or {}
        self._post_status = post_status
        self._reject_ordinals = reject_ordinals or {}
        self._get_filled_qty = get_filled_qty
        self._ack_state = ack_state or {}
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.submitted: list[dict[str, Any]] = []
        self.requests: list[httpx.Request] = []
        self._seq = 0
        self._post_ordinal = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/orders/stream"):
            return httpx.Response(
                200,
                stream=_StreamBody(self.queue),
                headers={"content-type": "text/event-stream"},
            )
        if request.method == "POST" and path.endswith("/orders"):
            return self._handle_post(request)
        if request.method == "GET":
            return self._handle_get(path)
        raise AssertionError(f"unexpected request {request.method} {path}")

    def _handle_post(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.submitted.append(body)
        self._post_ordinal += 1
        ordinal = self._post_ordinal
        cid = body["client_order_id"]
        if ordinal in self._reject_ordinals:
            return httpx.Response(422, json={"error": self._reject_ordinals[ordinal]})
        for step in self._fill_plan.get(ordinal, [("FILLED", body["quantity"])]):
            state, fill_qty = step[0], step[1]
            fill_price = step[2] if len(step) == 3 else "970.55"
            self._enqueue_event(cid, state, fill_qty, fill_price)
        ack = self._ack_state.get(ordinal, "PENDING_NEW")
        if ack in _PUBLIC_STATUS:
            return httpx.Response(self._post_status, json=_result_body(cid, body["quantity"], ack))
        return httpx.Response(self._post_status, json=_result_body_pending(cid))

    def _handle_get(self, path: str) -> httpx.Response:
        cid = path.rsplit("/", 1)[-1]
        if self._get_filled_qty is not None:
            return httpx.Response(
                200,
                json={
                    "client_order_id": cid,
                    "broker": "sim",
                    "status": "FILLED",
                    "engine_state": "FILLED",
                    "filled_qty": self._get_filled_qty,
                    "remaining_qty": 0,
                    "avg_fill_price": "970.55",
                    "created_at": _TS,
                    "updated_at": _TS,
                },
            )
        return httpx.Response(404, json={"error": {"code": "not_found", "message": "x"}})

    def _enqueue_event(self, cid: str, state: str, fill_qty: int, fill_price: str) -> None:
        self._seq += 1
        data: dict[str, Any] = {
            "seq": self._seq,
            "client_order_id": cid,
            "strategy_id": "tfex-s50-multi-tf-swing",
            "engine_state": state,
            "status": _PUBLIC_STATUS[state],
            "price": "970.55",  # wire ``price`` = replace/amend price, NOT an average
            "ts": _TS,
        }
        if fill_qty > 0:
            data["fill"] = {
                "broker_fill_id": f"F-{self._seq}",
                "price": fill_price,
                "quantity": fill_qty,
                "exec_ts": _TS,
            }
        frame = f"id: {self._seq}\nevent: {state}\ndata: {json.dumps(data)}\n\n"
        self.queue.put_nowait(frame.encode())

    def enqueue_raw(self, frame: str) -> None:
        self.queue.put_nowait(frame.encode())

    def adapter(self) -> ExecutionEngineAdapter:
        return ExecutionEngineAdapter(
            base_url="http://gateway.test",
            api_key="key",
            transport=httpx.MockTransport(self.handler),
            backoff_seconds=(0.0,),
        )


# --- run_sim_loop ------------------------------------------------------------


class TestRunSimLoop:
    @pytest.mark.asyncio
    async def test_mode_off_raises(self) -> None:
        settings = Settings(_env_file=None, execution_mode="off")  # type: ignore[call-arg]
        with pytest.raises(ExecutionModeError):
            await run_sim_loop([_ins("long", 1)], settings=settings)

    @pytest.mark.asyncio
    async def test_happy_entry_opens_long(self) -> None:
        fake = _FakeEngine(fill_plan={1: [("FILLED", 1)]})
        result = await run_sim_loop(
            [_ins("long", 1)],
            settings=_sim_settings(),
            adapter=fake.adapter(),
            order_timeout_seconds=5.0,
        )
        assert result.position is not None
        assert result.position.direction == "long"
        assert result.position.contracts == 1
        assert result.outcomes[0].final_state == "FILLED"
        assert result.outcomes[0].position_effect == "OPEN"
        # uuid4 client_order_id
        assert uuid.UUID(result.outcomes[0].client_order_id).version == 4

    @pytest.mark.asyncio
    async def test_entry_then_exit_open_close_flat(self) -> None:
        # One run, two instructions: long open (1 @ 970.5) then short close (1) → flat.
        fake = _FakeEngine(fill_plan={1: [("FILLED", 1, "970.50")], 2: [("FILLED", 1, "972.00")]})
        result = await run_sim_loop(
            [_ins("long", 1, "970.5"), _ins("short", 1, "972.0")],
            settings=_sim_settings(),
            adapter=fake.adapter(),
            order_timeout_seconds=5.0,
        )
        assert len(result.outcomes) == 2
        entry, exit_ = result.outcomes
        # Entry leg = OPEN, FILLED, the intermediate long position is 1 @ 970.50.
        assert entry.position_effect == "OPEN"
        assert entry.final_state == "FILLED"
        assert entry.filled_qty == 1
        assert entry.avg_fill_price == Decimal("970.50")
        # Exit leg = CLOSE, FILLED.
        assert exit_.position_effect == "CLOSE"
        assert exit_.final_state == "FILLED"
        # Final position flat.
        assert result.position is None

    @pytest.mark.asyncio
    async def test_partial_entry_closes_to_smaller_position(self) -> None:
        # Open 2, then close 1 → a 1-contract long remains.
        fake = _FakeEngine(fill_plan={1: [("FILLED", 2, "970.00")], 2: [("FILLED", 1, "975.00")]})
        result = await run_sim_loop(
            [_ins("long", 2, "970.0"), _ins("short", 1, "975.0")],
            settings=_sim_settings(),
            adapter=fake.adapter(),
            order_timeout_seconds=5.0,
        )
        assert result.position is not None
        assert result.position.direction == "long"
        assert result.position.contracts == 1
        assert result.position.avg_entry == Decimal("970.00")  # CLOSE keeps avg
        assert result.outcomes[1].position_effect == "CLOSE"

    @pytest.mark.asyncio
    async def test_add_to_position_weighted_avg(self) -> None:
        # Open 1 @ 970, then open 1 more @ 974 → 2 @ 972 (weighted avg, same direction).
        fake = _FakeEngine(fill_plan={1: [("FILLED", 1, "970.00")], 2: [("FILLED", 1, "974.00")]})
        result = await run_sim_loop(
            [_ins("long", 1, "970.0"), _ins("long", 1, "974.0")],
            settings=_sim_settings(),
            adapter=fake.adapter(),
            order_timeout_seconds=5.0,
        )
        assert result.position is not None
        assert result.position.contracts == 2
        assert result.position.avg_entry == Decimal("972.00")
        assert result.outcomes[1].position_effect == "OPEN"

    @pytest.mark.asyncio
    async def test_ack_already_filled_no_double_count(self) -> None:
        # The POST ack returns FILLED AND the stream replays the fill — apply once.
        fake = _FakeEngine(fill_plan={1: [("FILLED", 1)]}, ack_state={1: "FILLED"})
        result = await run_sim_loop(
            [_ins("long", 1)],
            settings=_sim_settings(),
            adapter=fake.adapter(),
            order_timeout_seconds=5.0,
        )
        assert result.position is not None
        assert result.position.contracts == 1  # exactly once

    @pytest.mark.asyncio
    async def test_partial_fills_aggregate(self) -> None:
        fake = _FakeEngine(fill_plan={1: [("PARTIALLY_FILLED", 1), ("FILLED", 1)]})
        result = await run_sim_loop(
            [_ins("long", 2)],
            settings=_sim_settings(),
            adapter=fake.adapter(),
            order_timeout_seconds=5.0,
        )
        assert result.position is not None
        assert result.position.contracts == 2
        assert result.outcomes[0].final_state == "FILLED"

    @pytest.mark.asyncio
    async def test_reject_mid_batch_continues_position_unchanged(self) -> None:
        # First order opens long 1; second (close 2) is rejected → position unchanged;
        # third (open 1) still submits → long 2.
        fake = _FakeEngine(
            fill_plan={1: [("FILLED", 1)], 3: [("FILLED", 1)]},
            reject_ordinals={
                2: {"code": "risk_rejected", "message": "cap", "client_order_id": "x"}
            },
        )
        result = await run_sim_loop(
            [_ins("long", 1), _ins("short", 1), _ins("long", 1)],
            settings=_sim_settings(),
            adapter=fake.adapter(),
            order_timeout_seconds=5.0,
        )
        assert result.outcomes[0].final_state == "FILLED"
        assert result.outcomes[1].rejected is True
        assert result.outcomes[1].reject_code == "risk_rejected"
        assert result.outcomes[1].position_effect == "CLOSE"
        assert result.outcomes[2].final_state == "FILLED"
        assert result.position is not None
        assert result.position.contracts == 2  # 1 + 1, the rejected close did not reduce

    @pytest.mark.asyncio
    async def test_timeout_then_get_residual(self) -> None:
        # Stream delivers only 1/2 (no terminal); GET says 2 → apply +1 residual only.
        fake = _FakeEngine(fill_plan={1: [("PARTIALLY_FILLED", 1)]}, get_filled_qty=2)
        result = await run_sim_loop(
            [_ins("long", 2)],
            settings=_sim_settings(),
            adapter=fake.adapter(),
            order_timeout_seconds=0.2,
        )
        assert result.position is not None
        assert result.position.contracts == 2  # 1 stream + 1 residual
        assert result.outcomes[0].final_state == "FILLED"
        assert result.outcomes[0].filled_qty == 2

    @pytest.mark.asyncio
    async def test_stream_resync_degrades_to_get(self) -> None:
        # The stream emits resync_required before any fill; loop degrades to GET polling.
        fake = _FakeEngine(fill_plan={1: []}, get_filled_qty=1)
        fake.enqueue_raw('event: resync_required\ndata: {"after_seq": 0}\n\n')
        result = await run_sim_loop(
            [_ins("long", 1)],
            settings=_sim_settings(),
            adapter=fake.adapter(),
            order_timeout_seconds=5.0,
        )
        assert result.position is not None
        assert result.position.contracts == 1  # via GET residual
        assert result.outcomes[0].final_state == "FILLED"

    @pytest.mark.asyncio
    async def test_distinct_uuids_per_order(self) -> None:
        fake = _FakeEngine(fill_plan={1: [("FILLED", 1)], 2: [("FILLED", 1)]})
        await run_sim_loop(
            [_ins("long", 1), _ins("long", 1)],
            settings=_sim_settings(),
            adapter=fake.adapter(),
            order_timeout_seconds=5.0,
        )
        cids = [b["client_order_id"] for b in fake.submitted]
        assert len(cids) == len(set(cids)) == 2
        for cid in cids:
            assert uuid.UUID(cid).version == 4

    @pytest.mark.asyncio
    async def test_stream_subscribed_before_first_submit(self) -> None:
        fake = _FakeEngine(fill_plan={1: [("FILLED", 1)]})
        await run_sim_loop(
            [_ins("long", 1)],
            settings=_sim_settings(),
            adapter=fake.adapter(),
            order_timeout_seconds=5.0,
        )
        assert fake.requests, "no requests recorded"
        assert fake.requests[0].url.path.endswith("/orders/stream")
        post_indices = [i for i, r in enumerate(fake.requests) if r.method == "POST"]
        assert post_indices and min(post_indices) >= 1  # every POST after the stream open

    @pytest.mark.asyncio
    async def test_stream_never_connects_warns_and_proceeds(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        fake = _FakeEngine(fill_plan={1: []}, get_filled_qty=1)

        async def hanging_handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/orders/stream"):
                await asyncio.sleep(60.0)  # cancelled at loop teardown
            return fake.handler(request)

        adapter = ExecutionEngineAdapter(
            base_url="http://gateway.test",
            api_key="key",
            transport=httpx.MockTransport(hanging_handler),
            backoff_seconds=(0.0,),
        )
        with caplog.at_level(logging.WARNING, logger="tfex_s50_multi_tf_swing.execution.sim_loop"):
            result = await run_sim_loop(
                [_ins("long", 1)],
                settings=_sim_settings(),
                adapter=adapter,
                order_timeout_seconds=0.2,
                stream_connect_timeout_seconds=0.1,
            )
        assert "stream not connected" in caplog.text
        assert result.outcomes[0].final_state == "FILLED"
        assert result.position is not None
        assert result.position.contracts == 1  # via GET reconcile

    @pytest.mark.asyncio
    async def test_avg_fill_price_weighted_across_partials(self) -> None:
        # 1 @ 970.00 + 1 @ 972.00 → 971.00. The event's top-level ``price`` (970.55)
        # must NOT become the average.
        fake = _FakeEngine(
            fill_plan={1: [("PARTIALLY_FILLED", 1, "970.00"), ("FILLED", 1, "972.00")]}
        )
        result = await run_sim_loop(
            [_ins("long", 2)],
            settings=_sim_settings(),
            adapter=fake.adapter(),
            order_timeout_seconds=5.0,
        )
        assert result.outcomes[0].filled_qty == 2
        assert result.outcomes[0].avg_fill_price == Decimal("971.00")

    @pytest.mark.asyncio
    async def test_timeout_still_non_terminal_records_none(self) -> None:
        # Stream delivers a partial but no terminal; GET also returns non-terminal →
        # the order records final_state=None and the loop completes without crashing.
        fake = _FakeEngine(fill_plan={1: [("PARTIALLY_FILLED", 1)]})

        def get_handler(request: httpx.Request) -> httpx.Response:
            fake.requests.append(request)
            path = request.url.path
            if path.endswith("/orders/stream"):
                return httpx.Response(
                    200,
                    stream=_StreamBody(fake.queue),
                    headers={"content-type": "text/event-stream"},
                )
            if request.method == "POST":
                return fake._handle_post(request)
            cid = path.rsplit("/", 1)[-1]
            return httpx.Response(
                200,
                json={
                    "client_order_id": cid,
                    "broker": "sim",
                    "status": "PARTIALLY_FILLED",
                    "engine_state": "PARTIALLY_FILLED",
                    "filled_qty": 1,
                    "remaining_qty": 1,
                    "avg_fill_price": "970.55",
                    "created_at": _TS,
                    "updated_at": _TS,
                },
            )

        adapter = ExecutionEngineAdapter(
            base_url="http://gateway.test",
            api_key="key",
            transport=httpx.MockTransport(get_handler),
            backoff_seconds=(0.0,),
        )
        result = await run_sim_loop(
            [_ins("long", 2)],
            settings=_sim_settings(),
            adapter=adapter,
            order_timeout_seconds=0.2,
        )
        assert result.outcomes[0].final_state is None
        assert result.position is not None
        assert result.position.contracts == 1  # only the streamed partial

    @pytest.mark.asyncio
    async def test_starting_position_close_to_flat(self) -> None:
        # Pre-seed a long-2 position; a short-2 close goes to flat.
        fake = _FakeEngine(fill_plan={1: [("FILLED", 2)]})
        start = SimPosition(direction="long", contracts=2, avg_entry=Decimal("970"))
        result = await run_sim_loop(
            [_ins("short", 2)],
            settings=_sim_settings(),
            position=start,
            adapter=fake.adapter(),
            order_timeout_seconds=5.0,
        )
        assert result.outcomes[0].position_effect == "CLOSE"
        assert result.position is None


class TestBuildAdapterGuards:
    @pytest.mark.asyncio
    async def test_missing_gateway_url_raises_mode_error(self) -> None:
        settings = Settings(_env_file=None, execution_mode="off")  # type: ignore[call-arg]
        forced = settings.model_copy(update={"execution_mode": "sim", "gateway_base_url": ""})
        with pytest.raises(ExecutionModeError, match="GATEWAY_BASE_URL"):
            await run_sim_loop([_ins("long", 1)], settings=forced)

    @pytest.mark.asyncio
    async def test_missing_gateway_key_raises_mode_error(self) -> None:
        settings = Settings(_env_file=None, execution_mode="off")  # type: ignore[call-arg]
        forced = settings.model_copy(
            update={
                "execution_mode": "sim",
                "gateway_base_url": "http://gateway.test",
                "gateway_api_key": SecretStr(""),
                "execution_account": "SIM-1",
            }
        )
        with pytest.raises(ExecutionModeError, match="GATEWAY_API_KEY"):
            await run_sim_loop([_ins("long", 1)], settings=forced)
