"""tvkit-backed OHLCV fetcher.

Two entry points:

* :meth:`OhlcvFetcher.fetch_contract` — per-contract bars via the TradingView
  symbol ``TFEX:S50<code><yyyy>``. Used to populate ``data/raw/<contract>/``.
* :meth:`OhlcvFetcher.fetch_continuous_reference` — TradingView's auto-roll
  ``TFEX:S501!``. Used as an external cross-check for our locally-built
  back-adjusted continuous (see
  :meth:`tfex_s50_multi_tf_swing.data.validator.Validator.validate_continuous_against_reference`).

Both entry points are async, retry on transient errors with exponential
backoff, and are concurrency-limited by a shared semaphore. Anonymous tvkit
sessions cap at 5,000 bars per symbol; the 5-year 5m backfill needs the
``TFEX_S50_MULTI_TF_SWING_TVKIT_AUTH_TOKEN`` cookie blob.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

import polars as pl
from pydantic import SecretStr
from tvkit.api.chart import OHLCV
from tvkit.api.chart.exceptions import StreamConnectionError
from tvkit.api.chart.models.ohlcv import OHLCVBar

from tfex_s50_multi_tf_swing.data.contracts import (
    TV_CONTINUOUS_SYMBOL,
    tv_symbol_for_contract,
)
from tfex_s50_multi_tf_swing.data.errors import FetcherError
from tfex_s50_multi_tf_swing.data.models import Timeframe

logger: logging.Logger = logging.getLogger(__name__)

# TFEX is the TradingView exchange prefix for S50 futures.
EXCHANGE_PREFIX: Final[str] = "TFEX"

# Map of project timeframe strings to the TradingView ``interval`` argument.
_TF_INTERVAL: Final[dict[Timeframe, str]] = {
    "5m": "5",
    "1h": "60",
    "4h": "240",
}

# Transient classes worth retrying. Other exceptions raise FetcherError immediately.
_TRANSIENT: Final[tuple[type[BaseException], ...]] = (
    StreamConnectionError,
    asyncio.TimeoutError,
    ConnectionError,
)


class OhlcvFetcher:
    """Async OHLCV fetcher with retry + concurrency limits.

    Construct one fetcher per process. Pass the
    :class:`tfex_s50_multi_tf_swing.config.settings.Settings` so retry knobs
    and auth credentials flow from the env.
    """

    def __init__(
        self,
        *,
        auth_token: SecretStr | None = None,
        concurrency: int = 4,
        max_attempts: int = 3,
        base_backoff_seconds: float = 1.0,
    ) -> None:
        if concurrency < 1:
            raise FetcherError(f"concurrency must be ≥1, got {concurrency}")
        if max_attempts < 1:
            raise FetcherError(f"max_attempts must be ≥1, got {max_attempts}")
        if base_backoff_seconds <= 0:
            raise FetcherError(f"base_backoff_seconds must be > 0, got {base_backoff_seconds}")
        self._auth_token: SecretStr | None = auth_token
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(concurrency)
        self._max_attempts: int = max_attempts
        self._base_backoff: float = base_backoff_seconds

    async def fetch_contract(
        self,
        *,
        contract_code: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> pl.DataFrame:
        """Fetch raw OHLCV for one quarterly contract.

        Args:
            contract_code: Canonical code (e.g. ``"S50H2026"``).
            timeframe: One of ``"5m" / "1h" / "4h"``.
            start: Inclusive UTC start.
            end: Exclusive UTC end.

        Returns:
            A Polars frame with columns
            ``time, open, high, low, close, volume`` and Decimal-typed prices.
            Empty if tvkit returned no bars.
        """
        _require_utc(start, "start")
        _require_utc(end, "end")
        if start >= end:
            raise FetcherError(
                f"start must be < end; got start={start.isoformat()} end={end.isoformat()}"
            )
        symbol = f"{EXCHANGE_PREFIX}:{tv_symbol_for_contract(contract_code)}"
        return await self._fetch_symbol(
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
        )

    async def fetch_continuous_reference(
        self,
        *,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> pl.DataFrame:
        """Fetch TradingView's ``S501!`` auto-roll continuous (cross-check only)."""
        _require_utc(start, "start")
        _require_utc(end, "end")
        if start >= end:
            raise FetcherError(
                f"start must be < end; got start={start.isoformat()} end={end.isoformat()}"
            )
        symbol = f"{EXCHANGE_PREFIX}:{TV_CONTINUOUS_SYMBOL}"
        return await self._fetch_symbol(symbol=symbol, timeframe=timeframe, start=start, end=end)

    # ------------------------------------------------------------------
    # Internal — shared symbol fetch with retry
    # ------------------------------------------------------------------

    async def _fetch_symbol(
        self,
        *,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> pl.DataFrame:
        interval = _TF_INTERVAL[timeframe]
        async with self._semaphore:
            bars: list[OHLCVBar] = []
            for attempt in range(1, self._max_attempts + 1):
                try:
                    bars = await self._fetch_once(
                        symbol=symbol, interval=interval, start=start, end=end
                    )
                    break
                except _TRANSIENT as exc:
                    if attempt == self._max_attempts:
                        raise FetcherError(
                            f"fetch failed after {self._max_attempts} attempts: "
                            f"symbol={symbol!r} interval={interval!r} "
                            f"start={start.isoformat()} end={end.isoformat()} cause={exc!r}"
                        ) from exc
                    backoff: float = self._base_backoff * (2 ** (attempt - 1))
                    logger.warning(
                        "fetcher: transient %s on %s attempt %d/%d; retrying in %.1fs",
                        type(exc).__name__,
                        symbol,
                        attempt,
                        self._max_attempts,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                except Exception as exc:  # noqa: BLE001 — wrap-and-rethrow
                    raise FetcherError(
                        f"non-retryable fetch failure for {symbol!r}: {exc!r}"
                    ) from exc
        if not bars:
            logger.info(
                "fetcher: %s tf=%s returned 0 bars in [%s, %s)",
                symbol,
                timeframe,
                start.isoformat(),
                end.isoformat(),
            )
            return _empty_frame()
        return _bars_to_frame(bars, start=start, end=end)

    async def _fetch_once(
        self,
        *,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> list[OHLCVBar]:
        cookies = _parse_auth_token(self._auth_token)
        async with OHLCV(cookies=cookies) as client:
            bars: list[OHLCVBar] = await client.get_historical_ohlcv(
                symbol,
                interval=interval,
                start=start,
                end=end,
            )
            return bars


# ---------------------------------------------------------------------------
# Helpers (module-private)
# ---------------------------------------------------------------------------


def _require_utc(dt: datetime, name: str) -> None:
    if dt.tzinfo is None:
        raise FetcherError(f"{name} must be timezone-aware UTC; got naive")
    if dt.utcoffset() != UTC.utcoffset(dt):
        raise FetcherError(f"{name} must be UTC; got {dt.tzinfo}")


def _parse_auth_token(token: SecretStr | None) -> dict[str, str] | None:
    if token is None:
        return None
    raw: str = token.get_secret_value()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FetcherError("TVKIT_AUTH_TOKEN must be a JSON object") from exc
    if not isinstance(data, dict):
        raise FetcherError("TVKIT_AUTH_TOKEN must decode to a JSON object")
    return {str(k): str(v) for k, v in data.items()}


def _empty_frame() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "time": pl.Datetime(time_unit="us", time_zone="UTC"),
            "open": pl.Decimal(18, 4),
            "high": pl.Decimal(18, 4),
            "low": pl.Decimal(18, 4),
            "close": pl.Decimal(18, 4),
            "volume": pl.Decimal(18, 4),
        }
    )


def _bars_to_frame(bars: list[OHLCVBar], *, start: datetime, end: datetime) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for bar in bars:
        t = datetime.fromtimestamp(bar.timestamp, tz=UTC)
        if t < start or t >= end:
            continue
        rows.append(
            {
                "time": t,
                "open": _to_decimal(bar.open),
                "high": _to_decimal(bar.high),
                "low": _to_decimal(bar.low),
                "close": _to_decimal(bar.close),
                "volume": _to_decimal(bar.volume),
            }
        )
    if not rows:
        return _empty_frame()
    return (
        pl.DataFrame(rows)
        .with_columns(
            [
                pl.col("time").dt.replace_time_zone("UTC"),
                pl.col("open").cast(pl.Decimal(18, 4)),
                pl.col("high").cast(pl.Decimal(18, 4)),
                pl.col("low").cast(pl.Decimal(18, 4)),
                pl.col("close").cast(pl.Decimal(18, 4)),
                pl.col("volume").cast(pl.Decimal(18, 4)),
            ]
        )
        .sort("time")
    )


def _to_decimal(v: float) -> Decimal:
    return Decimal(f"{v:.4f}")


__all__: list[str] = ["EXCHANGE_PREFIX", "OhlcvFetcher"]
