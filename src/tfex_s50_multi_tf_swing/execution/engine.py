"""5m execution engine (ROADMAP §5.4).

:func:`simulate_trade` turns one :class:`~tfex_s50_multi_tf_swing.signals.models.SetupSignal`
into a :class:`~tfex_s50_multi_tf_swing.execution.models.Trade` by walking forward over 5m bars:

* **Entry** fills at the **next bar's open** after the trigger bar — never the trigger bar
  itself, so there is no same-bar look-ahead. The entry bar is rejected if its range (a spread
  proxy) exceeds ``max_spread_mult × median``.
* **Stop** is structure-and-volatility-aware: ``entry − k·ATR`` clamped to the signal's
  ``stop_reference`` (the structure invalidation), whichever is further from entry.
* **Take profit** is hybrid: at ``partial_tp_r`` (1R) bank ``partial_fraction`` (50 %) and move
  the stop to breakeven; the remainder trails ``trail_atr_mult·ATR`` behind the best close.
* **Time stop** exits after ``time_stop_bars`` with no target; otherwise the trade closes at the
  last bar (``end_of_data``).

The per-trade forward scan is **bounded by ``time_stop_bars``** → O(N) per trade, never O(n²).
The engine is **source-agnostic** on the bars: tests / the demo pass the continuous
(back-adjusted) series for simplicity, but the live / Phase-8 path passes the **raw per-contract**
series so roll costs stay honest (hard rule #3). PnL is in **points + R-multiples** only — the
THB multiplier (Phase 7) and cost model (Phase 8) are out of scope.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from decimal import Decimal

import polars as pl

from tfex_s50_multi_tf_swing.execution.errors import ExecutionInputError
from tfex_s50_multi_tf_swing.execution.models import ExecutionConfig, ExitReason, Trade
from tfex_s50_multi_tf_swing.signals.models import SetupSignal

logger = logging.getLogger(__name__)

_REQUIRED_COLUMNS: tuple[str, ...] = ("time", "open", "high", "low", "close", "atr")


@dataclass(frozen=True)
class _Bars:
    """Column-major float view of the bars frame, plus a time → index map."""

    time: list[object]
    open: list[float]
    high: list[float]
    low: list[float]
    close: list[float]
    atr: list[float | None]
    index_of: dict[object, int]

    def __len__(self) -> int:
        return len(self.time)


@dataclass(frozen=True)
class _Exit:
    """The resolved exit of the forward walk."""

    index: int
    price: float
    reason: ExitReason
    partial_done: bool


def simulate_trade(
    signal: SetupSignal, bars: pl.DataFrame, *, config: ExecutionConfig | None = None
) -> Trade | None:
    """Simulate one trade from ``signal`` over ``bars``; ``None`` if it cannot be entered."""
    config = config or ExecutionConfig()
    frame = _prepare(bars)
    fill = _fill_index(frame, signal.time)
    if fill is None:
        return None
    if _spread_rejected(frame, fill, config):
        logger.info("entry rejected at %s: bar range exceeds spread cap", signal.time)
        return None
    atr_entry = frame.atr[fill]
    if atr_entry is None or atr_entry <= 0.0:
        return None

    is_long = signal.direction == "long"
    entry = frame.open[fill]
    stop = _initial_stop(entry, float(signal.stop_reference), atr_entry, config, is_long=is_long)
    risk = abs(entry - stop)
    if risk <= 0.0:
        return None
    target = entry + (risk if is_long else -risk) * config.partial_tp_r

    exit_ = _walk_forward(frame, fill, entry, stop, target, atr_entry, config, is_long=is_long)
    return _build_trade(signal, frame, fill, entry, stop, risk, exit_, config, is_long=is_long)


def simulate_signals(
    signals: list[SetupSignal], bars: pl.DataFrame, *, config: ExecutionConfig | None = None
) -> list[Trade]:
    """Simulate every signal independently, dropping any that cannot be entered."""
    config = config or ExecutionConfig()
    trades: list[Trade] = []
    for signal in signals:
        trade = simulate_trade(signal, bars, config=config)
        if trade is not None:
            trades.append(trade)
    return trades


def _prepare(bars: pl.DataFrame) -> _Bars:
    missing = [c for c in _REQUIRED_COLUMNS if c not in bars.columns]
    if missing:
        raise ExecutionInputError(f"bars frame missing columns: {sorted(missing)}")
    df = bars.sort("time").with_columns(
        pl.col("open").cast(pl.Float64),
        pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64),
        pl.col("close").cast(pl.Float64),
        pl.col("atr").cast(pl.Float64),
    )
    times = df.get_column("time").to_list()
    return _Bars(
        time=times,
        open=df.get_column("open").to_list(),
        high=df.get_column("high").to_list(),
        low=df.get_column("low").to_list(),
        close=df.get_column("close").to_list(),
        atr=df.get_column("atr").to_list(),
        index_of={t: i for i, t in enumerate(times)},
    )


def _fill_index(frame: _Bars, trigger_time: object) -> int | None:
    """Index of the entry (fill) bar — the bar after the trigger; ``None`` if unfillable."""
    trigger = frame.index_of.get(trigger_time)
    if trigger is None or trigger + 1 >= len(frame):
        return None
    return trigger + 1


def _spread_rejected(frame: _Bars, fill: int, config: ExecutionConfig) -> bool:
    ranges = [hi - lo for hi, lo in zip(frame.high, frame.low, strict=True)]
    median = statistics.median(ranges) if ranges else 0.0
    if median <= 0.0:
        return False
    return (frame.high[fill] - frame.low[fill]) > config.max_spread_mult * median


def _initial_stop(
    entry: float, stop_reference: float, atr: float, config: ExecutionConfig, *, is_long: bool
) -> float:
    """``entry − k·ATR`` clamped to the structure invalidation (further from entry wins)."""
    atr_stop = entry - config.k_atr_stop * atr if is_long else entry + config.k_atr_stop * atr
    return min(atr_stop, stop_reference) if is_long else max(atr_stop, stop_reference)


def _walk_forward(
    frame: _Bars,
    fill: int,
    entry: float,
    stop: float,
    target: float,
    atr: float,
    config: ExecutionConfig,
    *,
    is_long: bool,
) -> _Exit:
    """Walk bars from the fill bar; resolve stop / target+trail / breakeven / time stop."""
    stop_level = stop
    partial_done = False
    best = entry
    last = len(frame) - 1
    for j in range(fill, len(frame)):
        held = j - fill
        hi, lo, cl = frame.high[j], frame.low[j], frame.close[j]
        if (is_long and lo <= stop_level) or (not is_long and hi >= stop_level):
            reason: ExitReason = "trailing_stop" if partial_done else "stop_loss"
            return _Exit(j, stop_level, reason, partial_done)
        if not partial_done and ((is_long and hi >= target) or (not is_long and lo <= target)):
            if config.partial_fraction >= 1.0:
                return _Exit(j, target, "take_profit", partial_done=False)
            partial_done = True
            buffer = config.breakeven_buffer if is_long else -config.breakeven_buffer
            stop_level = entry + buffer
            best = cl
        elif partial_done:
            best = max(best, cl) if is_long else min(best, cl)
            offset = config.trail_atr_mult * atr
            trail = best - offset if is_long else best + offset
            stop_level = max(stop_level, trail) if is_long else min(stop_level, trail)
        if held >= config.time_stop_bars:
            return _Exit(j, cl, "time_stop", partial_done)
    return _Exit(last, frame.close[last], "end_of_data", partial_done)


def _build_trade(
    signal: SetupSignal,
    frame: _Bars,
    fill: int,
    entry: float,
    stop: float,
    risk: float,
    exit_: _Exit,
    config: ExecutionConfig,
    *,
    is_long: bool,
) -> Trade:
    """Assemble the :class:`Trade`, folding the partial + remainder legs into ``pnl_points``."""
    target = entry + (risk if is_long else -risk) * config.partial_tp_r
    if exit_.partial_done:
        realized = config.partial_fraction * _dir_pnl(target, entry, is_long=is_long)
        rem_fraction = 1.0 - config.partial_fraction
    else:
        realized = 0.0
        rem_fraction = 1.0
    pnl_points = realized + rem_fraction * _dir_pnl(exit_.price, entry, is_long=is_long)
    return Trade(
        strategy_id=signal.strategy_id,
        direction=signal.direction,
        entry_time=frame.time[fill],  # type: ignore[arg-type]
        exit_time=frame.time[exit_.index],  # type: ignore[arg-type]
        entry=Decimal(str(entry)),
        stop=Decimal(str(stop)),
        exit_price=Decimal(str(exit_.price)),
        pnl_points=Decimal(str(pnl_points)),
        r_multiple=Decimal(str(pnl_points / risk)),
        bars_held=exit_.index - fill,
        exit_reason=exit_.reason,
        regime=signal.regime,
    )


def _dir_pnl(price: float, entry: float, *, is_long: bool) -> float:
    return price - entry if is_long else entry - price


__all__: list[str] = ["simulate_signals", "simulate_trade"]
