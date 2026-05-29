"""OHLCV validation pipeline.

Per ROADMAP §1.4 the validator answers four questions about a fetched frame:

1. Are any bars missing inside an open session?
2. Are there duplicate timestamps?
3. Are any per-bar spreads ``(high - low) / close`` abnormal (>3σ)?
4. Does the 5m frame aggregate up to the 1H frame and the 1H to the 4H?

Plus an informational cross-check (§3.5 of the plan) comparing our
locally-built back-adjusted continuous to TradingView's ``S501!`` series.

The validator is pure: it consumes Polars frames and returns
:class:`~tfex_s50_multi_tf_swing.data.models.ValidationReport`. Persistence
lives in :mod:`tfex_s50_multi_tf_swing.data.store`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

import polars as pl

from tfex_s50_multi_tf_swing.data.errors import ValidationError
from tfex_s50_multi_tf_swing.data.models import (
    TIMEFRAME_MINUTES,
    ContinuousCrossCheck,
    CrossCheckPoint,
    Timeframe,
    ValidationIssue,
    ValidationReport,
)
from tfex_s50_multi_tf_swing.data.session import SessionCalendar

logger: logging.Logger = logging.getLogger(__name__)

DEFAULT_SPREAD_SIGMA: float = 3.0
"""Z-score threshold above which a bar's spread is flagged as abnormal."""

DEFAULT_CROSS_CHECK_TOLERANCE: Decimal = Decimal("0.0050")
"""Default ``|return_diff|`` tolerance when comparing our continuous to ``S501!``."""


