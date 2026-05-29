"""Causal multi-timeframe alignment.

Higher-timeframe features must never leak onto a lower-timeframe bar before the
HTF bar has *closed*. Bars are open-labelled (confirmed in
:mod:`tfex_s50_multi_tf_swing.data.fetcher`), so an HTF bar stamped ``time=t``
only becomes usable at ``t + TIMEFRAME_MINUTES[tf]``. :func:`align_timeframes`
therefore shifts each HTF panel by its bar duration to an ``available_at`` key
and performs a backward as-of join — attaching, to every base-TF bar, the most
recent HTF feature row whose bar had already closed.

This is the single most dangerous look-ahead trap in a multi-timeframe system;
``tests/unit/features/test_align.py`` asserts no future HTF value can appear.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import polars as pl

from tfex_s50_multi_tf_swing.data.models import TIMEFRAME_MINUTES, Timeframe
from tfex_s50_multi_tf_swing.features.errors import AlignmentError
from tfex_s50_multi_tf_swing.features.models import PANEL_KEYS


def align_timeframes(
    base: pl.DataFrame,
    *,
    base_timeframe: Timeframe,
    higher: Mapping[Timeframe, pl.DataFrame],
    columns: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Attach higher-timeframe features to each base-TF bar, causally.

    Args:
        base: The base (lowest) timeframe panel; must carry a tz-aware UTC
            ``time`` column and be sortable by it.
        base_timeframe: The timeframe of ``base`` (e.g. ``"5m"``).
        higher: Mapping of higher timeframe → its feature panel. Every key must
            be strictly coarser than ``base_timeframe``.
        columns: Optional subset of HTF feature columns to bring across. Panel
            key columns (``time`` / ``timeframe``) are always excluded.

    Returns:
        ``base`` widened with ``{tf}_{column}`` columns for each higher tf.
    """
    if "time" not in base.columns:
        raise AlignmentError("base panel must contain a 'time' column")
    base_minutes = TIMEFRAME_MINUTES[base_timeframe]
    result = base.sort("time")

    for htf, panel in higher.items():
        if TIMEFRAME_MINUTES[htf] <= base_minutes:
            raise AlignmentError(
                f"higher timeframe {htf!r} ({TIMEFRAME_MINUTES[htf]}m) is not coarser "
                f"than base {base_timeframe!r} ({base_minutes}m)"
            )
        result = _join_one(result, htf=htf, panel=panel, columns=columns)
    return result


def _join_one(
    base: pl.DataFrame,
    *,
    htf: Timeframe,
    panel: pl.DataFrame,
    columns: Sequence[str] | None,
) -> pl.DataFrame:
    feature_cols = [c for c in panel.columns if c not in PANEL_KEYS]
    if columns is not None:
        missing = [c for c in columns if c not in feature_cols]
        if missing:
            raise AlignmentError(f"requested columns absent from {htf!r} panel: {missing}")
        feature_cols = list(columns)

    duration = pl.duration(minutes=TIMEFRAME_MINUTES[htf])
    renamed = {c: f"{htf}_{c}" for c in feature_cols}
    htf_sel = (
        panel.select(["time", *feature_cols])
        .with_columns((pl.col("time") + duration).alias("_available_at"))
        .rename(renamed)
        .drop("time")
        .sort("_available_at")
    )
    return base.join_asof(
        htf_sel,
        left_on="time",
        right_on="_available_at",
        strategy="backward",
    ).drop("_available_at")


__all__: list[str] = ["align_timeframes"]
