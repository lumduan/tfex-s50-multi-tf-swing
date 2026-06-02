"""Tests for ``tfex_s50_multi_tf_swing.data.engine_fetcher``."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import polars as pl
import pytest

from tfex_s50_multi_tf_swing.adapters.errors import MarketDataEngineError
from tfex_s50_multi_tf_swing.adapters.market_data_engine_client import (
    EngineOHLCVBar,
    EngineOHLCVResponse,
)
from tfex_s50_multi_tf_swing.data import engine_fetcher
from tfex_s50_multi_tf_swing.data.engine_fetcher import EngineOhlcvFetcher, engine_timeframe
from tfex_s50_multi_tf_swing.data.errors import (
    EngineTimeframeUnavailableError,
    FetcherError,
)

_START = datetime(2026, 3, 2, tzinfo=UTC)
_END = datetime(2026, 3, 5, tzinfo=UTC)
_RAW_COLS = ["time", "open", "high", "low", "close", "volume", "open_interest"]


def _bar(
    ts: datetime,
    *,
    open_: str = "812.100000",
    oi: str | None = "1000.0000",
) -> EngineOHLCVBar:
    return EngineOHLCVBar(
        ts=ts,
        open=Decimal(open_),
        high=Decimal("813.000000"),
        low=Decimal("811.000000"),
        close=Decimal(open_),
        volume=Decimal("1500.0000"),
        open_interest=Decimal(oi) if oi is not None else None,
    )


def _resp(bars: list[EngineOHLCVBar], *, symbol: str = "S50M2026") -> EngineOHLCVResponse:
    return EngineOHLCVResponse(symbol=symbol, timeframe="5m", adjusted=False, bars=bars)


def _install_fake(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: EngineOHLCVResponse | None = None,
    raise_exc: BaseException | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Replace the client with a fake; return a record of init/get calls."""
    calls: dict[str, list[dict[str, Any]]] = {"init": [], "get": []}

    class _FakeClient:
        def __init__(self, *, base_url: str, api_key: str | None = None, **_kw: object) -> None:
            calls["init"].append({"base_url": base_url, "api_key": api_key})

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def get_ohlcv(
            self,
            symbol: str,
            timeframe: str,
            *,
            adjusted: bool,
            limit: int,
            start: datetime | None = None,
            end: datetime | None = None,
        ) -> EngineOHLCVResponse:
            calls["get"].append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "adjusted": adjusted,
                    "limit": limit,
                    "start": start,
                    "end": end,
                }
            )
            if raise_exc is not None:
                raise raise_exc
            assert response is not None
            return response

    monkeypatch.setattr(engine_fetcher, "MarketDataEngineClient", _FakeClient)
    return calls


# ---------------------------------------------------------------------------
# engine_timeframe mapping
# ---------------------------------------------------------------------------


def test_engine_timeframe_maps_known() -> None:
    assert engine_timeframe("5m") == "5m"
    assert engine_timeframe("1h") == "1h"


def test_engine_timeframe_4h_raises() -> None:
    with pytest.raises(EngineTimeframeUnavailableError, match="4h"):
        engine_timeframe("4h")


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


def test_requires_base_url() -> None:
    with pytest.raises(FetcherError, match="base_url"):
        EngineOhlcvFetcher(base_url="")


def test_requires_positive_concurrency() -> None:
    with pytest.raises(FetcherError, match="concurrency"):
        EngineOhlcvFetcher(base_url="http://engine", concurrency=0)


# ---------------------------------------------------------------------------
# fetch_contract — shape, casting, window, symbol mapping
# ---------------------------------------------------------------------------


async def test_fetch_contract_returns_raw_frame_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(monkeypatch, response=_resp([_bar(datetime(2026, 3, 3, tzinfo=UTC))]))
    fetcher = EngineOhlcvFetcher(base_url="http://engine")
    df = await fetcher.fetch_contract(
        contract_code="S50M2026", timeframe="5m", start=_START, end=_END
    )
    assert df.columns == _RAW_COLS
    assert df.schema["time"] == pl.Datetime(time_unit="us", time_zone="UTC")
    for col in ("open", "high", "low", "close", "volume", "open_interest"):
        assert df.schema[col] == pl.Decimal(18, 4)
    assert df.height == 1