class Validator:
    """Pure-function validator producing a :class:`ValidationReport`.

    The validator does not raise on warnings — it accumulates them in
    :class:`ValidationReport.issues`. It only raises :class:`ValidationError`
    when given input that violates a structural invariant (missing columns,
    non-UTC timestamps, etc.).
    """

    def __init__(
        self,
        *,
        calendar: SessionCalendar | None = None,
        spread_sigma: float = DEFAULT_SPREAD_SIGMA,
    ) -> None:
        self._calendar: SessionCalendar = calendar or SessionCalendar()
        self._spread_sigma: float = spread_sigma

    # ------------------------------------------------------------------
    # Single-frame validation
    # ------------------------------------------------------------------

    def validate(
        self,
        df: pl.DataFrame,
        *,
        timeframe: Timeframe,
        contract: str,
        as_of: datetime,
    ) -> ValidationReport:
        """Validate a single per-contract OHLCV frame at one timeframe."""
        _require_columns(df, {"time", "open", "high", "low", "close", "volume"})
        _require_utc_time(df)

        issues: list[ValidationIssue] = []

        duplicate_count: int = self._count_duplicate_timestamps(df, issues)
        missing_count: int = self._count_missing_bars_in_session(df, timeframe, issues)
        abnormal_spread_count: int = self._count_abnormal_spread_bars(df, issues)

        return ValidationReport(
            as_of=as_of,
            contract=contract,
            timeframe=timeframe,
            bar_count=df.height,
            missing_bars=missing_count,
            duplicate_timestamps=duplicate_count,
            abnormal_spread_bars=abnormal_spread_count,
            issues=issues,
        )

    # ------------------------------------------------------------------
    # Cross-timeframe consistency
    # ------------------------------------------------------------------

    def cross_timeframe_consistency(
        self,
        *,
        finer: pl.DataFrame,
        finer_tf: Timeframe,
        coarser: pl.DataFrame,
        coarser_tf: Timeframe,
    ) -> int:
        """Count timestamps where aggregating ``finer`` does not match ``coarser``.

        Aggregation rule: within each ``coarser_tf`` window, the finer frame's
        first/max/min/last/sum of OHLCV must match the coarser frame. Returns
        the number of mismatched coarser bars. Floating-point comparisons use
        a small relative tolerance because Decimal→Float arithmetic happens in
        Polars internally.
        """
        if TIMEFRAME_MINUTES[finer_tf] >= TIMEFRAME_MINUTES[coarser_tf]:
            raise ValidationError(
                f"cross-TF: finer ({finer_tf}) must have smaller bar size than "
                f"coarser ({coarser_tf})"
            )
        _require_columns(finer, {"time", "open", "high", "low", "close", "volume"})
        _require_columns(coarser, {"time", "open", "high", "low", "close", "volume"})

        coarser_minutes: int = TIMEFRAME_MINUTES[coarser_tf]
        bucketed = finer.with_columns(
            pl.col("time").dt.truncate(f"{coarser_minutes}m").alias("bucket")
        )
        agg = bucketed.group_by("bucket").agg(
            [
                pl.col("open").first().alias("agg_open"),
                pl.col("high").max().alias("agg_high"),
                pl.col("low").min().alias("agg_low"),
                pl.col("close").last().alias("agg_close"),
                pl.col("volume").sum().alias("agg_volume"),
            ]
        )
        joined = coarser.join(agg, left_on="time", right_on="bucket", how="inner")
        if joined.height == 0:
            return 0

        # Compare as Float64 to be robust to Decimal vs Float differences
        # introduced by Polars internal math.
        cast_cols: list[pl.Expr] = []
        for col in ("open", "high", "low", "close", "volume"):
            cast_cols.append(pl.col(col).cast(pl.Float64).alias(f"r_{col}"))
            cast_cols.append(pl.col(f"agg_{col}").cast(pl.Float64).alias(f"a_{col}"))
        normed = joined.with_columns(cast_cols)
        mismatch_expr = (
            ((pl.col("r_open") - pl.col("a_open")).abs() > 1e-4)
            | ((pl.col("r_high") - pl.col("a_high")).abs() > 1e-4)
            | ((pl.col("r_low") - pl.col("a_low")).abs() > 1e-4)
            | ((pl.col("r_close") - pl.col("a_close")).abs() > 1e-4)
            | ((pl.col("r_volume") - pl.col("a_volume")).abs() > 1e-4)
        )
        mismatches: int = int(normed.filter(mismatch_expr).height)
        return mismatches

    # ------------------------------------------------------------------
    # Continuous vs S501! cross-check
    # ------------------------------------------------------------------

    def validate_continuous_against_reference(
        self,
        *,
        our_continuous: pl.DataFrame,
        s501_reference: pl.DataFrame,
        timeframe: Timeframe,
        tolerance: Decimal = DEFAULT_CROSS_CHECK_TOLERANCE,
    ) -> ContinuousCrossCheck:
        """Compare our back-adjusted continuous to TradingView's ``S501!``.

        The reference and our series are aligned on common ``time`` values; we
        compute log-returns on close in both, then flag timestamps where the
        absolute return-difference exceeds ``tolerance``. The result is
        informational only — it is surfaced in the validation report so a
        human can eyeball any divergence at roll boundaries.
        """
        _require_columns(our_continuous, {"time", "close"})
        _require_columns(s501_reference, {"time", "close"})

        aligned = (
            our_continuous.select(["time", pl.col("close").alias("close_ours")])
            .join(
                s501_reference.select(["time", pl.col("close").alias("close_ref")]),
                on="time",
                how="inner",
            )
            .sort("time")
        )
        if aligned.height < 2:
            return ContinuousCrossCheck(
                timeframe=timeframe,
                aligned_bars=int(aligned.height),
                max_abs_return_diff=Decimal("0"),
                mean_abs_return_diff=Decimal("0"),
                flagged=[],
                tolerance=tolerance,
            )

        ret = aligned.with_columns(
            [
                pl.col("close_ours").cast(pl.Float64).pct_change().alias("ret_ours"),
                pl.col("close_ref").cast(pl.Float64).pct_change().alias("ret_ref"),
            ]
        ).drop_nulls(["ret_ours", "ret_ref"])
        ret = ret.with_columns((pl.col("ret_ours") - pl.col("ret_ref")).abs().alias("abs_diff"))

        tol_float: float = float(tolerance)
        flagged_rows: list[CrossCheckPoint] = []
        for row in ret.filter(pl.col("abs_diff") > tol_float).iter_rows(named=True):
            flagged_rows.append(
                CrossCheckPoint(
                    time=row["time"],
                    our_return=_q(row["ret_ours"]),
                    reference_return=_q(row["ret_ref"]),
                    difference=_q(row["abs_diff"]),
                )
            )

        return ContinuousCrossCheck(
            timeframe=timeframe,
            aligned_bars=int(ret.height + 1),  # +1 for the dropped first row
            max_abs_return_diff=_q(ret["abs_diff"].max()),
            mean_abs_return_diff=_q(ret["abs_diff"].mean()),
            flagged=flagged_rows,
            tolerance=tolerance,
        )

    # ------------------------------------------------------------------
    # Internal pieces
    # ------------------------------------------------------------------

    def _count_duplicate_timestamps(self, df: pl.DataFrame, issues: list[ValidationIssue]) -> int:
        dup_count: int = int(df["time"].n_unique() - df.height) * -1
        # df.height - n_unique gives the number of duplicates removed.
        dup_count = df.height - int(df["time"].n_unique())
        if dup_count > 0:
            issues.append(
                ValidationIssue(
                    level="warning",
                    kind="duplicate_timestamp",
                    detail=f"{dup_count} duplicate timestamps in frame",
                    count=dup_count,
                )
            )
        return dup_count

    def _count_missing_bars_in_session(
        self,
        df: pl.DataFrame,
        timeframe: Timeframe,
        issues: list[ValidationIssue],
    ) -> int:
        """Count expected bars missing within the frame's observed time window.

        For each business day with at least one bar in ``df``, we enumerate
        the per-session 5m / 1h / 4h slots that fall **inside** that day's
        observed ``[min_time, max_time]`` and count how many are absent.
        Lunch and overnight gaps are excluded by construction. Sessions
        the frame did not cover at all (e.g. a test that only fed morning
        bars) are NOT counted as missing — that is a fetch-scope question,
        not a data-quality one.
        """
        if df.height == 0:
            return 0
        existing = set(df["time"].to_list())
        # Per-day observed time range.
        per_day = (
            df.select(
                [
                    pl.col("time").dt.date().alias("d"),
                    pl.col("time").min().over(pl.col("time").dt.date()).alias("day_min"),
                    pl.col("time").max().over(pl.col("time").dt.date()).alias("day_max"),
                ]
            )
            .unique(subset=["d"])
            .sort("d")
        )
        missing_total: int = 0
        tf_minutes: int = TIMEFRAME_MINUTES[timeframe]
        for row in per_day.iter_rows(named=True):
            day = row["d"]
            day_min = row["day_min"]
            day_max = row["day_max"]
            if not self._calendar.is_business_day(day):
                continue
            for expected_time in _expected_session_minutes(day, tf_minutes):
                if expected_time < day_min or expected_time > day_max:
                    continue
                if expected_time not in existing:
                    missing_total += 1
        if missing_total > 0:
            issues.append(
                ValidationIssue(
                    level="warning" if missing_total < df.height * 0.001 else "error",
                    kind="missing_bar",
                    detail=(f"{missing_total} expected bars missing inside the observed window"),
                    count=missing_total,
                )
            )
        return missing_total

    def _count_abnormal_spread_bars(self, df: pl.DataFrame, issues: list[ValidationIssue]) -> int:
        """Flag bars whose normalised spread exceeds the σ threshold."""
        if df.height < 30:
            return 0
        with_spread = df.with_columns(
            (
                (pl.col("high").cast(pl.Float64) - pl.col("low").cast(pl.Float64))
                / pl.col("close").cast(pl.Float64).fill_null(strategy="zero")
            )
            .replace(float("inf"), None)
            .alias("spread_frac")
        ).drop_nulls(["spread_frac"])
        if with_spread.height == 0:
            return 0
        spread_std: float = _as_float(with_spread["spread_frac"].std())
        spread_mean: float = _as_float(with_spread["spread_frac"].mean())
        if spread_std == 0.0:
            return 0
        threshold: float = spread_mean + self._spread_sigma * spread_std
        flagged: int = int(with_spread.filter(pl.col("spread_frac") > threshold).height)
        if flagged > 0:
            issues.append(
                ValidationIssue(
                    level="info",
                    kind="abnormal_spread",
                    detail=(
                        f"{flagged} bars exceed {self._spread_sigma}σ spread threshold "
                        f"(mean={spread_mean:.6f}, σ={spread_std:.6f})"
                    ),
                    count=flagged,
                )
            )
        return flagged


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_columns(df: pl.DataFrame, expected: set[str] | Mapping[str, object]) -> None:
    cols: set[str] = set(df.columns)
    missing: set[str] = set(expected) - cols
    if missing:
        raise ValidationError(f"frame is missing required columns: {sorted(missing)}")


