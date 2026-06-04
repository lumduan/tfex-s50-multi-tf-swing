"""Triple-barrier labelling for the probability filter (ROADMAP §6.1).

Each fired :class:`SetupSignal` is labelled by walking the 5m execution bars forward from
its **next-bar-open** entry (the same no-same-bar-look-ahead convention as
:mod:`tfex_s50_multi_tf_swing.execution.engine`) against three barriers:

* **take-profit** at ``entry ± tp_atr_mult · ATR``,
* **stop-loss** at ``entry ∓ sl_atr_mult · ATR``,
* **time** at ``horizon_bars`` (then labelled by the sign of the realised return).

On a bar that touches both barriers the **stop is assumed first** (conservative — never
optimistically credit the target). The per-target binary label encodes the *economic
hypothesis* each model tests:

* ``trend_continuation`` (gates A / B): ``1`` when the move *held* (TP first, or a positive
  time-exit) — the model learns to keep continuations.
* ``fake_breakout`` (gates C): ``1`` when the breakout *failed* (SL first, or a non-positive
  time-exit) — the model learns to drop fakes.

Labels are :class:`float` statistics that never cross the gateway boundary.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

import polars as pl

from tfex_s50_multi_tf_swing.ml.errors import LabelError
from tfex_s50_multi_tf_swing.ml.models import TripleBarrierConfig, target_for_strategy
from tfex_s50_multi_tf_swing.signals.models import SetupSignal

logger = logging.getLogger(__name__)

_REQUIRED_COLUMNS: tuple[str, ...] = ("time", "open", "high", "low", "close", "atr")

LABEL_SCHEMA: dict[str, pl.DataType] = {
    "strategy_id": pl.Utf8(),
    "time": pl.Datetime(time_unit="us", time_zone="UTC"),
    "direction": pl.Utf8(),
    "target": pl.Utf8(),
    "outcome": pl.Utf8(),
    "label": pl.Int8(),
    "ret": pl.Float64(),
}


def _prepare(
    bars: pl.DataFrame,
) -> tuple[
    list[object], list[float], list[float], list[float], list[float | None], dict[object, int]
]:
    """Column-major float view of the bars + a ``time → index`` map (sorted by time)."""
    missing = [c for c in _REQUIRED_COLUMNS if c not in bars.columns]
    if missing:
        raise LabelError(f"bars frame missing columns: {sorted(missing)}")
    df = bars.sort("time").with_columns(
        pl.col("open").cast(pl.Float64),
        pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64),
        pl.col("close").cast(pl.Float64),
        pl.col("atr").cast(pl.Float64),
    )
    times = df.get_column("time").to_list()
    return (
        times,
        df.get_column("open").to_list(),
        df.get_column("high").to_list(),
        df.get_column("low").to_list(),
        df.get_column("atr").to_list(),
        {t: i for i, t in enumerate(times)},
    )


def _resolve(
    *,
    is_long: bool,
    entry: float,
    tp: float,
    sl: float,
    fill: int,
    high: list[float],
    low: list[float],
    close: list[float],
    horizon: int,
) -> tuple[str, float]:
    """Walk forward and resolve the barrier outcome → ``(outcome, return)``."""
    last = len(high) - 1
    end = min(fill + horizon, last)
    for j in range(fill, end + 1):
        hi, lo = high[j], low[j]
        if (is_long and lo <= sl) or (not is_long and hi >= sl):
            return "sl", (sl - entry) if is_long else (entry - sl)
        if (is_long and hi >= tp) or (not is_long and lo <= tp):
            return "tp", (tp - entry) if is_long else (entry - tp)
    final = close[end]
    return "time", (final - entry) if is_long else (entry - final)


def _label_for_target(target: str, outcome: str, ret: float) -> int:
    """Map a barrier outcome to the per-target binary label."""
    if target == "trend_continuation":
        return 1 if outcome == "tp" or (outcome == "time" and ret > 0.0) else 0
    return 1 if outcome == "sl" or (outcome == "time" and ret <= 0.0) else 0


def label_triple_barrier(
    signals: Sequence[SetupSignal],
    bars: pl.DataFrame,
    *,
    config: TripleBarrierConfig | None = None,
) -> pl.DataFrame:
    """Label every signal by the triple-barrier method; return one row per labellable signal.

    Signals that cannot be entered (no next bar, missing / non-positive ATR) are dropped with
    a debug log, exactly like the execution engine.
    """
    config = config or TripleBarrierConfig()
    times, open_, high, low, atr, index_of = _prepare(bars)
    close = bars.sort("time").get_column("close").cast(pl.Float64).to_list()

    rows: list[dict[str, object]] = []
    for signal in signals:
        trigger = index_of.get(signal.time)
        if trigger is None or trigger + 1 > len(times) - 1:
            logger.debug("label skip %s: no entry bar after trigger", signal.time)
            continue
        fill = trigger + 1
        atr_entry = atr[fill]
        if atr_entry is None or atr_entry <= 0.0:
            logger.debug("label skip %s: missing/non-positive ATR at entry", signal.time)
            continue
        is_long = signal.direction == "long"
        entry = open_[fill]
        tp = entry + config.tp_atr_mult * atr_entry * (1 if is_long else -1)
        sl = entry - config.sl_atr_mult * atr_entry * (1 if is_long else -1)
        outcome, ret = _resolve(
            is_long=is_long,
            entry=entry,
            tp=tp,
            sl=sl,
            fill=fill,
            high=high,
            low=low,
            close=close,
            horizon=config.horizon_bars,
        )
        target = target_for_strategy(signal.strategy_id)
        rows.append(
            {
                "strategy_id": signal.strategy_id,
                "time": signal.time,
                "direction": signal.direction,
                "target": target,
                "outcome": outcome,
                "label": _label_for_target(target, outcome, ret),
                "ret": ret,
            }
        )
    return pl.DataFrame(rows, schema=LABEL_SCHEMA)


def save_labels(frame: pl.DataFrame, out_dir: object) -> list[object]:
    """Persist labels under ``out_dir`` as one Parquet per target (``{target}.parquet``).

    Returns the written paths. The directory is created if absent. ``data/labels/`` is
    gitignored — these derive from gitignored market data and are never committed.
    """
    base = Path(str(out_dir))
    base.mkdir(parents=True, exist_ok=True)
    written: list[object] = []
    for target in frame.get_column("target").unique().to_list():
        path = base / f"{target}.parquet"
        frame.filter(pl.col("target") == target).write_parquet(path)
        written.append(path)
    return written


__all__: list[str] = ["LABEL_SCHEMA", "label_triple_barrier", "save_labels"]
