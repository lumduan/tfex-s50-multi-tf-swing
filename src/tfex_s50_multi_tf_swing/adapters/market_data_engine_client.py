"""Async HTTP client for the Market Data Engine read API.

The Market Data Engine (``quant-marketdata-engine``, host ``:8300``) is the
platform's canonical OHLCV producer and sole tvkit-cookie owner. This client
lets tfex *read* pre-fetched bars from its auth-gated read API
(``GET /ohlcv`` and ``GET /ohlcv/adjusted``), gateway-proxied under
``/api/v2/engines/market-data/*``, instead of fetching tvkit directly — used
when ``TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE='engine'`` (feature-market-data-engine
Phase 4).

The client mirrors :mod:`tfex_s50_multi_tf_swing.adapters.gateway_client`'s
manual-retry semantics: one shared :class:`httpx.AsyncClient`, retries on
transient 5xx + transport errors with bounded backoff, 4xx terminal, parses the
wire's ``Decimal``-as-string prices into :class:`~decimal.Decimal`, and supports
a custom transport for testability. It holds **no tvkit credential** — only an
optional ``X-API-Key`` for the engine's read API, which is never logged.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from decimal import Decimal

import httpx
from pydantic import BaseModel, ConfigDict

from tfex_s50_multi_tf_swing.adapters.errors import MarketDataEngineError

logger: logging.Logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS: float = 30.0
DEFAULT_MAX_ATTEMPTS: int = 3
DEFAULT_BACKOFF_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0)

OHLCV_PATH: str = "/ohlcv"
OHLCV_ADJUSTED_PATH: str = "/ohlcv/adjusted"


class EngineOHLCVBar(BaseModel):
    """One OHLCV bar as returned by the Market Data Engine read API.

    Prices and volume arrive on the wire as decimal strings (never floats);
    Pydantic coerces them to :class:`~decimal.Decimal` here, preserving
    precision at the HTTP boundary. ``ts`` is the bar-open time in UTC;
    ``open_interest`` is ``None`` for equities and present for futures.
    """

    model_config = ConfigDict(frozen=True)

    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    open_interest: Decimal | None = None


class EngineOHLCVResponse(BaseModel):
    """A ``(symbol, timeframe)`` bar series returned by the engine."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: str
    adjusted: bool
    bars: list[EngineOHLCVBar]


class MarketDataEngineClient:
    """Async HTTP client that reads OHLCV from the Market Data Engine.

    Args:
        base_url: Engine read-API base URL as proxied by the gateway (include
            the ``/api/v2/engines/market-data`` prefix), e.g.
            ``http://quant-api-gateway:8000/api/v2/engines/market-data``
            in-cluster or ``http://localhost:8080/api/v2/engines/market-data``
            for host-local dev.
        api_key: Optional shared secret sent as ``X-API-Key``. The engine only
            enforces it when its own ``MARKETDATA_ENGINE_API_KEY`` is set.
        timeout: Per-request timeout in seconds.
        max_attempts: Total GET attempts (initial + retries) on 5xx/transport
            errors.
        backoff_seconds: Sleep durations between retries, indexed by
            ``attempt_index`` (0-based); clamped to the last value when more
            attempts are configured than backoff entries.
        transport: Optional custom :class:`httpx.AsyncBaseTransport` for tests
            (e.g. :class:`httpx.MockTransport`).
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_seconds: tuple[float, ...] = DEFAULT_BACKOFF_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

        self._base_url: str = base_url.rstrip("/")
        self._api_key: str | None = api_key or None
        self._max_attempts: int = max_attempts
        self._backoff: tuple[float, ...] = backoff_seconds or (0.0,)
        self._client: httpx.AsyncClient = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            transport=transport,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client. Idempotent."""
        await self._client.aclose()

    async def __aenter__(self) -> MarketDataEngineClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

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
        """Read a bar series for ``(symbol, timeframe)`` from the engine.

        Routes to ``/ohlcv/adjusted`` when ``adjusted`` is True, else
        ``/ohlcv``. tfex's ``engine`` source always reads raw bars
        (``adjusted=False``) and back-adjusts the continuous locally. Retries
        transient 5xx / transport failures with backoff; 4xx (e.g. 401 auth,
        422 bad params) are terminal.

        Args:
            symbol: Engine symbol, e.g. ``"S50M2026"`` or ``"S501!"``.
            timeframe: Engine timeframe — one of ``"1d"``, ``"1h"``, ``"5m"``.
            adjusted: When True, request adjust-on-read bars.
            limit: Maximum number of bars (engine caps at 50000).
            start: Optional inclusive range start (UTC).
            end: Optional inclusive range end (UTC).

        Returns:
            The parsed :class:`EngineOHLCVResponse` (``bars`` may be empty).

        Raises:
            MarketDataEngineError: On a 4xx, an unparseable body, or after all
                retries are exhausted.
        """
        path: str = OHLCV_ADJUSTED_PATH if adjusted else OHLCV_PATH
        params: dict[str, str | int] = {
            "symbol": symbol,
            "timeframe": timeframe,
            "limit": limit,
        }
        if start is not None:
            params["start"] = start.isoformat()
        if end is not None:
            params["end"] = end.isoformat()
        headers: dict[str, str] = {}
        if self._api_key is not None:
            headers["X-API-Key"] = self._api_key

        last_exc: Exception | None = None
        for attempt in range(self._max_attempts):
            try:
                response = await self._client.get(path, params=params, headers=headers)
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning(
                    "market-data-engine GET %s transport error (attempt %d/%d): %s",
                    path,
                    attempt + 1,
                    self._max_attempts,
                    exc,
                )
            else:
                if response.is_success:
                    try:
                        return EngineOHLCVResponse.model_validate_json(response.content)
                    except ValueError as exc:
                        raise MarketDataEngineError(
                            f"market-data-engine returned an unparseable body for "
                            f"{symbol} {timeframe}: {exc}"
                        ) from exc
                if 400 <= response.status_code < 500:
                    raise MarketDataEngineError(
                        f"market-data-engine rejected {symbol} {timeframe} with "
                        f"{response.status_code}: {response.text[:200]}"
                    )
                last_exc = MarketDataEngineError(
                    f"market-data-engine returned {response.status_code}: {response.text[:200]}"
                )
                logger.warning(
                    "market-data-engine GET %s 5xx (attempt %d/%d): %d",
                    path,
                    attempt + 1,
                    self._max_attempts,
                    response.status_code,
                )

            if attempt + 1 < self._max_attempts:
                sleep_for = self._backoff[min(attempt, len(self._backoff) - 1)]
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)

        raise MarketDataEngineError(
            f"market-data-engine GET for {symbol} {timeframe} failed after "
            f"{self._max_attempts} attempts"
        ) from last_exc


__all__: list[str] = [
    "DEFAULT_BACKOFF_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_TIMEOUT_SECONDS",
    "OHLCV_ADJUSTED_PATH",
    "OHLCV_PATH",
    "EngineOHLCVBar",
    "EngineOHLCVResponse",
    "MarketDataEngineClient",
]
