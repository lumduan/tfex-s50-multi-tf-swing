"""Build feature panels from the back-adjusted continuous OHLCV (Phase 2).

Reads ``data/continuous/<tf>.parquet`` (produced by the Phase 1 refresh), runs
the feature pipeline, and writes:

* ``data/features/<tf>.parquet``     — per-timeframe feature panel
* ``data/features/aligned_<base>.parquet`` — causally-aligned multi-timeframe view

Usage::

    uv run python scripts/build_features.py \\
        --timeframe 5m --timeframe 1h --timeframe 4h --base-timeframe 5m

Features are statistical (Float64) and never cross the gateway boundary — no
Decimal, no money. The pipeline is look-ahead-free (see the features package).
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Final

from tfex_s50_multi_tf_swing.config.settings import get_settings
from tfex_s50_multi_tf_swing.data.models import TIMEFRAMES, Timeframe
from tfex_s50_multi_tf_swing.data.store import ParquetStore
from tfex_s50_multi_tf_swing.features.models import FeatureConfig
from tfex_s50_multi_tf_swing.features.pipeline import build_aligned, build_panel
from tfex_s50_multi_tf_swing.features.store import FeatureStore

logger: logging.Logger = logging.getLogger(__name__)

_LOG_FORMAT: Final[str] = "%(asctime)s [%(levelname)-7s] %(name)s - %(message)s"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timeframe",
        action="append",
        choices=list(TIMEFRAMES),
        metavar="TF",
        help=f"Timeframe to build (one of {list(TIMEFRAMES)}). Repeatable; defaults to all.",
    )
    parser.add_argument(
        "--base-timeframe",
        default="1h",
        choices=list(TIMEFRAMES),
        help="Base timeframe for the aligned panel (default 1h, 1H-execution migration).",
    )
    parser.add_argument(
        "--no-normalise",
        action="store_true",
        help="Skip winsorise + trailing z-score (emit raw feature values).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args(argv)


def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    timeframes: list[Timeframe] = args.timeframe or list(TIMEFRAMES)
    config = FeatureConfig(normalise=not args.no_normalise)

    source = ParquetStore(settings.data_dir)
    sink = FeatureStore(settings.data_dir, config)

    panels = {}
    for tf in timeframes:
        continuous = source.read_continuous(tf)
        panel = build_panel(continuous, tf, config)
        sink.write_panel(tf, panel)
        panels[tf] = panel
        logger.info("built feature panel tf=%s rows=%d", tf, panel.height)

    base: Timeframe = args.base_timeframe
    if base in panels and len(panels) > 1:
        aligned = build_aligned(panels, base_timeframe=base)
        sink.write_aligned(aligned, base)
        logger.info(
            "built aligned panel base=%s rows=%d cols=%d", base, aligned.height, aligned.width
        )
    else:
        logger.info("skipping aligned panel (need base %s + ≥1 coarser timeframe)", base)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(level=args.log_level, format=_LOG_FORMAT)
    return _run(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
