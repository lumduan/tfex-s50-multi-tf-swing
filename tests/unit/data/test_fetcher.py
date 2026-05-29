"""Unit tests for :class:`tfex_s50_multi_tf_swing.data.fetcher.OhlcvFetcher`.

The TradingView HTTP / WebSocket surface is mocked at the
:class:`tvkit.api.chart.OHLCV` boundary via :func:`monkeypatch.setattr`, so no
network calls happen.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import polars as pl
import pytest
from pydantic import SecretStr
from tvkit.api.chart.exceptions import StreamConnectionError
from tvkit.api.chart.models.ohlcv import OHLCVBar

from tfex_s50_multi_tf_swing.data.errors import FetcherError
from tfex_s50_multi_tf_swing.data.fetcher import EXCHANGE_PREFIX, OhlcvFetcher

_START = datetime(2026, 5, 27, 0, 0, tzinfo=UTC)
_END = datetime(2026, 5, 27, 3, 0, tzinfo=UTC)


class _FakeClient:
    """Fake tvkit.OHLCV client wired into the fetcher via monkeypatch."""

    def __init__(
        self,
        *,
        bars: list[OHLCVBar] | None = None,
        raise_for_attempts: list[type[BaseException]] | None = None,
        captured_symbols: list[str] | None = None,
    ) -> None:
        self._bars = bars or []
        self._to_raise = list(raise_for_attempts or [])
        self._captured_symbols = captured_symbols if captured_symbols is not None else []

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def get_historical_ohlcv(
        self,
        symbol: str,
        *,
        interval: str,
        start: datetime,
        end: datetime,
        **_kwargs: Any,
    ) -> list[OHLCVBar]:
        self._captured_symbols.append(symbol)
        if self._to_raise:
            exc_type = self._to_raise.pop(0)
            raise exc_type("simulated")
        return self._bars


def _make_bars(n: int) -> list[OHLCVBar]:
    out: list[OHLCVBar] = []
    base = _START.timestamp()
    for i in range(n):
        out.append(
            OHLCVBar(
                timestamp=base + i * 300,
                open=800.0 + i,
                high=801.0 + i,
                low=799.0 + i,
                close=800.5 + i,
                volume=1000.0,
            )
        )
    return out


def _patch_ohlcv(monkeypatch: pytest.MonkeyPatch, client_factory: Any) -> None:
    """Patch ``tvkit.api.chart.OHLCV`` reference inside the fetcher module."""
    import tfex_s50_multi_tf_swing.data.fetcher as fetcher_mod

    monkeypatch.setattr(fetcher_mod, "OHLCV", client_factory, raising=True)


async def test_fetch_contract_returns_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []
    fake = _FakeClient(bars=_make_bars(3), captured_symbols=captured)
    _patch_ohlcv(monkeypatch, lambda **_kw: fake)

    f = OhlcvFetcher()
    df = await f.fetch_contract(contract_code="S50M2026", timeframe="5m", start=_START, end=_END)
    assert df.height == 3
    assert df.columns == ["time", "open", "high", "low", "close", "volume"]
    # contract code → TradingView symbol with TFEX: prefix
    assert captured == [f"{EXCHANGE_PREFIX}:S50M2026"]
    # Decimal precision preserved
    assert df["open"].to_list()[0] == Decimal("800.0000")


async def test_fetch_continuous_uses_s501(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []
    fake = _FakeClient(bars=_make_bars(1), captured_symbols=captured)
    _patch_ohlcv(monkeypatch, lambda **_kw: fake)

    f = OhlcvFetcher()
    df = await f.fetch_continuous_reference(timeframe="1h", start=_START, end=_END)
    assert df.height == 1
    assert captured == [f"{EXCHANGE_PREFIX}:S501!"]


async def test_fetch_retries_on_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []
    fake = _FakeClient(
        bars=_make_bars(2),
        raise_for_attempts=[StreamConnectionError, asyncio.TimeoutError],
        captured_symbols=captured,
    )
    _patch_ohlcv(monkeypatch, lambda **_kw: fake)

    # Speed up backoffs.
    f = OhlcvFetcher(max_attempts=3, base_backoff_seconds=0.001)
    df = await f.fetch_contract(contract_code="S50M2026", timeframe="5m", start=_START, end=_END)
    assert df.height == 2
    assert len(captured) == 3  # two failures + one success


async def test_fetch_raises_after_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(
        raise_for_attempts=[StreamConnectionError, StreamConnectionError, StreamConnectionError]
    )
    _patch_ohlcv(monkeypatch, lambda **_kw: fake)

    f = OhlcvFetcher(max_attempts=3, base_backoff_seconds=0.001)
    with pytest.raises(FetcherError):
        await f.fetch_contract(contract_code="S50M2026", timeframe="5m", start=_START, end=_END)


async def test_fetch_wraps_non_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(raise_for_attempts=[ValueError])  # not transient
    _patch_ohlcv(monkeypatch, lambda **_kw: fake)

    f = OhlcvFetcher(max_attempts=3, base_backoff_seconds=0.001)
    with pytest.raises(FetcherError):
        await f.fetch_contract(contract_code="S50M2026", timeframe="5m", start=_START, end=_END)


async def test_fetch_empty_returns_empty_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(bars=[])
    _patch_ohlcv(monkeypatch, lambda **_kw: fake)

    f = OhlcvFetcher()
    df = await f.fetch_contract(contract_code="S50M2026", timeframe="5m", start=_START, end=_END)
    assert df.height == 0
    assert df.schema["time"] == pl.Datetime(time_unit="us", time_zone="UTC")


def test_constructor_rejects_bad_params() -> None:
    with pytest.raises(FetcherError):
        OhlcvFetcher(concurrency=0)
    with pytest.raises(FetcherError):
        OhlcvFetcher(max_attempts=0)
    with pytest.raises(FetcherError):
        OhlcvFetcher(base_backoff_seconds=0)


def test_auth_token_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class _CaptureClient(_FakeClient):
        def __init__(self, *, cookies: Any = None) -> None:
            super().__init__(bars=_make_bars(1))
            if isinstance(cookies, dict):
                captured.update(cookies)

    _patch_ohlcv(monkeypatch, _CaptureClient)
    f = OhlcvFetcher(auth_token=SecretStr('{"sessionid":"abc","tv_ecuid":"xyz"}'))
    asyncio.get_event_loop().run_until_complete(
        f.fetch_contract(contract_code="S50M2026", timeframe="5m", start=_START, end=_END)
    )
    assert captured == {"sessionid": "abc", "tv_ecuid": "xyz"}


async def test_auth_token_invalid_json_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ohlcv(monkeypatch, lambda **_kw: _FakeClient(bars=_make_bars(1)))
    f = OhlcvFetcher(auth_token=SecretStr("not-json"))
    with pytest.raises(FetcherError):
        await f.fetch_contract(contract_code="S50M2026", timeframe="5m", start=_START, end=_END)


async def test_fetch_rejects_naive_datetimes() -> None:
    f = OhlcvFetcher()
    with pytest.raises(FetcherError):
        await f.fetch_contract(
            contract_code="S50M2026",
            timeframe="5m",
            start=datetime(2026, 5, 27),
            end=_END,
        )


async def test_fetch_rejects_inverted_window() -> None:
    f = OhlcvFetcher()
    with pytest.raises(FetcherError):
        await f.fetch_contract(
            contract_code="S50M2026",
            timeframe="5m",
            start=_END,
            end=_START,
        )


async def test_fetch_continuous_rejects_naive() -> None:
    f = OhlcvFetcher()
    with pytest.raises(FetcherError):
        await f.fetch_continuous_reference(timeframe="5m", start=datetime(2026, 5, 27), end=_END)


async def test_fetch_filters_bars_outside_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars = _make_bars(5)
    # Add a stray bar far in the future
    bars.append(
        OHLCVBar(
            timestamp=datetime(2030, 1, 1, tzinfo=UTC).timestamp(),
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
            volume=1.0,
        )
    )
    fake = _FakeClient(bars=bars)
    _patch_ohlcv(monkeypatch, lambda **_kw: fake)

    f = OhlcvFetcher()
    df = await f.fetch_contract(contract_code="S50M2026", timeframe="5m", start=_START, end=_END)
    # The stray 2030 bar must be filtered out.
    assert df.height == 5
