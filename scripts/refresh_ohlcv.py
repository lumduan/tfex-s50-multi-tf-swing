"""Refresh OHLCV from TradingView (tvkit) and write Parquet + (optional) Timescale mirror.

Usage::

    uv run python scripts/refresh_ohlcv.py \\
        --contract S50M2026 --contract S50U2026 \\
        --timeframe 5m --timeframe 1h --timeframe 4h \\
        --start 2026-04-01 --end 2026-05-01

When ``TFEX_S50_MULTI_TF_SWING_DB_WRITE_ENABLED=true`` and ``PG_DSN`` is set,
the same rows are also UPSERTed into ``ohlcv_raw`` / ``ohlcv_continuous`` in
``db_tfex_s50_multi_tf_swing``. Re-running the same window is idempotent.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime
from typing import Final

from tfex_s50_multi_tf_swing.config.settings import get_settings
from tfex_s50_multi_tf_swing.data import (
    OhlcvDbWriter,
    OhlcvFetcher,
    ParquetStore,
    SessionCalendar,
    refresh_all,
)
from tfex_s50_multi_tf_swing.data.models import TIMEFRAMES, Timeframe

logger: logging.Logger = logging.getLogger(__name__)

_LOG_FORMAT: Final[str] = "%(asctime)s [%(levelname)-7s] %(name)s - %(message)s"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        action="append",
        required=True,
        metavar="CODE",
        help="Quarterly contract code (e.g. S50M2026). Pass multiple times.",
    )
    parser.add_argument(
        "--timeframe",
        action="append",
        choices=list(TIMEFRAMES),
        metavar="TF",
        help=f"Timeframe to refresh (one of {list(TIMEFRAMES)}). "
        "Pass multiple times. Defaults to all.",
    )
    parser.add_argument(
        "--start",
        required=True,
        type=_parse_date_utc,
        help="Inclusive UTC start (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--end",
        required=True,
        type=_parse_date_utc,
        help="Exclusive UTC end (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default INFO).",
    )
    return parser.parse_args(argv)


def _parse_date_utc(s: str) -> datetime:
    try:
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as exc:  # pragma: no cover — argparse surfaces it
        raise argparse.ArgumentTypeError(f"invalid date {s!r}; want YYYY-MM-DD") from exc


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    timeframes: list[Timeframe] = args.timeframe or list(TIMEFRAMES)

    store = ParquetStore(settings.data_dir)
    fetcher = OhlcvFetcher(
        auth_token=settings.tvkit_auth_token,
        concurrency=settings.data_fetch_concurrency,
    )
    calendar = SessionCalendar(roll_offset_days=settings.roll_offset_days)

    db_writer: OhlcvDbWriter | None = None
    if settings.db_write_enabled and settings.pg_dsn:
        # Open the pool inside the same coroutine so it's properly closed below.
        async with OhlcvDbWriter.from_dsn(settings.pg_dsn) as writer:
            await refresh_all(
                settings=settings,
                contracts=args.contract,
                timeframes=timeframes,
                start=args.start,
                end=args.end,
                fetcher=fetcher,
                store=store,
                db_writer=writer,
                calendar=calendar,
            )
            return 0
    elif settings.db_write_enabled and not settings.pg_dsn:
        logger.warning("DB_WRITE_ENABLED=true but PG_DSN is unset; running without DB mirror")

    await refresh_all(
        settings=settings,
        contracts=args.contract,
        timeframes=timeframes,
        start=args.start,
        end=args.end,
        fetcher=fetcher,
        store=store,
        db_writer=db_writer,
        calendar=calendar,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(level=args.log_level, format=_LOG_FORMAT)
    return asyncio.run(_run(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