async def test_decimal_18_6_engine_cast_to_18_4(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(
        monkeypatch,
        response=_resp([_bar(datetime(2026, 3, 3, tzinfo=UTC), open_="812.123456")]),
    )
    fetcher = EngineOhlcvFetcher(base_url="http://engine")
    df = await fetcher.fetch_contract(
        contract_code="S50M2026", timeframe="5m", start=_START, end=_END
    )
    # 812.123456 quantized half-even to 4 dp → 812.1235.
    assert df["open"].to_list()[0] == Decimal("812.1235")


async def test_open_interest_present_for_futures(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(
        monkeypatch,
        response=_resp([_bar(datetime(2026, 3, 3, tzinfo=UTC), oi="4200.0000")]),
    )
    fetcher = EngineOhlcvFetcher(base_url="http://engine")
    df = await fetcher.fetch_contract(
        contract_code="S50M2026", timeframe="5m", start=_START, end=_END
    )
    assert df["open_interest"].to_list()[0] == Decimal("4200.0000")


async def test_open_interest_null_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(
        monkeypatch,
        response=_resp([_bar(datetime(2026, 3, 3, tzinfo=UTC), oi=None)]),
    )
    fetcher = EngineOhlcvFetcher(base_url="http://engine")
    df = await fetcher.fetch_contract(
        contract_code="S50M2026", timeframe="5m", start=_START, end=_END
    )
    assert df["open_interest"].to_list()[0] is None


async def test_window_filtered_to_start_end(monkeypatch: pytest.MonkeyPatch) -> None:
    bars = [
        _bar(datetime(2026, 3, 1, tzinfo=UTC)),  # before start — excluded
        _bar(datetime(2026, 3, 3, tzinfo=UTC)),  # in window
        _bar(datetime(2026, 3, 5, tzinfo=UTC)),  # == end (exclusive) — excluded
        _bar(datetime(2026, 3, 6, tzinfo=UTC)),  # after end — excluded
    ]
    _install_fake(monkeypatch, response=_resp(bars))
    fetcher = EngineOhlcvFetcher(base_url="http://engine")
    df = await fetcher.fetch_contract(
        contract_code="S50M2026", timeframe="5m", start=_START, end=_END
    )
    assert df.height == 1
    assert df["time"].to_list()[0] == datetime(2026, 3, 3, tzinfo=UTC)


async def test_symbol_and_params_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake(monkeypatch, response=_resp([_bar(datetime(2026, 3, 3, tzinfo=UTC))]))
    fetcher = EngineOhlcvFetcher(base_url="http://engine", api_key="k")
    await fetcher.fetch_contract(contract_code="S50M2026", timeframe="5m", start=_START, end=_END)
    assert calls["init"][0] == {"base_url": "http://engine", "api_key": "k"}
    get = calls["get"][0]
    assert get["symbol"] == "S50M2026"
    assert get["timeframe"] == "5m"
    assert get["adjusted"] is False  # always raw on the engine source
    assert get["start"] == _START
    assert get["end"] == _END


async def test_empty_response_is_empty_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(monkeypatch, response=_resp([]))
    fetcher = EngineOhlcvFetcher(base_url="http://engine")
    df = await fetcher.fetch_contract(
        contract_code="S50M2026", timeframe="5m", start=_START, end=_END
    )
    assert df.height == 0
    assert df.columns == _RAW_COLS


# ---------------------------------------------------------------------------
# 4h declines BEFORE any I/O
# ---------------------------------------------------------------------------


async def test_4h_raises_before_any_io(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake(monkeypatch, response=_resp([]))
    fetcher = EngineOhlcvFetcher(base_url="http://engine")
    with pytest.raises(EngineTimeframeUnavailableError):
        await fetcher.fetch_contract(
            contract_code="S50M2026", timeframe="4h", start=_START, end=_END
        )
    assert calls["init"] == []  # the client was never constructed
    assert calls["get"] == []


# ---------------------------------------------------------------------------
# Window guards
# ---------------------------------------------------------------------------


async def test_naive_window_raises() -> None:
    fetcher = EngineOhlcvFetcher(base_url="http://engine")
    with pytest.raises(FetcherError, match="UTC"):
        await fetcher.fetch_contract(
            contract_code="S50M2026",
            timeframe="5m",
            start=datetime(2026, 3, 2),  # naive
            end=_END,
        )


async def test_start_not_before_end_raises() -> None:
    fetcher = EngineOhlcvFetcher(base_url="http://engine")
    with pytest.raises(FetcherError, match="start must be"):
        await fetcher.fetch_contract(
            contract_code="S50M2026", timeframe="5m", start=_END, end=_START
        )


# ---------------------------------------------------------------------------
# Upstream failure propagates
# ---------------------------------------------------------------------------


async def test_engine_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(monkeypatch, raise_exc=MarketDataEngineError("upstream down"))
    fetcher = EngineOhlcvFetcher(base_url="http://engine")
    with pytest.raises(MarketDataEngineError, match="upstream down"):
        await fetcher.fetch_contract(
            contract_code="S50M2026", timeframe="5m", start=_START, end=_END
        )


# ---------------------------------------------------------------------------
# Continuous reference is the interim empty frame
# ---------------------------------------------------------------------------


async def test_fetch_continuous_reference_returns_empty_frame() -> None:
    fetcher = EngineOhlcvFetcher(base_url="http://engine")
    ref = await fetcher.fetch_continuous_reference(timeframe="5m", start=_START, end=_END)
    assert ref.height == 0
    assert ref.columns == ["time", "open", "high", "low", "close", "volume"]
