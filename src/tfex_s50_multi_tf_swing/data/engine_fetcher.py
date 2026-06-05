"""Market Data Engine OHLCV fetcher (the ``engine`` source).

A :class:`~tfex_s50_multi_tf_swing.data.refresh.FetcherProtocol` adapter that
reads RAW per-dated-contract bars from the shared ``quant-marketdata-engine``
read API (gateway-proxied) instead of fetching tvkit. It drops into
``refresh_all(fetcher=...)`` exactly where :class:`OhlcvFetcher` does and returns
the **same** Polars raw-frame shape, so the store → continuous-builder →
validator → db-writer chain is unchanged and source-agnostic.

Two engine limitations are handled here (feature-market-data-engine Phase 4):

* **4h is not served.** The engine read API exposes only ``1d | 1h | 5m``; a
  ``cagg_ohlcv_4h`` aggregate exists but is unrouted. Per Decision D10 coarser
  timeframes must come from continuous aggregates, never a local rollup — so
  :func:`engine_timeframe` declines ``4h`` with a typed error before any I/O.
* **No engine-native back-adjusted continuous.** The engine's futures-roll
  adjust-on-read is unbuilt, so :meth:`fetch_continuous_reference` returns an
  empty frame (``refresh_all`` skips the cross-check) — tfex builds the
  back-adjusted continuous locally from the raw dated-contract bars, the series
  the strategy was validated on.

This fetcher holds **no tvkit credential** — only an optional ``X-API-Key`` for
the engine read API.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

import polars as pl

from tfex_s50_multi_tf_swing.adapters.market_data_engine_client import (
    EngineOHLCVBar,
    MarketDataEngineClient,
)
from tfex_s50_multi_tf_swing.data.contracts import engine_symbol_for_contract
from tfex_s50_multi_tf_swing.data.errors import (
    EngineTimeframeUnavailableError,
    FetcherError,
)
from tfex_s50_multi_tf_swing.data.models import Timeframe

logger: logging.Logger = logging.getLogger(__name__)

# tfex project timeframe → Market Data Engine timeframe literal. The engine
# serves only ``1d | 1h | 5m``; ``4h`` is intentionally absent (see module docs).
_TF_TO_ENGINE: Final[dict[Timeframe, str]] = {"5m": "5m", "1h": "1h", "1d": "1d"}

# Per-request bar cap. The engine bounds at 50000; refresh windows pass explicit
# start/end so this only guards against an unexpectedly huge single-contract span.
_ENGINE_BAR_LIMIT: Final[int] = 50000

_PRICE_SCALE: Final[Decimal] = Decimal("0.0001")


def engine_timeframe(tf: Timeframe) -> str:
    """Map a tfex timeframe to the engine's timeframe literal.

    Raises:
        EngineTimeframeUnavailableError: for ``4h`` — the engine does not route
            its ``cagg_ohlcv_4h`` aggregate, and D10 forbids a local rollup.
    """
    engine_tf = _TF_TO_ENGINE.get(tf)
    if engine_tf is None:
        raise EngineTimeframeUnavailableError(
            f"timeframe {tf!r} is not served by the Market Data Engine read API "
            f"(only {sorted(_TF_TO_ENGINE)!r}); 4h must come from a future engine "
            f"continuous-aggregate route, not a local rollup (Decision D10)."
        )
    return engine_tf


class EngineOhlcvFetcher:
    """Reads raw OHLCV from the Market Data Engine; FetcherProtocol-shaped.

    Args:
        base_url: Engine read-API base URL as proxied by the gateway (includes
            the ``/api/v2/engines/market-data`` prefix).
        api_key: Optional ``X-API-Key`` forwarded to the engine (never logged).
        concurrency: Max concurrent engine reads (one per contract × timeframe).
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        concurrency: int = 4,
    ) -> None:
        if not base_url:
            raise FetcherError("market_data_engine_base_url is required for the engine source")
        if concurrency < 1:
            raise FetcherError(f"concurrency must be ≥1, got {concurrency}")
        self._base_url: str = base_url
        self._api_key: str | None = api_key or None
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(concurrency)

    async def fetch_contract(
        self,
        *,
        contract_code: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> pl.DataFrame:
        """Fetch raw OHLCV for one quarterly contract from the engine.

        Returns a Polars frame with columns
        ``time, open, high, low, close, volume, open_interest`` (Decimal-typed,
        UTC, sorted, window-filtered to ``[start, end)``). Empty if the engine
        returned no bars. Raises :class:`EngineTimeframeUnavailableError` for
        ``4h`` *before* any network call.
        """
        _require_utc(start, "start")
        _require_utc(end, "end")
        if start >= end:
            raise FetcherError(
                f"start must be < end; got start={start.isoformat()} end={end.isoformat()}"
            )
        engine_tf: str = engine_timeframe(timeframe)
        symbol: str = engine_symbol_for_contract(contract_code)

        async with (
            self._semaphore,
            MarketDataEngineClient(base_url=self._base_url, api_key=self._api_key) as client,
        ):
            response = await client.get_ohlcv(
                symbol,
                engine_tf,
                adjusted=False,
                limit=_ENGINE_BAR_LIMIT,
                start=start,
                end=end,
            )

        if not response.bars:
            logger.info(
                "engine-fetcher: %s tf=%s returned 0 bars in [%s, %s)",
                symbol,
                timeframe,
                start.isoformat(),
                end.isoformat(),
            )
            return _empty_raw_frame()
        return _bars_to_frame(response.bars, start=start, end=end)

    async def fetch_continuous_reference(
        self,
        *,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> pl.DataFrame:
        """Return an empty reference frame (interim — engine has no S501! continuous).

        The engine's futures-roll back-adjustment is unbuilt, so there is no
        native ``S501!`` continuous to cross-check against. Returning an empty
        frame makes ``refresh_all`` skip the cross-check cleanly; tfex builds the
        back-adjusted continuous locally from the raw dated-contract bars.
        """
        _require_utc(start, "start")
        _require_utc(end, "end")
        logger.info(
            "engine-fetcher: continuous reference skipped tf=%s "
            "(engine has no native back-adjusted S501!; building continuous locally)",
            timeframe,
        )
        return _empty_reference_frame()


# ---------------------------------------------------------------------------
# Helpers (module-private)
# ---------------------------------------------------------------------------


def _require_utc(dt: datetime, name: str) -> None:
    if dt.tzinfo is None:
        raise FetcherError(f"{name} must be timezone-aware UTC; got naive")
    if dt.utcoffset() != UTC.utcoffset(dt):
        raise FetcherError(f"{name} must be UTC; got {dt.tzinfo}")


def _quantize(value: Decimal) -> Decimal:
    """Quantize an engine Decimal (scale 6) down to the store's scale 4."""
    return value.quantize(_PRICE_SCALE)


def _empty_raw_frame() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "time": pl.Datetime(time_unit="us", time_zone="UTC"),
            "open": pl.Decimal(18, 4),
            "high": pl.Decimal(18, 4),
            "low": pl.Decimal(18, 4),
            "close": pl.Decimal(18, 4),
            "volume": pl.Decimal(18, 4),
            "open_interest": pl.Decimal(18, 4),
        }
    )


def _empty_reference_frame() -> pl.DataFrame:
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


def _bars_to_frame(bars: list[EngineOHLCVBar], *, start: datetime, end: datetime) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for bar in bars:
        t = bar.ts if bar.ts.tzinfo is not None else bar.ts.replace(tzinfo=UTC)
        if t < start or t >= end:
            continue
        rows.append(
            {
                "time": t,
                "open": _quantize(bar.open),
                "high": _quantize(bar.high),
                "low": _quantize(bar.low),
                "close": _quantize(bar.close),
                "volume": _quantize(bar.volume),
                "open_interest": (
                    _quantize(bar.open_interest) if bar.open_interest is not None else None
                ),
            }
        )
    if not rows:
        return _empty_raw_frame()
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
                pl.col("open_interest").cast(pl.Decimal(18, 4)),
            ]
        )
        .sort("time")
    )


__all__: list[str] = ["EngineOhlcvFetcher", "engine_timeframe"]
