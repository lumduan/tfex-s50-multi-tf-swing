"""Source-agnostic OHLCV loader for the walk-forward harness (ROADMAP §8.1).

Walk-forward reads OHLCV from the **Market Data Engine** (the ``engine`` source via the gateway
proxy) or — for heavy full-history columnar scans — the engine's offline **Parquet snapshot**
(:class:`~tfex_s50_multi_tf_swing.data.store.ParquetStore`), which stays usable even when infra-db
/ the gateway is down. It **never** falls back to a per-strategy tvkit fetch (that boundary is
hard). When a required continuous frame is missing or empty this raises
:class:`~tfex_s50_multi_tf_swing.backtest.errors.WalkForwardDataError`.

The live ``engine`` fetch is owned by the refresh pipeline (``data/engine_fetcher.py``), so the
snapshot is engine-sourced; this module only reads the resulting snapshot. ``4h`` is engine-declined
(see the OHLCV-source section in ``CLAUDE.md``); when it is absent the aligned inputs default
``4h_bias_direction`` to ``neutral`` (A/B emit nothing, C still runs).
"""

from __future__ import annotations

import logging

import polars as pl

from tfex_s50_multi_tf_swing.backtest.errors import WalkForwardDataError
from tfex_s50_multi_tf_swing.data.errors import StoreError
from tfex_s50_multi_tf_swing.data.models import Timeframe
from tfex_s50_multi_tf_swing.data.store import ParquetStore
from tfex_s50_multi_tf_swing.features.indicators import atr

logger = logging.getLogger(__name__)

_DEFAULT_ATR_PERIOD = 14


def load_continuous_frames(
    store: ParquetStore, *, with_4h: bool = False
) -> dict[Timeframe, pl.DataFrame]:
    """Read the 5m + 1h (+ optional 4h) continuous snapshot; raise on a missing / empty frame."""
    timeframes: list[Timeframe] = ["5m", "1h"]
    if with_4h:
        timeframes.append("4h")

    frames: dict[Timeframe, pl.DataFrame] = {}
    for tf in timeframes:
        try:
            frame = store.read_continuous(tf)
        except StoreError as exc:
            raise WalkForwardDataError(
                f"continuous {tf} snapshot unavailable at {store.base_dir}: {exc}. "
                "Refresh from the Market Data Engine (engine source) — never tvkit."
            ) from exc
        if frame.is_empty():
            raise WalkForwardDataError(f"continuous {tf} snapshot at {store.base_dir} is empty")
        frames[tf] = frame
    logger.info("loaded continuous snapshot: %s", {tf: f.height for tf, f in frames.items()})
    return frames


def build_execution_bars(
    frame_5m: pl.DataFrame, *, atr_period: int = _DEFAULT_ATR_PERIOD
) -> pl.DataFrame:
    """Cast OHLC to float and append ``atr`` for the execution engine.

    The real run feeds the **raw per-contract** 5m series (TFEX hard rule #3); the synthetic /
    snapshot demonstration uses the back-adjusted continuous as a documented stand-in until a raw
    multi-contract TFEX history exists.
    """
    bars = frame_5m.with_columns(
        pl.col("open").cast(pl.Float64),
        pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64),
        pl.col("close").cast(pl.Float64),
    )
    return bars.with_columns(atr(atr_period).alias("atr"))


__all__: list[str] = ["build_execution_bars", "load_continuous_frames"]
