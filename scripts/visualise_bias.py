"""Visualise the 4H higher-timeframe bias overlaid on the continuous series (ROADMAP §4.2).

Reads the back-adjusted 4H continuous frame (``data/continuous/4h.parquet``, produced by the
Phase 1 refresh on the ``mirror`` source), runs the bias engine, and writes a **public-safe**
overlay summary — ``time`` + ``bias_direction`` + ``bias_reasons`` only, **no raw OHLCV** — to
``results/static/bias/overlay_4h.parquet`` plus a small ``overlay_4h_counts.json``.

The library core stays pure: all IO lives here, never in ``src/``. A notebook
(``notebooks/04_htf_bias.ipynb``) renders the chart from this artifact.

4h is **mirror-only** today: the ``engine`` OHLCV source declines 4h
(``EngineTimeframeUnavailableError``, no local rollup — D10), so this script reads the offline
``mirror`` Parquet. See ``docs/plans/ROADMAP.md`` → Phase 4.

Usage::

    uv run python scripts/visualise_bias.py --timeframe 4h
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Final

from tfex_s50_multi_tf_swing.bias.htf import build_bias_inputs, classify_frame
from tfex_s50_multi_tf_swing.config.settings import get_settings
from tfex_s50_multi_tf_swing.data.models import TIMEFRAMES, Timeframe
from tfex_s50_multi_tf_swing.data.store import ParquetStore

logger: logging.Logger = logging.getLogger(__name__)

_LOG_FORMAT: Final[str] = "%(asctime)s [%(levelname)-7s] %(name)s - %(message)s"
_DEFAULT_OUT: Final[Path] = Path("results/static/bias")
#: Columns safe to persist publicly — never raw OHLCV.
_PUBLIC_COLUMNS: Final[tuple[str, ...]] = ("time", "bias_direction", "bias_reasons")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timeframe",
        default="4h",
        choices=list(TIMEFRAMES),
        help="Timeframe whose continuous series to overlay (default 4h).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"Public-safe artifact directory (default {_DEFAULT_OUT}).",
    )
    parser.add_argument(
        "--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )
    return parser.parse_args(argv)


def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    timeframe: Timeframe = args.timeframe
    store = ParquetStore(settings.data_dir)

    continuous = store.read_continuous(timeframe)
    inputs = build_bias_inputs(
        continuous,
        timeframe,
        regime_thresholds=settings.regime_thresholds(),
    )
    classified = classify_frame(inputs, config=settings.bias_config())
    overlay = classified.select(*_PUBLIC_COLUMNS)

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    overlay.write_parquet(out_dir / f"overlay_{timeframe}.parquet")

    counts = (
        overlay.group_by("bias_direction").len().sort("bias_direction").to_dict(as_series=False)
    )
    summary = {
        "timeframe": timeframe,
        "bars": overlay.height,
        "direction_counts": dict(zip(counts["bias_direction"], counts["len"], strict=True)),
    }
    (out_dir / f"overlay_{timeframe}_counts.json").write_text(json.dumps(summary, indent=2))
    logger.info("wrote bias overlay tf=%s bars=%d counts=%s", timeframe, overlay.height, summary)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(level=args.log_level, format=_LOG_FORMAT)
    return _run(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
