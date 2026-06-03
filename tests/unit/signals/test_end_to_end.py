"""End-to-end integration: panels → inputs → setup → signal → execution → backtest.

This is the chain the task brief asks for, minus the explicitly-deferred ``risk/`` sizing
(Phase 7) and gateway ingestion (later pipeline phase). Two paths are exercised:

* a **deterministic** chain on a hand-built aligned row that fires Strategy A, asserting a
  ``Trade`` flows all the way to a ``BacktestMetrics``;
* a **pipeline** chain that builds the aligned inputs from synthetic continuous frames via
  :func:`build_signal_inputs` and runs Strategy C, asserting the harness runs and returns a
  well-formed report (signal count is data-dependent, so only the shape is asserted).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from tests.unit.features.conftest import ohlcv
from tests.unit.signals.conftest import LONG_BASE, frame, to_row
from tests.unit.signals.test_inputs import _SMALL
from tfex_s50_multi_tf_swing.backtest.models import BacktestMetrics
from tfex_s50_multi_tf_swing.backtest.per_strategy import run_per_strategy_backtest
from tfex_s50_multi_tf_swing.data.models import Timeframe
from tfex_s50_multi_tf_swing.execution.models import ExecutionConfig
from tfex_s50_multi_tf_swing.features.indicators import atr
from tfex_s50_multi_tf_swing.signals import strategy_a, strategy_c
from tfex_s50_multi_tf_swing.signals.inputs import build_signal_inputs

_T0 = datetime(2026, 1, 5, 3, 0, tzinfo=UTC)
_BAR_SCHEMA: dict[str, pl.DataType] = {
    "time": pl.Datetime(time_unit="us", time_zone="UTC"),
    "open": pl.Float64(),
    "high": pl.Float64(),
    "low": pl.Float64(),
    "close": pl.Float64(),
    "atr": pl.Float64(),
}


def _bars() -> pl.DataFrame:
    # trigger @ t0 (matches LONG_BASE.time), entry @ t0+5m, stop hit @ t0+10m.
    ohlc = [(100, 101, 99, 100), (100, 101, 99, 100), (99, 99, 96, 97)]
    rows = [
        {
            "time": _T0 + timedelta(minutes=5 * i),
            "open": o,
            "high": h,
            "low": low,
            "close": c,
            "atr": 2.0,
        }
        for i, (o, h, low, c) in enumerate(ohlc)
    ]
    return pl.DataFrame(rows, schema=_BAR_SCHEMA)


def test_deterministic_chain_strategy_a() -> None:
    inputs = frame([to_row(LONG_BASE)])
    metrics = run_per_strategy_backtest(
        lambda df: strategy_a.to_signals(strategy_a.classify_frame(df)),
        inputs,
        _bars(),
        strategy_id="A",
    )
    assert isinstance(metrics, BacktestMetrics)
    assert metrics.n_trades == 1
    assert metrics.per_regime["trend_up"].n_trades == 1


def test_pipeline_chain_runs_strategy_c() -> None:
    frames: dict[Timeframe, pl.DataFrame] = {
        "5m": ohlcv(n=120, interval_minutes=5),
        "1h": ohlcv(n=60, interval_minutes=60),
        "4h": ohlcv(n=40, interval_minutes=240),
    }
    inputs = build_signal_inputs(frames, feature_config=_SMALL)
    bars = frames["5m"].with_columns(
        pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64),
        pl.col("close").cast(pl.Float64),
    )
    bars = bars.with_columns(atr(5).alias("atr"))
    metrics = run_per_strategy_backtest(
        lambda df: strategy_c.to_signals(strategy_c.classify_frame(df)),
        inputs,
        bars,
        strategy_id="C",
        config=ExecutionConfig(time_stop_bars=6),
    )
    assert isinstance(metrics, BacktestMetrics)
    assert metrics.n_trades >= 0
