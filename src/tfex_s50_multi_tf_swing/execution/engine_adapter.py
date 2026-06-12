"""Async HTTP/SSE client for the Execution engine (via the gateway proxy).

``ExecutionEngineAdapter`` mirrors
:class:`tfex_s50_multi_tf_swing.adapters.gateway_client.GatewayClient`'s construction
(base_url, api_key, transport injection, retry/backoff) and adds:

- :meth:`submit_order` — ``POST /orders`` with at-least-once + engine-dedupe
  semantics: bare transport/5xx failures retry the **same** ``client_order_id``
  (a fresh id would risk double execution); typed rejection envelopes are
  terminal and never retried.
- :meth:`get_order` — ``GET /orders/{cid}`` for residual reconciliation.
- :meth:`stream_updates` — a hand-rolled SSE consumer over ``aiter_lines`` with a
  ``read=None`` timeout (keep-alives every ~15 s), a client-side seq watermark,
  and a ``Last-Event-ID`` reconnect loop.

Every request carries ``X-API-Key`` and ``X-Strategy-Id``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from tfex_s50_multi_tf_swing.execution.errors import (
    EngineAdapterError,
    OrderRejectedError,
    StreamError,
    StreamResetError,
)
from tfex_s50_multi_tf_swing.execution.models import (
    NormalizedOrder,
    NormalizedOrderResult,
    OrderUpdateEvent,
)

logger: logging.Logger = logging.getLogger(__name__)

EXECUTION_ORDERS_PATH: str = "/api/v2/engines/execution/orders"
EXECUTION_STREAM_PATH: str = "/api/v2/engines/execution/orders/stream"
STRATEGY_ID: str = "tfex-s50-multi-tf-swing"
DEFAULT_TIMEOUT_SECONDS: float = 10.0
DEFAULT_MAX_ATTEMPTS: int = 3
DEFAULT_BACKOFF_SECONDS: tuple[float, ...] = (0.5, 1.0, 2.0)


def _parse_error_envelope(response: httpx.Response) -> dict[str, Any] | None:
    """Return the ``error`` object if the body is a typed rejection envelope, else None."""
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and "code" in error and "message" in error:
            return error
    return None


class ExecutionEngineAdapter:
    """Async context-managed client for the Execution engine order surface.

    Args:
        base_url: Gateway base URL, e.g. ``http://quant-api-gateway:8000``.
        api_key: Shared secret sent as ``X-API-Key``.
        strategy_id: Slug sent as ``X-Strategy-Id`` and used as the default
            stream filter. Defaults to ``"tfex-s50-multi-tf-swing"``.
        timeout: Per-request timeout in seconds (the stream uses ``read=None``).
        max_attempts: Total attempts (initial + retries) on bare 5xx / transport
            errors for ``submit_order`` and stream reconnects.
        backoff_seconds: Sleep durations between retries (clamped to the last).
        transport: Optional :class:`httpx.AsyncBaseTransport` for tests.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        strategy_id: str = STRATEGY_ID,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_seconds: tuple[float, ...] = DEFAULT_BACKOFF_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not api_key:
            raise ValueError("api_key is required")
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

        self._base_url: str = base_url.rstrip("/")
        self._api_key: str = api_key
        self._strategy_id: str = strategy_id
        self._timeout: float = timeout
        self._max_attempts: int = max_attempts
        self._backoff: tuple[float, ...] = backoff_seconds or (0.0,)
        self._client: httpx.AsyncClient = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            transport=transport,
        )

    @property
    def strategy_id(self) -> str:
        """The ``X-Strategy-Id`` slug used on every request."""
        return self._strategy_id

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self._api_key, "X-Strategy-Id": self._strategy_id}

    async def close(self) -> None:
        """Close the underlying HTTP client. Idempotent."""
        await self._client.aclose()

    async def __aenter__(self) -> ExecutionEngineAdapter:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    def _backoff_at(self, attempt: int) -> float:
        return self._backoff[min(attempt, len(self._backoff) - 1)]

    # --- Order submission / read --------------------------------------------

    async def submit_order(self, order: NormalizedOrder) -> NormalizedOrderResult:
        """POST a NormalizedOrder; retry bare 5xx / transport errors with the same cid.

        201 (accepted) and 200 (idempotent resend) are handled identically. A
        typed rejection envelope (any 4xx, or an enveloped 503 like
        ``kill_switch_engaged``) is terminal → :class:`OrderRejectedError`. An
        unparseable 4xx → :class:`EngineAdapterError`. Bare 5xx and transport
        errors retry the same ``client_order_id``.

        Raises:
            OrderRejectedError: On a typed rejection envelope (terminal).
            EngineAdapterError: On an unparseable 4xx or exhausted retries.
        """
        headers = {**self._headers(), "Content-Type": "application/json"}
        body = order.wire_dump()
        last_exc: Exception | None = None
        for attempt in range(self._max_attempts):
            try:
                response = await self._client.post(
                    EXECUTION_ORDERS_PATH, json=body, headers=headers
                )
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning(
                    "submit_order transport error cid=%s (attempt %d/%d): %s",
                    order.client_order_id,
                    attempt + 1,
                    self._max_attempts,
                    exc,
                )
            else:
                if response.status_code in (200, 201):
                    return NormalizedOrderResult.model_validate(response.json())
                error = _parse_error_envelope(response)
                if error is not None:
                    raise OrderRejectedError(
                        code=str(error["code"]),
                        message=str(error["message"]),
                        client_order_id=error.get("client_order_id"),
                        status_code=response.status_code,
                    )
                if 400 <= response.status_code < 500:
                    raise EngineAdapterError(
                        f"submit_order got unparseable {response.status_code}: "
                        f"{response.text[:200]}"
                    )
                # Bare 5xx (no envelope) — retry the same cid.
                last_exc = EngineAdapterError(
                    f"submit_order got {response.status_code}: {response.text[:200]}"
                )
                logger.warning(
                    "submit_order bare 5xx cid=%s (attempt %d/%d): %d",
                    order.client_order_id,
                    attempt + 1,
                    self._max_attempts,
                    response.status_code,
                )

            if attempt + 1 < self._max_attempts:
                sleep_for = self._backoff_at(attempt)
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)

        raise EngineAdapterError(
            f"submit_order cid={order.client_order_id} failed after {self._max_attempts} attempts"
        ) from last_exc

    async def get_order(self, client_order_id: str) -> NormalizedOrderResult:
        """GET a single order by client id; typed envelopes raise, transport errors retry.

        Raises:
            OrderRejectedError: On a typed rejection envelope.
            EngineAdapterError: On an unparseable error or exhausted retries.
        """
        headers = self._headers()
        path = f"{EXECUTION_ORDERS_PATH}/{client_order_id}"
        last_exc: Exception | None = None
        for attempt in range(self._max_attempts):
            try:
                response = await self._client.get(path, headers=headers)
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning(
                    "get_order transport error cid=%s (attempt %d/%d): %s",
                    client_order_id,
                    attempt + 1,
                    self._max_attempts,
                    exc,
                )
            else:
                if response.status_code == 200:
                    return NormalizedOrderResult.model_validate(response.json())
                error = _parse_error_envelope(response)
                if error is not None:
                    raise OrderRejectedError(
                        code=str(error["code"]),
                        message=str(error["message"]),
                        client_order_id=error.get("client_order_id"),
                        status_code=response.status_code,
                    )
                if 400 <= response.status_code < 500:
                    raise EngineAdapterError(
                        f"get_order got unparseable {response.status_code}: {response.text[:200]}"
                    )
                last_exc = EngineAdapterError(
                    f"get_order got {response.status_code}: {response.text[:200]}"
                )

            if attempt + 1 < self._max_attempts:
                sleep_for = self._backoff_at(attempt)
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)

        raise EngineAdapterError(
            f"get_order cid={client_order_id} failed after {self._max_attempts} attempts"
        ) from last_exc

    # --- SSE stream ----------------------------------------------------------

    async def stream_updates(
        self,
        *,
        filter_strategy_id: str | None = None,
        client_order_id: str | None = None,
        last_event_id: int | None = None,
        connected: asyncio.Event | None = None,
    ) -> AsyncIterator[OrderUpdateEvent]:
        """Yield order-update events from the SSE stream, reconnecting on drop.

        By default filters on this adapter's ``strategy_id``. Maintains a
        client-side seq watermark (skips ``seq <= cursor``); reconnects send
        ``Last-Event-ID: <cursor>``. When ``connected`` is given it is set on
        every successful (re)connect — callers use it as a subscribe-before-submit
        handshake (re-setting an already-set event is a no-op).

        Raises:
            StreamResetError: On ``event: resync_required`` (caller degrades to GET).
            OrderRejectedError: On a typed envelope at stream open.
            StreamError: On an unparseable open error or exhausted reconnects.
        """
        strategy_id = filter_strategy_id if filter_strategy_id is not None else self._strategy_id
        params: dict[str, str] = {"strategy_id": strategy_id}
        if client_order_id is not None:
            params["client_order_id"] = client_order_id
        cursor: int = last_event_id if last_event_id is not None else 0
        first_connect: bool = True
        consecutive_failures: int = 0

        while True:
            connect_params = dict(params)
            headers = self._headers()
            if first_connect and last_event_id is not None:
                connect_params["last_event_id"] = str(last_event_id)
            if not first_connect and cursor > 0:
                headers["Last-Event-ID"] = str(cursor)
            first_connect = False

            stream_timeout = httpx.Timeout(self._timeout, read=None)
            try:
                async with self._client.stream(
                    "GET",
                    EXECUTION_STREAM_PATH,
                    params=connect_params,
                    headers=headers,
                    timeout=stream_timeout,
                ) as response:
                    if response.status_code != 200:
                        await response.aread()
                        error = _parse_error_envelope(response)
                        if error is not None:
                            raise OrderRejectedError(
                                code=str(error["code"]),
                                message=str(error["message"]),
                                client_order_id=error.get("client_order_id"),
                                status_code=response.status_code,
                            )
                        raise StreamError(
                            f"stream open got {response.status_code}: {response.text[:200]}"
                        )

                    if connected is not None:
                        connected.set()
                    async for event in self._iter_frames(response):
                        consecutive_failures = 0
                        if event.seq <= cursor:
                            continue
                        cursor = event.seq
                        yield event
            except (StreamResetError, OrderRejectedError, StreamError):
                raise
            except httpx.HTTPError as exc:
                consecutive_failures += 1
                logger.warning(
                    "stream transport error (failure %d/%d): %s",
                    consecutive_failures,
                    self._max_attempts,
                    exc,
                )
            else:
                # Clean EOF from the server — treat as a reconnectable drop.
                consecutive_failures += 1
                logger.warning(
                    "stream closed by server (failure %d/%d)",
                    consecutive_failures,
                    self._max_attempts,
                )

            if consecutive_failures >= self._max_attempts:
                raise StreamError(
                    f"stream failed after {consecutive_failures} consecutive reconnects"
                )
            sleep_for = self._backoff_at(consecutive_failures - 1)
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)

    async def _iter_frames(self, response: httpx.Response) -> AsyncIterator[OrderUpdateEvent]:
        """Parse SSE frames off an open response; dispatch advisories, yield events."""
        event_name: str | None = None
        data_lines: list[str] = []
        async for raw_line in response.aiter_lines():
            line = raw_line.rstrip("\n").rstrip("\r")
            if line == "":
                event = self._dispatch_frame(event_name, "\n".join(data_lines))
                event_name = None
                data_lines = []
                if event is not None:
                    yield event
                continue
            if line.startswith(":"):
                continue  # comment / keep-alive
            field, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
            if field == "event":
                event_name = value
            elif field == "data":
                data_lines.append(value)
            # ``id:`` is carried by the OrderUpdateEvent.seq; we ignore the SSE id field.

    def _dispatch_frame(self, event_name: str | None, data: str) -> OrderUpdateEvent | None:
        """Turn one accumulated frame into an event, or handle an advisory/empty frame."""
        if not data:
            return None
        if event_name == "resync_required":
            raise StreamResetError(after_seq=int(json.loads(data)["after_seq"]))
        if event_name == "gap":
            logger.warning("stream gap advisory: %s", data)
            return None
        return OrderUpdateEvent.model_validate_json(data)


__all__: list[str] = [
    "DEFAULT_BACKOFF_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_TIMEOUT_SECONDS",
    "EXECUTION_ORDERS_PATH",
    "EXECUTION_STREAM_PATH",
    "STRATEGY_ID",
    "ExecutionEngineAdapter",
]
