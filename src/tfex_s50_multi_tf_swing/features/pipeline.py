"""§2.6 Feature pipeline — assemble, winsorise, trailing z-score.

``build_panel`` turns one back-adjusted continuous OHLCV frame into a feature
panel keyed by ``(time, timeframe)``. Order of operations:

1. Validate the input contract (tz-aware UTC, monotonic, no dups, enough bars).
2. Cast Decimal prices to Float64 (features are statistical, not money).
3. Tag sessions, then add the shared ``_atr`` / swing-pivot / ADX helper columns.
4. Run each feature group (trend, volatility, time-of-day, structure, regime).
5. Select the registered columns, winsorise (1/99, trailing) and z-score
   (trailing window) the unbounded continuous features, and validate the panel
   against the registry.

Every step is trailing-only or shifted-forward — no look-ahead. The
``test_pipeline`` look-ahead regression test proves features on a prefix equal
features on the full series for overlapping rows.
"""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from tfex_s50_multi_tf_swing.data.models import TIMEFRAME_MINUTES, Timeframe
from tfex_s50_multi_tf_swing.features.align import align_timeframes
from tfex_s50_multi_tf_swing.features.errors import (
    FeatureInputError,
    FeatureSchemaError,
    InsufficientLookbackError,
)
from tfex_s50_multi_tf_swing.features.indicators import atr, with_adx, with_swing_pivots
from tfex_s50_multi_tf_swing.features.models import (
    FeatureConfig,
    feature_columns,
    panel_polars_schema,
)
from tfex_s50_multi_tf_swing.features.regime import add_regime
from tfex_s50_multi_tf_swing.features.structure import add_structure
from tfex_s50_multi_tf_swing.features.time_of_day import add_time_of_day, with_session_columns
from tfex_s50_multi_tf_swing.features.trend import add_trend
from tfex_s50_multi_tf_swing.features.volatility import add_volatility

_REQUIRED_OHLCV: frozenset[str] = frozenset({"time", "open", "high", "low", "close", "volume"})

# f64 features that are already bounded / normalised and must NOT be z-scored.
_NO_NORMALISE: frozenset[str] = frozenset(
    {"rv_percentile", "trend_persistence", "volume_expansion"}
)
_NO_NORMALISE_PREFIXES: tuple[str, ...] = ("or_high_", "or_low_", "ib_high", "ib_low")


def build_panel(
    df: pl.DataFrame, timeframe: Timeframe, config: FeatureConfig | None = None
) -> pl.DataFrame:
    """Build the feature panel for one timeframe from a continuous OHLCV frame."""
    config = config or FeatureConfig()
    _require_ohlcv(df, config)

    work = df.sort("time").with_columns(
        pl.col("open").cast(pl.Float64),
        pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64),
        pl.col("close").cast(pl.Float64),
        pl.col("volume").cast(pl.Float64),
    )
    work = with_session_columns(work)
    work = work.with_columns(atr(config.atr_period).alias("_atr"))
    work = with_swing_pivots(work, config.swing_lookback)
    work = with_adx(work, config.adx_period)

    work = add_trend(work, config)
    work = add_volatility(work, config)
    work = add_time_of_day(work, config, timeframe)
    work = add_structure(work, config, timeframe)
    work = add_regime(work, config)

    work = work.with_columns(pl.lit(timeframe).alias("timeframe"))
    panel = _select_and_cast(work, timeframe, config)
    if config.normalise:
        panel = _normalise(panel, timeframe, config)
    return panel


def build_aligned(
    panels: Mapping[Timeframe, pl.DataFrame],
    *,
    base_timeframe: Timeframe = "5m",
) -> pl.DataFrame:
    """Causally widen the base-TF panel with every coarser TF's features."""
    if base_timeframe not in panels:
        raise FeatureInputError(f"base timeframe {base_timeframe!r} missing from panels")
    base_minutes = TIMEFRAME_MINUTES[base_timeframe]
    higher = {tf: p for tf, p in panels.items() if TIMEFRAME_MINUTES[tf] > base_minutes}
    return align_timeframes(panels[base_timeframe], base_timeframe=base_timeframe, higher=higher)


def _require_ohlcv(df: pl.DataFrame, config: FeatureConfig) -> None:
    missing = _REQUIRED_OHLCV - set(df.columns)
    if missing:
        raise FeatureInputError(f"input frame missing required columns: {sorted(missing)}")
    if df.height == 0:
        raise InsufficientLookbackError("input frame is empty")

    time_dtype = df.schema["time"]
    if not isinstance(time_dtype, pl.Datetime) or time_dtype.time_zone is None:
        raise FeatureInputError(f"'time' must be tz-aware Datetime, got {time_dtype}")

    times = df.get_column("time")
    if times.is_duplicated().any():
        raise FeatureInputError("duplicate timestamps in input frame")
    if not times.sort().equals(times):
        # Non-fatal ordering is handled by sort() downstream, but a frame that is
        # not monotonic usually signals a data bug — fail loud per the brief.
        raise FeatureInputError("'time' column is not monotonically increasing")

    min_bars = config.max_lookback()
    if df.height < min_bars:
        raise InsufficientLookbackError(
            f"need ≥ {min_bars} bars for the configured windows, got {df.height}"
        )


def _select_and_cast(
    work: pl.DataFrame, timeframe: Timeframe, config: FeatureConfig
) -> pl.DataFrame:
    schema = panel_polars_schema(config, timeframe)
    expected = list(schema.keys())
    missing = [c for c in expected if c not in work.columns]
    if missing:  # pragma: no cover — defensive; the groups always produce these.
        raise FeatureSchemaError(f"pipeline did not produce columns: {missing}")
    casts = [pl.col(name).cast(dtype) for name, dtype in schema.items()]
    return work.select(expected).with_columns(casts)


def _normalise(panel: pl.DataFrame, timeframe: Timeframe, config: FeatureConfig) -> pl.DataFrame:
    cols = [
        c.name
        for c in feature_columns(config, timeframe)
        if c.dtype == "f64" and _should_normalise(c.name)
    ]
    win = config.zscore_window
    exprs: list[pl.Expr] = []
    for name in cols:
        lo = pl.col(name).rolling_quantile(quantile=config.winsor_lower_q, window_size=win)
        hi = pl.col(name).rolling_quantile(quantile=config.winsor_upper_q, window_size=win)
        clipped = pl.col(name).clip(lower_bound=lo, upper_bound=hi)
        mean = clipped.rolling_mean(window_size=win)
        std = clipped.rolling_std(window_size=win)
        exprs.append(((clipped - mean) / std).alias(name))
    return panel.with_columns(exprs) if exprs else panel


def _should_normalise(name: str) -> bool:
    if name in _NO_NORMALISE:
        return False
    return not name.startswith(_NO_NORMALISE_PREFIXES)


__all__: list[str] = ["build_aligned", "build_panel"]
