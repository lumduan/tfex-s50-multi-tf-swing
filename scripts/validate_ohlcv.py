"""Re-validate the latest Parquet OHLCV without re-fetching.

Usage::

    uv run python scripts/validate_ohlcv.py --as-of 2026-04-30 \\
        --contract S50M2026 --timeframe 5m
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Final

from tfex_s50_multi_tf_swing.config.settings import get_settings
from tfex_s50_multi_tf_swing.data import ParquetStore, SessionCalendar, Validator
from tfex_s50_multi_tf_swing.data.models import TIMEFRAMES, Timeframe

logger: logging.Logger = logging.getLogger(__name__)

_LOG_FORMAT: Final[str] = "%(asctime)s [%(levelname)-7s] %(name)s - %(message)s"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of",
        required=True,
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC),
        help="Report's as-of date (YYYY-MM-DD UTC).",
    )
    parser.add_argument(
        "--contract", required=True, help="Quarterly contract code (e.g. S50M2026)."
    )
    parser.add_argument(
        "--timeframe",
        required=True,
        choices=list(TIMEFRAMES),
        metavar="TF",
        help=f"Timeframe to validate (one of {list(TIMEFRAMES)}).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(level=args.log_level, format=_LOG_FORMAT)

    settings = get_settings()
    store = ParquetStore(settings.data_dir)
    df = store.read_raw_if_exists(args.contract, args.timeframe)
    if df is None:
        logger.error(
            "no raw Parquet found for contract=%s tf=%s under %s",
            args.contract,
            args.timeframe,
            settings.data_dir,
        )
        return 1
    timeframe: Timeframe = args.timeframe  # validated by argparse choice
    validator = Validator(calendar=SessionCalendar(roll_offset_days=settings.roll_offset_days))
    report = validator.validate(df, timeframe=timeframe, contract=args.contract, as_of=args.as_of)
    path = store.write_validation_report(report)
    logger.info("wrote validation report to %s", path)
    print(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0 if report.is_clean else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
