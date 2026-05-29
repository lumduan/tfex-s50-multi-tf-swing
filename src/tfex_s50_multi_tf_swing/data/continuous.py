"""Back-adjusted continuous futures contract builder.

ROADMAP §1.2 — roll on volume crossover near expiry (default ``5d_before_expiry``),
ratio-adjust historical prices so the rollover gap disappears, preserve the
raw per-contract series for honest execution simulation.

This module is pure: it consumes per-contract OHLCV frames keyed by contract
code and returns a single continuous Polars frame plus the list of roll
records used. Persistence happens elsewhere.

Algorithm:

1. Sort contracts by expiry ascending (calendar order).
2. For each adjacent pair ``(near, far)``:
   - Determine the roll moment: the LAST bar in the roll window where
     the ``far`` contract's volume first equals or exceeds the ``near``
     contract's volume (volume-crossover). If no crossover occurs, the
     roll happens at the end of the window (``expiry``).
   - Compute the ratio ``r = close(near, t_roll) / close(far, t_roll)``.
   - Multiply every prior ``far`` bar (and every earlier continuous bar)
     by ``r`` so the continuous series is gap-free.
3. Concatenate, emit the continuous frame plus a list of
   :class:`~tfex_s50_multi_tf_swing.data.models.RollRecord`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal

import polars as pl

from tfex_s50_multi_tf_swing.data.contracts import parse_contract_code
from tfex_s50_multi_tf_swing.data.errors import ContinuousContractError
from tfex_s50_multi_tf_swing.data.models import (
    RollRecord,
    Timeframe,
)
from tfex_s50_multi_tf_swing.data.session import SessionCalendar

logger: logging.Logger = logging.getLogger(__name__)


class ContinuousBuilder:
    """Build the back-adjusted continuous series from per-contract raw frames."""

    def __init__(
        self,
        *,
        calendar: SessionCalendar | None = None,
        roll_offset_days: int = 5,
    ) -> None:
        if roll_offset_days < 0:
            raise ValueError(f"roll_offset_days must be ≥ 0, got {roll_offset_days}")
        self._calendar: SessionCalendar = calendar or SessionCalendar(
            roll_offset_days=roll_offset_days
        )
        self._roll_offset_days: int = roll_offset_days

    def build(
        self,
        *,
        per_contract: Mapping[str, pl.DataFrame],
        timeframe: Timeframe,
    ) -> tuple[pl.DataFrame, list[RollRecord]]:
        """Stitch per-contract frames into one back-adjusted continuous frame.

        ``per_contract`` maps contract code (e.g. ``"S50H2026"``) to its raw
        Polars frame containing ``time, open, high, low, close, volume``.
        Frames must use tz-aware UTC timestamps.

        Returns a ``(continuous_frame, roll_records)`` tuple. The continuous
        frame carries columns:

        ``time``, ``timeframe``, ``open``, ``high``, ``low``, ``close``,
        ``volume``, ``contract_at_time``, ``adjustment_factor``.
        """
        if not per_contract:
            raise ContinuousContractError("per_contract is empty")
        for code, df in per_contract.items():
            _require_columns(df, code, {"time", "open", "high", "low", "close", "volume"})

        ordered: list[tuple[str, pl.DataFrame]] = sorted(
            per_contract.items(),
            key=lambda kv: _month_index(kv[0]),
        )

        # Per ROADMAP: roll happens on volume crossover within the
        # roll-offset-day window before expiry. Determine the roll moment for
        # each pair, then back-adjust historicals.
        rolls: list[RollRecord] = []
        # Tracks the cumulative multiplicative adjustment applied to the
        # latest contract in calendar order; back-applied to earlier
        # contracts as new rolls are discovered.
        # Walk pairs from oldest to newest.
        segments: list[pl.DataFrame] = []
        cumulative_factor: Decimal = Decimal("1")

        for i, (code, raw) in enumerate(ordered):
            is_last: bool = i == len(ordered) - 1
            if is_last:
                # Final segment: keep all bars; no future expiry to roll past.
                segments.append(_tag_segment(raw, code, cumulative_factor))
                continue
            far_code, far_raw = ordered[i + 1]
            expiry = self._expiry_for(code)
            roll_time = self._find_roll_time(
                near=raw, far=far_raw, expiry=expiry, code=code, far_code=far_code
            )
            ratio = self._compute_roll_ratio(
                near=raw,
                far=far_raw,
                roll_time=roll_time,
                near_code=code,
                far_code=far_code,
            )
            rolls.append(
                RollRecord(
                    roll_time=roll_time,
                    from_contract=code,
                    to_contract=far_code,
                    ratio=ratio,
                )
            )
            # Use ``near`` bars up to (and including) the roll moment; back-adjust them.
            near_segment = raw.filter(pl.col("time") <= roll_time)
            segments.append(_tag_segment(near_segment, code, cumulative_factor * ratio))
            cumulative_factor = cumulative_factor  # near is adjusted *up* relative to far

        # Each segment was tagged with the factor that maps it INTO the
        # latest-contract scale. The far segment we built last is in the
        # newest contract's scale, so its factor is 1.0. We multiply
        # historical OHLC by the running factor.
        continuous = pl.concat(segments).sort("time").unique(subset=["time"], keep="last")
        # Now apply adjustment_factor multiplicatively to OHLC. ``volume``
        # is preserved as observed (volume is not price-rescaled).
        af = pl.col("adjustment_factor").cast(pl.Float64)
        adjusted = (
            continuous.with_columns(
                [
                    (pl.col("open").cast(pl.Float64) * af).alias("open"),
                    (pl.col("high").cast(pl.Float64) * af).alias("high"),
                    (pl.col("low").cast(pl.Float64) * af).alias("low"),
                    (pl.col("close").cast(pl.Float64) * af).alias("close"),
                ]
            )
            .with_columns(
                [
                    pl.col("open").cast(pl.Decimal(18, 4)),
                    pl.col("high").cast(pl.Decimal(18, 4)),
                    pl.col("low").cast(pl.Decimal(18, 4)),
                    pl.col("close").cast(pl.Decimal(18, 4)),
                    pl.col("volume").cast(pl.Decimal(18, 4)),
                    pl.col("adjustment_factor").cast(pl.Decimal(18, 8)),
                ]
            )
            .with_columns(pl.lit(timeframe).alias("timeframe"))
        )

        ordered_cols = [
            "time",
            "timeframe",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "contract_at_time",
            "adjustment_factor",
        ]
        return adjusted.select(ordered_cols), rolls

    # ------------------------------------------------------------------
    # Roll-time discovery
    # ------------------------------------------------------------------

    def _find_roll_time(
        self,
        *,
        near: pl.DataFrame,
        far: pl.DataFrame,
        expiry: datetime,
        code: str,
        far_code: str,
    ) -> datetime:
        window_start = expiry - timedelta(days=self._roll_offset_days)
        in_window_near = near.filter((pl.col("time") >= window_start) & (pl.col("time") <= expiry))
        in_window_far = far.filter((pl.col("time") >= window_start) & (pl.col("time") <= expiry))
        if in_window_near.height == 0 or in_window_far.height == 0:
            logger.warning(
                "roll: no overlap window data near=%s far=%s window=[%s, %s]; "
                "defaulting roll to %s expiry",
                code,
                far_code,
                window_start.isoformat(),
                expiry.isoformat(),
                code,
            )
            return expiry

        joined = (
            in_window_near.select(["time", pl.col("volume").alias("vol_near")])
            .join(
                in_window_far.select(["time", pl.col("volume").alias("vol_far")]),
                on="time",
                how="inner",
            )
            .sort("time")
        )
        if joined.height == 0:
            return expiry

        crossover = joined.filter(pl.col("vol_far") >= pl.col("vol_near"))
        if crossover.height == 0:
            return expiry
        first_crossover_time = crossover["time"].head(1).to_list()[0]
        if not isinstance(first_crossover_time, datetime):
            raise ContinuousContractError(
                f"unexpected roll-time type: {type(first_crossover_time)}"
            )
        return first_crossover_time

    # ------------------------------------------------------------------
    # Ratio
    # ------------------------------------------------------------------

    def _compute_roll_ratio(
        self,
        *,
        near: pl.DataFrame,
        far: pl.DataFrame,
        roll_time: datetime,
        near_code: str,
        far_code: str,
    ) -> Decimal:
        near_close = _close_at_or_before(near, roll_time)
        far_close = _close_at_or_before(far, roll_time)
        if near_close is None or far_close is None:
            raise ContinuousContractError(
                f"missing close at roll time {roll_time.isoformat()} for "
                f"pair {near_code} → {far_code}"
            )
        if near_close == 0:
            raise ContinuousContractError(
                f"near-contract close is zero at roll time {roll_time.isoformat()}"
            )
        # Back-adjustment ratio: scale historical NEAR bars onto the FAR scale
        # so the continuous series has no jump at the roll boundary.
        # Quantize to 8 dp so the ratio stays stable on disk.
        ratio = (Decimal(str(far_close)) / Decimal(str(near_close))).quantize(Decimal("0.00000001"))
        return ratio

    # ------------------------------------------------------------------
    # Expiry helper
    # ------------------------------------------------------------------

    def _expiry_for(self, code: str) -> datetime:
        from tfex_s50_multi_tf_swing.data.contracts import expiry_for

        expiry_date = expiry_for(code, calendar=self._calendar)
        # Treat expiry as end-of-day UTC for comparison purposes.
        return datetime.combine(
            expiry_date,
            datetime.max.time().replace(microsecond=0),
            tzinfo=__import__("datetime").timezone.utc,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_columns(df: pl.DataFrame, code: str, expected: set[str]) -> None:
    missing = expected - set(df.columns)
    if missing:
        raise ContinuousContractError(
            f"contract {code!r} frame is missing columns {sorted(missing)}"
        )


_MONTH_ORDER: dict[str, int] = {"H": 1, "M": 2, "U": 3, "Z": 4}


def _month_index(code: str) -> tuple[int, int]:
    month_code, year = parse_contract_code(code)
    return year, _MONTH_ORDER[month_code]


def _tag_segment(df: pl.DataFrame, code: str, factor: Decimal) -> pl.DataFrame:
    """Attach ``contract_at_time`` and ``adjustment_factor`` to a raw segment."""
    return df.with_columns(
        [
            pl.lit(code).alias("contract_at_time"),
            pl.lit(str(factor)).cast(pl.Decimal(18, 8)).alias("adjustment_factor"),
        ]
    )


def _close_at_or_before(df: pl.DataFrame, t: datetime) -> Decimal | None:
    bar = df.filter(pl.col("time") <= t).sort("time").tail(1)
    if bar.height == 0:
        return None
    close = bar["close"].to_list()[0]
    if close is None:
        return None
    if isinstance(close, Decimal):
        return close
    return Decimal(str(close))


__all__: list[str] = ["ContinuousBuilder"]
