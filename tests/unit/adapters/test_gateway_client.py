"""Tests for ``tfex_s50_multi_tf_swing.adapters.gateway_client``."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

from tfex_s50_multi_tf_swing.adapters.errors import GatewayClientError
from tfex_s50_multi_tf_swing.adapters.gateway_client import (
    DEFAULT_MAX_ATTEMPTS,
    GatewayClient,
)
from tfex_s50_multi_tf_swing.adapters.payload import (
    INGEST_PATH,
    StrategyPayload,
    build_ingestion_payload,
)


def _payload() -> StrategyPayload:
    return build_ingestion_payload(
        strategy_id="tfex-s50-multi-tf-swing",
        last_updated=datetime(2026, 5, 28, tzinfo=UTC),
        daily_pnl=Decimal("0"),
        equity_curve=[("2026-05-28", Decimal("100000"))],
        max_drawdown=Decimal("0"),
        sharpe_ratio=Decimal("0"),
        total_value=Decimal("100000"),
        cash_balance=Decimal("100000"),
        positions_count=0,
        margin_usage=Decimal("0"),
    )


class _Sequencer:
    """Pop one queued response per call; raise StopIteration if exhausted."""

    def __init__(self, responses: list[httpx.Response | type[BaseException]]) -> None:
        self._responses = list(responses)
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if not self._responses:
            raise AssertionError("MockTransport ran out of queued responses")
        nxt = self._responses.pop(0)
        if isinstance(nxt, type) and issubclass(nxt, BaseException):
            raise nxt("simulated transport error")
        return nxt


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


def test_client_requires_base_url() -> None:
    with pytest.raises(ValueError, match="base_url"):
        GatewayClient(base_url="", api_key="k")


def test_client_requires_api_key() -> None:
    with pytest.raises(ValueError, match="api_key"):
        GatewayClient(base_url="http://x", api_key="")


def test_client_requires_positive_attempts() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        GatewayClient(base_url="http://x", api_key="k", max_attempts=0)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_post_daily_report_2xx_sends_api_key_and_returns() -> None:
    seq = _Sequencer([httpx.Response(201, json={"ok": True})])
    transport = httpx.MockTransport(seq)
    async with GatewayClient(
        base_url="http://gateway",
        api_key="secret-key",
        transport=transport,
    ) as client:
        await client.post_daily_report(_payload())

    assert len(seq.calls) == 1
    req = seq.calls[0]
    assert req.method == "POST"
    assert req.url.path == INGEST_PATH
    assert req.headers.get("X-API-Key") == "secret-key"
    assert req.headers.get("Content-Type") == "application/json"


async def test_repeated_post_succeeds_twice_for_idempotency() -> None:
    """The client just re-POSTs — idempotency is gateway-side."""
    seq = _Sequencer(
        [httpx.Response(201, json={"ok": True}), httpx.Response(201, json={"ok": True})]
    )
    transport = httpx.MockTransport(seq)
    async with GatewayClient(base_url="http://gateway", api_key="k", transport=transport) as client:
        await client.post_daily_report(_payload())
        await client.post_daily_report(_payload())
    assert len(seq.calls) == 2


# ---------------------------------------------------------------------------
# 4xx is terminal — no retry
# ---------------------------------------------------------------------------


async def test_post_4xx_raises_immediately_no_retry() -> None:
    seq = _Sequencer([httpx.Response(422, text="validation error")])
    transport = httpx.MockTransport(seq)
    async with GatewayClient(base_url="http://gateway", api_key="k", transport=transport) as client:
        with pytest.raises(GatewayClientError, match="422"):
            await client.post_daily_report(_payload())
    assert len(seq.calls) == 1  # no retry


async def test_post_401_raises_gateway_client_error() -> None:
    seq = _Sequencer([httpx.Response(401, text="bad key")])
    transport = httpx.MockTransport(seq)
    async with GatewayClient(base_url="http://gateway", api_key="k", transport=transport) as client:
        with pytest.raises(GatewayClientError, match="401"):
            await client.post_daily_report(_payload())


# ---------------------------------------------------------------------------
# 5xx + transport errors — retried; eventual failure raises
# ---------------------------------------------------------------------------


async def test_post_5xx_retries_then_succeeds() -> None:
    seq = _Sequencer(
        [
            httpx.Response(503, text="overloaded"),
            httpx.Response(502, text="bad gateway"),
            httpx.Response(201, json={"ok": True}),
        ]
    )
    transport = httpx.MockTransport(seq)
    async with GatewayClient(
        base_url="http://gateway",
        api_key="k",
        transport=transport,
        backoff_seconds=(0.0, 0.0, 0.0),
    ) as client:
        await client.post_daily_report(_payload())
    assert len(seq.calls) == 3


async def test_post_5xx_exhausts_retries_raises() -> None:
    seq = _Sequencer(
        [
            httpx.Response(500, text="boom"),
            httpx.Response(502, text="boom"),
            httpx.Response(503, text="boom"),
        ]
    )
    transport = httpx.MockTransport(seq)
    async with GatewayClient(
        base_url="http://gateway",
        api_key="k",
        transport=transport,
        backoff_seconds=(0.0, 0.0, 0.0),
    ) as client:
        with pytest.raises(GatewayClientError, match=r"failed after \d+ attempts"):
            await client.post_daily_report(_payload())
    assert len(seq.calls) == DEFAULT_MAX_ATTEMPTS


async def test_post_transport_error_retries() -> None:
    seq = _Sequencer([httpx.ConnectError, httpx.Response(201, json={"ok": True})])
    transport = httpx.MockTransport(seq)
    async with GatewayClient(
        base_url="http://gateway",
        api_key="k",
        transport=transport,
        backoff_seconds=(0.0,),
    ) as client:
        await client.post_daily_report(_payload())
    assert len(seq.calls) == 2


async def test_post_transport_error_exhausts_raises_with_cause() -> None:
    seq = _Sequencer([httpx.ConnectError, httpx.ConnectError, httpx.ConnectError])
    transport = httpx.MockTransport(seq)
    async with GatewayClient(
        base_url="http://gateway",
        api_key="k",
        transport=transport,
        backoff_seconds=(0.0, 0.0, 0.0),
    ) as client:
        with pytest.raises(GatewayClientError) as excinfo:
            await client.post_daily_report(_payload())
    assert isinstance(excinfo.value.__cause__, httpx.ConnectError)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


async def test_close_is_idempotent() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(201))
    client = GatewayClient(base_url="http://x", api_key="k", transport=transport)
    await client.close()
    await client.close()  # second call must not raise


async def test_backoff_falls_back_to_zero_when_empty() -> None:
    """Empty backoff tuple is normalised to a single 0-second wait so retries still run."""
    seq = _Sequencer([httpx.Response(503), httpx.Response(201)])
    transport = httpx.MockTransport(seq)
    async with GatewayClient(
        base_url="http://gateway",
        api_key="k",
        transport=transport,
        backoff_seconds=(),
    ) as client:
        await client.post_daily_report(_payload())
    assert len(seq.calls) == 2


async def test_post_serialises_payload_decimals_as_strings_on_wire() -> None:
    received: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["body"] = request.read().decode("utf-8")
        return httpx.Response(201, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with GatewayClient(base_url="http://gateway", api_key="k", transport=transport) as client:
        await client.post_daily_report(_payload())

    assert '"value":"100000.0000"' in received["body"]
    assert '"daily_pnl":"0.0000"' in received["body"]
    assert '"margin_usage":"0.0000"' in received["body"]