def _require_utc_time(df: pl.DataFrame) -> None:
    if "time" not in df.columns:
        raise ValidationError("frame has no 'time' column")
    dtype = df.schema["time"]
    if not isinstance(dtype, pl.Datetime) or dtype.time_zone not in ("UTC", "+00:00"):
        raise ValidationError(f"frame 'time' column must be Datetime[*, UTC]; got {dtype!r}")


def _expected_session_minutes(day: object, tf_minutes: int) -> list[datetime]:
    """Enumerate expected UTC timestamps for the three sessions of ``day``.

    ``day`` is a ``datetime.date`` (passed positionally as ``object`` so the
    callable surface stays simple). Returns tz-aware UTC datetimes at
    ``tf_minutes`` intervals INSIDE each session window. Lunch and overnight
    gaps are excluded by construction.
    """
    from datetime import date as _date  # local import keeps the module surface clean
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    from tfex_s50_multi_tf_swing.data.session import BKK, SESSION_BOUNDS_BKK

    if not isinstance(day, _date):  # pragma: no cover — call-site guarantee
        raise TypeError(f"expected datetime.date, got {type(day).__name__}")

    expected: list[datetime] = []
    for name, (start, end) in SESSION_BOUNDS_BKK.items():
        # Convert minute-of-day BKK to absolute BKK datetime, then to UTC.
        start_bkk: _dt = _dt.combine(day, _dt.min.time(), tzinfo=BKK) + _td(minutes=start)
        end_bkk: _dt = _dt.combine(day, _dt.min.time(), tzinfo=BKK) + _td(minutes=end)
        cursor: _dt = start_bkk
        while cursor < end_bkk:
            expected.append(cursor.astimezone(__import__("datetime").timezone.utc))
            cursor = cursor + _td(minutes=tf_minutes)
        # ``name`` unused except for clarity in iteration order; mypy-strict OK.
        _ = name
    return expected


def _q(v: object) -> Decimal:
    """Quantize a numeric to 8 decimal places as a :class:`Decimal`."""
    return Decimal(f"{_as_float(v):.8f}")


def _as_float(v: object) -> float:
    """Coerce a Polars scalar / number / None to a float (None → 0.0)."""
    if v is None:
        return 0.0
    if isinstance(v, int | float):
        return float(v)
    if isinstance(v, Decimal):
        return float(v)
    # Polars may return Series / numpy scalars; both expose __float__.
    return float(v)  # type: ignore[arg-type]


__all__: list[str] = [
    "DEFAULT_CROSS_CHECK_TOLERANCE",
    "DEFAULT_SPREAD_SIGMA",
    "Validator",
]
