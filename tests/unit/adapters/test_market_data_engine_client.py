"""Tests for ``tfex_s50_multi_tf_swing.adapters.market_data_engine_client``."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from tfex_s50_multi_tf_swing.adapters.errors import MarketDataEngineError
from tfex_s50_multi_tf_swing.adapters.market_data_engine_client import (
    OHLCV_ADJUSTED_PATH,
    OHLCV_PATH,
    EngineOHLCVResponse,
    MarketDataEngineClient,
)


def _ohlcv_json(*, open_interest: str | None = "1234.0000") -> dict[str, object]:
    bar: dict[str, object] = {
        "ts": "2026-03-02T03:00:00+00:00",
        "open": "812.100000",
        "high": "813.500000",
        "low": "811.000000",
        "close": "812.900000",
        "volume": "1500.0000",
        "open_interest": open_interest,
    }
    return {
        "symbol": "S50M2026",
        "timeframe": "5m",
        "adjusted": False,
        "bars": [bar],
    }


class _Sequencer:
    """Pop one queued response per call; record requests."""

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
        MarketDataEngineClient(base_url="")


def test_client_requires_positive_attempts() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        MarketDataEngineClient(base_url="http://x", max_attempts=0)


def test_api_key_is_optional() -> None:
    # Constructing without a key must not raise.
    client = MarketDataEngineClient(base_url="http://x")
    assert isinstance(client, MarketDataEngineClient)


# ---------------------------------------------------------------------------
# Happy path — parsing, routing, params
# ---------------------------------------------------------------------------


async def test_happy_path_parses_decimal_and_ts() -> None:
    seq = _Sequencer([httpx.Response(200, json=_ohlcv_json())])
    async with MarketDataEngineClient(
        base_url="http://engine", transport=httpx.MockTransport(seq)
    ) as client:
        resp: EngineOHLCVResponse = await client.get_ohlcv(
            "S50M2026", "5m", adjusted=False, limit=5000
        )
    assert resp.symbol == "S50M2026"
    assert resp.adjusted is False
    bar = resp.bars[0]
    assert bar.open == Decimal("812.100000")
    assert bar.open_interest == Decimal("1234.0000")
    assert bar.ts == datetime(2026, 3, 2, 3, 0, tzinfo=UTC)


async def test_raw_endpoint_path_and_params() -> None:
    seq = _Sequencer([httpx.Response(200, json=_ohlcv_json())])
    async with MarketDataEngineClient(
        base_url="http://engine", transport=httpx.MockTransport(seq)
    ) as client:
        await client.get_ohlcv("S50M2026", "5m", adjusted=False, limit=123)
    req = seq.calls[0]
    assert req.url.path == OHLCV_PATH
    assert req.url.params["symbol"] == "S50M2026"
    assert req.url.params["timeframe"] == "5m"
    assert req.url.params["limit"] == "123"


async def test_adjusted_routes_to_adjusted_path() -> None:
    seq = _Sequencer([httpx.Response(200, json=_ohlcv_json())])
    async with MarketDataEngineClient(
        base_url="http://engine", transport=httpx.MockTransport(seq)
    ) as client:
        await client.get_ohlcv("S50M2026", "5m", adjusted=True, limit=10)
    assert seq.calls[0].url.path == OHLCV_ADJUSTED_PATH


async def test_start_end_params_isoformatted() -> None:
    seq = _Sequencer([httpx.Response(200, json=_ohlcv_json())])
    start = datetime(2026, 3, 1, tzinfo=UTC)
    end = datetime(2026, 4, 1, tzinfo=UTC)
    async with MarketDataEngineClient(
        base_url="http://engine", transport=httpx.MockTransport(seq)
    ) as client:
        await client.get_ohlcv("S50M2026", "5m", adjusted=False, limit=10, start=start, end=end)
    params = seq.calls[0].url.params
    assert params["start"] == start.isoformat()
    assert params["end"] == end.isoformat()


# ---------------------------------------------------------------------------
# X-API-Key forwarding
# ---------------------------------------------------------------------------


async def test_api_key_forwarded_as_header() -> None:
    seq = _Sequencer([httpx.Response(200, json=_ohlcv_json())])
    async with MarketDataEngineClient(
        base_url="http://engine", api_key="secret", transport=httpx.MockTransport(seq)
    ) as client:
        await client.get_ohlcv("S50M2026", "5m", adjusted=False, limit=10)
    assert seq.calls[0].headers.get("X-API-Key") == "secret"


async def test_no_api_key_omits_header() -> None:
    seq = _Sequencer([httpx.Response(200, json=_ohlcv_json())])
    async with MarketDataEngineClient(
        base_url="http://engine", transport=httpx.MockTransport(seq)
    ) as client:
        await client.get_ohlcv("S50M2026", "5m", adjusted=False, limit=10)
    assert "X-API-Key" not in seq.calls[0].headers


# ---------------------------------------------------------------------------
# Empty / partial range
# ---------------------------------------------------------------------------


async def test_empty_bars_is_ok() -> None:
    body = {"symbol": "S50M2026", "timeframe": "5m", "adjusted": False, "bars": []}
    seq = _Sequencer([httpx.Response(200, json=body)])
    async with MarketDataEngineClient(
        base_url="http://engine", transport=httpx.MockTransport(seq)
    ) as client:
        resp = await client.get_ohlcv("S50M2026", "5m", adjusted=False, limit=10)
    assert resp.bars == []


async def test_open_interest_null_is_parsed() -> None:
    seq = _Sequencer([httpx.Response(200, json=_ohlcv_json(open_interest=None))])
    async with MarketDataEngineClient(
        base_url="http://engine", transport=httpx.MockTransport(seq)
    ) as client:
        resp = await client.get_ohlcv("SET:PTT", "5m", adjusted=False, limit=10)
    assert resp.bars[0].open_interest is None


# ---------------------------------------------------------------------------
# 4xx terminal — no retry
# ---------------------------------------------------------------------------


async def test_401_is_terminal_no_retry() -> None:
    seq = _Sequencer([httpx.Response(401, text="bad key")])
    async with MarketDataEngineClient(
        base_url="http://engine", transport=httpx.MockTransport(seq)
    ) as client:
        with pytest.raises(MarketDataEngineError, match="401"):
            await client.get_ohlcv("S50M2026", "5m", adjusted=False, limit=10)
    assert len(seq.calls) == 1


async def test_422_is_terminal_no_retry() -> None:
    seq = _Sequencer([httpx.Response(422, text="bad timeframe")])
    async with MarketDataEngineClient(
        base_url="http://engine", transport=httpx.MockTransport(seq)
    ) as client:
        with pytest.raises(MarketDataEngineError, match="422"):
            await client.get_ohlcv("S50M2026", "5m", adjusted=False, limit=10)
    assert len(seq.calls) == 1


# ---------------------------------------------------------------------------
# 5xx + transport — retried; eventual failure raises
# ---------------------------------------------------------------------------


async def test_retries_on_5xx_then_succeeds() -> None:
    seq = _Sequencer(
        [
            httpx.Response(503, text="overloaded"),
            httpx.Response(502, text="bad gateway"),
            httpx.Response(200, json=_ohlcv_json()),
        ]
    )
    async with MarketDataEngineClient(
        base_url="http://engine",
        transport=httpx.MockTransport(seq),
        backoff_seconds=(0.0, 0.0, 0.0),
    ) as client:
        resp = await client.get_ohlcv("S50M2026", "5m", adjusted=False, limit=10)
    assert len(seq.calls) == 3
    assert len(resp.bars) == 1


async def test_5xx_exhausts_attempts_then_raises() -> None:
    seq = _Sequencer(
        [
            httpx.Response(500, text="boom"),
            httpx.Response(502, text="boom"),
            httpx.Response(503, text="boom"),
        ]
    )
    async with MarketDataEngineClient(
        base_url="http://engine",
        transport=httpx.MockTransport(seq),
        backoff_seconds=(0.0, 0.0, 0.0),
    ) as client:
        with pytest.raises(MarketDataEngineError, match="failed after 3 attempts"):
            await client.get_ohlcv("S50M2026", "5m", adjusted=False, limit=10)
    assert len(seq.calls) == 3


async def test_transport_error_is_retried() -> None:
    seq = _Sequencer([httpx.ConnectError, httpx.Response(200, json=_ohlcv_json())])
    async with MarketDataEngineClient(
        base_url="http://engine",
        transport=httpx.MockTransport(seq),
        backoff_seconds=(0.0, 0.0),
    ) as client:
        resp = await client.get_ohlcv("S50M2026", "5m", adjusted=False, limit=10)
    assert len(seq.calls) == 2
    assert len(resp.bars) == 1


async def test_unparseable_body_raises() -> None:
    seq = _Sequencer([httpx.Response(200, content=b"not json")])
    async with MarketDataEngineClient(
        base_url="http://engine", transport=httpx.MockTransport(seq)
    ) as client:
        with pytest.raises(MarketDataEngineError, match="unparseable"):
            await client.get_ohlcv("S50M2026", "5m", adjusted=False, limit=10)


async def test_malformed_schema_body_raises() -> None:
    # Valid JSON, wrong shape (missing 'bars').
    seq = _Sequencer([httpx.Response(200, content=json.dumps({"symbol": "x"}).encode())])
    async with MarketDataEngineClient(
        base_url="http://engine", transport=httpx.MockTransport(seq)
    ) as client:
        with pytest.raises(MarketDataEngineError, match="unparseable"):
            await client.get_ohlcv("S50M2026", "5m", adjusted=False, limit=10)
