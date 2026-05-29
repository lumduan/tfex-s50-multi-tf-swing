"""Type contracts for the feature layer.

Two things live here:

* :class:`FeatureConfig` — a frozen Pydantic model holding every window /
  period parameter. Defaults are sensible swing-intraday values; callers may
  override per backtest. Because it is the single source of window sizes, the
  pipeline derives its required-lookback from it.
* The **feature-column registry** — :func:`feature_columns` returns the ordered
  list of output columns for a given ``(config, timeframe)``. It drives both the
  Parquet schema in :mod:`tfex_s50_multi_tf_swing.features.store` and the
  output-schema validation in :mod:`tfex_s50_multi_tf_swing.features.pipeline`.

Feature columns are :class:`float` (``f64``), flags are ``i8`` and categoricals
are ``str``. Decimal is reserved for money at the gateway boundary; features are
internal statistical quantities and never cross it (see the Phase 2 plan).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import polars as pl
import pyarrow as pa
from pydantic import BaseModel, ConfigDict, Field

from tfex_s50_multi_tf_swing.data.models import Timeframe

FeatureDtype = Literal["f64", "i8", "str"]
"""Compact dtype tag for a feature column."""

# Timeframes on which intraday-only features (opening range, initial balance)
# are meaningful. On 4h a 15-minute opening range is degenerate, so we omit it.
INTRADAY_TIMEFRAMES: tuple[Timeframe, ...] = ("5m", "1h")

# Identity columns carried alongside every panel (not winsorised / z-scored).
PANEL_KEYS: tuple[str, ...] = ("time", "timeframe")


class FeatureConfig(BaseModel):
    """Window / period parameters for the feature pipeline.

    Frozen so a config instance is a stable cache key and cannot drift mid-run.
    Every numeric window is ``ge``-bounded; the pipeline computes its
    minimum-required bar count as the max across these.
    """

    model_config = ConfigDict(frozen=True)

    # Trend
    ema_spans: tuple[int, ...] = (20, 50)
    swing_lookback: int = Field(default=3, ge=1)

    # Volatility
    atr_period: int = Field(default=14, ge=2)
    atr_short: int = Field(default=14, ge=2)
    atr_long: int = Field(default=50, ge=2)
    bb_period: int = Field(default=20, ge=2)
    bb_k: float = Field(default=2.0, gt=0)
    keltner_period: int = Field(default=20, ge=2)
    keltner_m: float = Field(default=1.5, gt=0)
    realised_vol_windows: tuple[int, ...] = (12, 48)

    # Time-of-day / structure
    opening_range_minutes: tuple[int, ...] = (15, 30, 60)
    initial_balance_minutes: int = Field(default=60, ge=5)
    close_auction_minutes: int = Field(default=15, ge=1)

    # Market structure
    liquidity_lookback: int = Field(default=20, ge=2)
    liquidity_confirm_bars: int = Field(default=3, ge=1)

    # Regime
    adx_period: int = Field(default=14, ge=2)
    rv_percentile_window: int = Field(default=252, ge=10)
    trend_persistence_window: int = Field(default=20, ge=2)
    volume_zscore_window: int = Field(default=20, ge=2)
    range_compression_adx_threshold: float = Field(default=20.0, gt=0)
    range_compression_atr_ratio_threshold: float = Field(default=1.0, gt=0)

    # Normalisation (pipeline)
    winsor_lower_q: float = Field(default=0.01, ge=0.0, le=0.5)
    winsor_upper_q: float = Field(default=0.99, ge=0.5, le=1.0)
    zscore_window: int = Field(default=100, ge=10)
    normalise: bool = True

    def max_lookback(self) -> int:
        """Largest window (in bars) any feature group needs to be well-defined."""
        return max(
            *self.ema_spans,
            self.atr_long,
            self.bb_period,
            self.keltner_period,
            *self.realised_vol_windows,
            self.liquidity_lookback,
            self.adx_period,
            self.rv_percentile_window,
            self.trend_persistence_window,
            self.volume_zscore_window,
            self.zscore_window,
            2 * self.swing_lookback + 1,
        )


@dataclass(frozen=True)
class FeatureColumn:
    """One output column of the feature panel."""

    name: str
    dtype: FeatureDtype
    group: str
    description: str


_POLARS_DTYPE: dict[FeatureDtype, pl.DataType] = {
    "f64": pl.Float64(),
    "i8": pl.Int8(),
    "str": pl.Utf8(),
}

_ARROW_DTYPE: dict[FeatureDtype, pa.DataType] = {
    "f64": pa.float64(),
    "i8": pa.int8(),
    "str": pa.string(),
}


def feature_columns(config: FeatureConfig, timeframe: Timeframe) -> list[FeatureColumn]:
    """Return the ordered feature columns produced for ``(config, timeframe)``.

    The set is timeframe-aware: opening-range and initial-balance columns are
    emitted only for :data:`INTRADAY_TIMEFRAMES`.
    """
    cols: list[FeatureColumn] = []

    # Trend
    for n in config.ema_spans:
        cols.append(
            FeatureColumn(f"ema_slope_{n}", "f64", "trend", f"ATR-normalised {n}-bar EMA slope")
        )
    cols.append(FeatureColumn("dist_from_vwap", "f64", "trend", "(close - session VWAP) / ATR"))
    cols.append(FeatureColumn("structure", "str", "trend", "HH/HL/LH/LL from confirmed pivots"))

    # Volatility
    cols.append(FeatureColumn("atr_ratio", "f64", "volatility", "ATR_short / ATR_long"))
    cols.append(FeatureColumn("bollinger_squeeze", "f64", "volatility", "BB width / Keltner width"))
    for h in config.realised_vol_windows:
        cols.append(
            FeatureColumn(
                f"realised_vol_{h}", "f64", "volatility", f"rolling realised vol, {h} bars"
            )
        )

    # Time-of-day
    if timeframe in INTRADAY_TIMEFRAMES:
        for w in config.opening_range_minutes:
            cols.append(
                FeatureColumn(f"or_high_{w}", "f64", "time_of_day", f"opening-range high {w}m")
            )
            cols.append(
                FeatureColumn(f"or_low_{w}", "f64", "time_of_day", f"opening-range low {w}m")
            )
    cols.append(FeatureColumn("lunch_zone_flag", "i8", "time_of_day", "12:00-14:00 dead zone"))
    cols.append(FeatureColumn("close_auction_flag", "i8", "time_of_day", "last 15m of afternoon"))
    cols.append(FeatureColumn("session_phase", "str", "time_of_day", "time-of-day bucket"))

    # Market structure
    cols.append(FeatureColumn("overnight_gap", "f64", "structure", "session gap / ATR"))
    cols.append(
        FeatureColumn("dist_to_prev_high", "f64", "structure", "(close - prev day H) / ATR")
    )
    cols.append(FeatureColumn("dist_to_prev_low", "f64", "structure", "(close - prev day L) / ATR"))
    if timeframe in INTRADAY_TIMEFRAMES:
        cols.append(FeatureColumn("ib_high", "f64", "structure", "initial-balance high"))
        cols.append(FeatureColumn("ib_low", "f64", "structure", "initial-balance low"))
    cols.append(FeatureColumn("liquidity_sweep_flag", "i8", "structure", "swing sweep + reversal"))

    # Regime
    cols.append(FeatureColumn("rv_percentile", "f64", "regime", "rolling realised-vol percentile"))
    cols.append(
        FeatureColumn("trend_persistence", "f64", "regime", "rolling return sign agreement")
    )
    cols.append(FeatureColumn("range_compression", "i8", "regime", "low ATR + low ADX flag"))
    cols.append(FeatureColumn("volume_expansion", "f64", "regime", "trailing volume z-score"))

    return cols


def panel_polars_schema(config: FeatureConfig, timeframe: Timeframe) -> dict[str, pl.DataType]:
    """Polars schema (key columns + features) for a per-timeframe panel."""
    schema: dict[str, pl.DataType] = {
        "time": pl.Datetime(time_unit="us", time_zone="UTC"),
        "timeframe": pl.Utf8(),
    }
    for col in feature_columns(config, timeframe):
        schema[col.name] = _POLARS_DTYPE[col.dtype]
    return schema


def panel_arrow_schema(config: FeatureConfig, timeframe: Timeframe) -> pa.Schema:
    """PyArrow schema for the on-disk per-timeframe panel Parquet."""
    fields: list[pa.Field] = [
        pa.field("time", pa.timestamp("us", tz="UTC")),
        pa.field("timeframe", pa.string()),
    ]
    fields.extend(
        pa.field(col.name, _ARROW_DTYPE[col.dtype]) for col in feature_columns(config, timeframe)
    )
    return pa.schema(fields)


__all__: list[str] = [
    "INTRADAY_TIMEFRAMES",
    "PANEL_KEYS",
    "FeatureColumn",
    "FeatureConfig",
    "FeatureDtype",
    "feature_columns",
    "panel_arrow_schema",
    "panel_polars_schema",
]
