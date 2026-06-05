"""Fetch S501! 1H adjusted bars from the Market Data Engine (direct, port 8300),
build 1D bars via resampling, and write both to ParquetStore.

The engine has 1H data back to 2016 but no 1D route — so we derive Daily bars
from 1H by aggregating OHLCV per BKK trading day.

Run: uv run python scripts/fetch_engine_continuous.py
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import polars as pl

from tfex_s50_multi_tf_swing.adapters.market_data_engine_client import MarketDataEngineClient
from tfex_s50_multi_tf_swing.config.settings import get_settings
from tfex_s50_multi_tf_swing.data.store import ParquetStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ENGINE_SYMBOL = "TFEX:S501!"
BATCH_SIZE = 5000
ENGINE_URL = "http://localhost:8300"


def _bars_to_df(bars: list, timeframe: str) -> pl.DataFrame:
    """Convert EngineOHLCVBar list to a continuous-frame Polars DataFrame."""
    if not bars:
        return pl.DataFrame(
            schema={
                "time": pl.Datetime(time_unit="us", time_zone="UTC"),
                "timeframe": pl.Utf8(),
                "open": pl.Decimal(18, 4),
                "high": pl.Decimal(18, 4),
                "low": pl.Decimal(18, 4),
                "close": pl.Decimal(18, 4),
                "volume": pl.Decimal(18, 4),
                "contract_at_time": pl.Utf8(),
                "adjustment_factor": pl.Decimal(18, 8),
            }
        )

    rows = []
    for b in bars:
        rows.append(
            {
                "time": b.ts,
                "timeframe": timeframe,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
                "contract_at_time": "S501!",
                "adjustment_factor": Decimal("1.0"),
            }
        )
    return pl.DataFrame(rows).sort("time")


def _resample_1h_to_1d(df_1h: pl.DataFrame) -> pl.DataFrame:
    """Resample 1H bars to 1D (Daily) bars by BKK trading day.

    Group bars by UTC date (BKK trading day = UTC+7, so the BKK day boundary
    is 17:00 UTC the previous day). We approximate by grouping by UTC date
    (good enough for Daily bars — a bar straddling midnight UTC is rare for
    TFEX which trades BKK daytime + night).
    """
    # Cast Decimal columns to Float64 for aggregation, then back to Decimal
    df = df_1h.with_columns(
        pl.col("open", "high", "low", "close", "volume").cast(pl.Float64),
        pl.col("time").dt.date().alias("date"),
    )

    daily = (
        df.group_by("date")
        .agg(
            [
                pl.col("open").first().alias("open"),
                pl.col("high").max().alias("high"),
                pl.col("low").min().alias("low"),
                pl.col("close").last().alias("close"),
                pl.col("volume").sum().alias("volume"),
                pl.col("time").first().alias("time"),
            ]
        )
        .sort("date")
    )

    # Convert back to Decimal and add continuous-frame columns
    result = daily.select(
        pl.col("time"),
        pl.lit("1d").alias("timeframe"),
        pl.col("open", "high", "low", "close", "volume").cast(pl.Decimal(18, 4)),
        pl.lit("S501!").alias("contract_at_time"),
        pl.lit(Decimal("1.0")).cast(pl.Decimal(18, 8)).alias("adjustment_factor"),
    )
    return result


async def _fetch_all(client: MarketDataEngineClient, timeframe: str) -> list:
    """Fetch all available bars by paginating **forward** with the ``start`` param.

    The engine's ``start`` param filters bars ``>= start`` (ascending); its ``end``
    param is ignored, so we walk forward: each page begins just after the newest bar
    of the previous page. This unlocks the full 2016 -> 2026 history (the prior
    ``end``-based walker returned the same oldest page every time and stalled at ~5k bars).
    """
    all_bars: list = []
    cursor = datetime(2016, 1, 1, tzinfo=UTC)

    while True:
        resp = await client.get_ohlcv(
            symbol=ENGINE_SYMBOL,
            timeframe=timeframe,  # type: ignore[arg-type]
            adjusted=True,
            limit=BATCH_SIZE,
            start=cursor,
        )
        bars = resp.bars
        if not bars:
            break
        newest = bars[-1].ts
        # Guard against a non-advancing page (would otherwise loop forever).
        if newest < cursor:
            break
        logger.info(
            "Fetched %d bars (start=%s, newest=%s)",
            len(bars),
            cursor.isoformat(),
            newest.isoformat(),
        )
        all_bars.extend(bars)
        cursor = newest + timedelta(microseconds=1)  # next page begins just after the newest bar
        if len(bars) < BATCH_SIZE:
            break  # last (partial) page reached the end of history

    logger.info("Total %s bars: %d", timeframe, len(all_bars))
    return all_bars


async def main() -> None:
    settings = get_settings()
    store = ParquetStore(settings.data_dir)

    async with MarketDataEngineClient(base_url=ENGINE_URL, api_key=None) as client:
        # Fetch 1H bars
        bars_1h = await _fetch_all(client, "1h")
        df_1h = _bars_to_df(bars_1h, "1h")
        store.write_continuous("1h", df_1h)
        logger.info(
            "Wrote continuous 1h: %d bars, %s → %s",
            df_1h.height,
            df_1h["time"][0] if df_1h.height > 0 else "N/A",
            df_1h["time"][-1] if df_1h.height > 0 else "N/A",
        )

        # Build 1D from 1H resampling
        df_1d = _resample_1h_to_1d(df_1h)
        store.write_continuous("1d", df_1d)
        logger.info(
            "Wrote continuous 1d: %d bars, %s → %s",
            df_1d.height,
            df_1d["time"][0] if df_1d.height > 0 else "N/A",
            df_1d["time"][-1] if df_1d.height > 0 else "N/A",
        )

    # Verify
    for tf in ["1h", "1d"]:
        read = store.read_continuous(tf)
        logger.info("Verify continuous %s: %d bars", tf, read.height)


if __name__ == "__main__":
    asyncio.run(main())
