"""§4.3 demonstration — counter-trend-entry reduction from the HTF bias veto.

ROADMAP §4.3 asks for a before/after comparison whose exit criterion is "≥ 30 % reduction in
counter-trend entries vs the unfiltered baseline". A faithful end-to-end backtest needs the
``signals/`` + ``execution/`` + ``backtest/`` layers, which do not exist yet (Phases 5 / 8), so
the full metric is **deferred → blocked-on Phase 5** (see the plan's Design Decision D9). This
script instead demonstrates the *mechanism*: it derives a **naive candidate-entry proxy**
(1-bar momentum: enter long after an up bar, short after a down bar) on the 4H continuous
series — deliberately independent of the bias gates — then counts how many candidates point
*against* the HTF bias. Those are exactly the entries the bias engine vetoes.

It writes a **public-safe** artifact (counts + reduction %, **no raw OHLCV**) to
``results/static/bias/counter_trend_reduction.json``.

Usage::

    uv run python scripts/bias_counter_trend_demo.py --timeframe 4h
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Final

import polars as pl

from tfex_s50_multi_tf_swing.bias.htf import build_bias_inputs, classify_frame
from tfex_s50_multi_tf_swing.config.settings import get_settings
from tfex_s50_multi_tf_swing.data.models import TIMEFRAMES, Timeframe
from tfex_s50_multi_tf_swing.data.store import ParquetStore

logger: logging.Logger = logging.getLogger(__name__)

_LOG_FORMAT: Final[str] = "%(asctime)s [%(levelname)-7s] %(name)s - %(message)s"
_DEFAULT_OUT: Final[Path] = Path("results/static/bias")


def _candidate_direction() -> pl.Expr:
    """Naive 1-bar momentum candidate: long after an up bar, short after a down bar.

    Trailing-only (``shift(1)``) so it never peeks; ``None`` on the first bar.
    """
    prev_ret = pl.col("close").cast(pl.Float64).diff().shift(1)
    return (
        pl.when(prev_ret > 0.0)
        .then(pl.lit("long"))
        .when(prev_ret < 0.0)
        .then(pl.lit("short"))
        .otherwise(None)
    )


def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    timeframe: Timeframe = args.timeframe
    store = ParquetStore(settings.data_dir)

    continuous = store.read_continuous(timeframe)
    inputs = build_bias_inputs(
        continuous, timeframe, regime_thresholds=settings.regime_thresholds()
    )
    bias = classify_frame(inputs, config=settings.bias_config()).select("time", "bias_direction")
    candidates = continuous.select("time", _candidate_direction().alias("candidate"))

    joined = candidates.join(bias, on="time", how="inner").drop_nulls("candidate")
    # A candidate is "counter-trend" when it opposes a non-neutral HTF bias.
    opposes = ((pl.col("candidate") == "long") & (pl.col("bias_direction") == "short")) | (
        (pl.col("candidate") == "short") & (pl.col("bias_direction") == "long")
    )
    total = joined.height
    counter_trend = int(joined.filter(opposes).height)
    kept = total - counter_trend
    reduction = (counter_trend / total) if total else 0.0

    summary = {
        "timeframe": timeframe,
        "baseline_candidates": total,
        "counter_trend_vetoed": counter_trend,
        "kept_after_filter": kept,
        "counter_trend_reduction_pct": round(reduction * 100.0, 2),
        "note": (
            "Demonstration on a naive 1-bar-momentum candidate proxy; the full §4.3 exit "
            "metric (≥30% vs the real unfiltered strategy) is deferred to Phase 5 (signals)."
        ),
    }
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "counter_trend_reduction.json").write_text(json.dumps(summary, indent=2))
    logger.info("counter-trend demo tf=%s %s", timeframe, summary)
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timeframe", default="4h", choices=list(TIMEFRAMES), help="Timeframe (default 4h)."
    )
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT)
    parser.add_argument(
        "--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(level=args.log_level, format=_LOG_FORMAT)
    return _run(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
