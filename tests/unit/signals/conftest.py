"""Shared fixtures and builders for the signal-layer tests.

The strategies read a wide *aligned 1H* frame (``1d_bias_direction`` + ``1d_regime`` + 1H
base columns). Building it through the full pipeline is slow and ``structure`` is often null on
sparse synthetic pivots, so — exactly like the regime / bias suites — tests hand-build one row
per gate branch.

A single source of truth keeps the frame and scalar paths in lock-step: a baseline is expressed
as **``SetupFeatures`` keyword args**; :func:`feats` builds the scalar model and :func:`to_row`
maps the same kwargs to the aligned frame's column names, so ``classify_row`` and
``classify_frame`` are guaranteed to see identical inputs (the parity tests rely on this).

.. note::
   Updated for the 1H-execution migration (2026-06-05): ``1d_bias_direction`` replaces
   ``4h_bias_direction``, ``1d_regime`` replaces ``1h_regime``, and the 1H base features
   are unprefixed. The ``h1_*`` attribute names in baselines map to the base columns
   (e.g. ``h1_dist_from_vwap`` → ``dist_from_vwap``) for backward-compatible test code.
"""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl

from tfex_s50_multi_tf_swing.signals.models import SetupFeatures

_T0 = datetime(2026, 1, 5, 3, 0, tzinfo=UTC)

# Aligned-frame column dtypes (forces dtypes even when a cell is ``None``).
SCHEMA: dict[str, pl.DataType] = {
    "time": pl.Datetime(time_unit="us", time_zone="UTC"),
    "1d_bias_direction": pl.Utf8(),
    "1d_regime": pl.Utf8(),
    "atr_ratio": pl.Float64(),
    "bollinger_squeeze": pl.Float64(),
    "volume_expansion": pl.Float64(),
    "dist_from_vwap": pl.Float64(),
    "structure": pl.Utf8(),
    "close": pl.Float64(),
    "swing_high": pl.Float64(),
    "swing_low": pl.Float64(),
    "or_high_60": pl.Float64(),
    "or_low_60": pl.Float64(),
    "liquidity_sweep_flag": pl.Int8(),
    "lunch_zone_flag": pl.Int8(),
}

# Map a ``SetupFeatures`` attribute name to its aligned-frame column name.
# ``h1_*`` attributes are deprecated but map to the base 1H columns for backward compat.
_ATTR_TO_COL: dict[str, str] = {
    "time": "time",
    "bias_direction": "1d_bias_direction",
    "regime": "1d_regime",
    "h1_dist_from_vwap": "dist_from_vwap",
    "h1_structure": "structure",
    "h1_atr_ratio": "atr_ratio",
    "h1_volume_expansion": "volume_expansion",
    "atr_ratio": "atr_ratio",
    "bollinger_squeeze": "bollinger_squeeze",
    "volume_expansion": "volume_expansion",
    "dist_from_vwap": "dist_from_vwap",
    "structure": "structure",
    "close": "close",
    "swing_high": "swing_high",
    "swing_low": "swing_low",
    "or_high": "or_high_60",
    "or_low": "or_low_60",
    "liquidity_sweep_flag": "liquidity_sweep_flag",
    "lunch_zone_flag": "lunch_zone_flag",
}

# A clean long for Strategy B (ORB): directional bias, trending regime, breakout above OR.
# 1H is now the base timeframe — all features are on the 1H frame.
LONG_BASE: dict[str, object] = {
    "time": _T0,
    "bias_direction": "long",
    "regime": "trend_up",
    "h1_dist_from_vwap": 0.2,
    "h1_structure": "HH",
    "h1_atr_ratio": 0.8,
    "h1_volume_expansion": 0.2,
    "atr_ratio": 0.9,
    "bollinger_squeeze": 0.7,
    "volume_expansion": 1.5,
    "dist_from_vwap": 0.5,
    "structure": "HH",
    "close": 105.0,
    "swing_high": 100.0,
    "swing_low": 95.0,
    "or_high": 100.0,
    "or_low": 96.0,
    "liquidity_sweep_flag": 0,
    "lunch_zone_flag": 0,
}

# The exact mirror — a clean short for Strategy B.
SHORT_BASE: dict[str, object] = {
    "time": _T0,
    "bias_direction": "short",
    "regime": "trend_down",
    "h1_dist_from_vwap": -0.2,
    "h1_structure": "LL",
    "h1_atr_ratio": 0.8,
    "h1_volume_expansion": 0.2,
    "atr_ratio": 0.9,
    "bollinger_squeeze": 0.7,
    "volume_expansion": 1.5,
    "dist_from_vwap": -0.5,
    "structure": "LL",
    "close": 90.0,
    "swing_high": 100.0,
    "swing_low": 95.0,
    "or_high": 100.0,
    "or_low": 96.0,
    "liquidity_sweep_flag": 0,
    "lunch_zone_flag": 0,
}

# A clean Strategy-C long (range_high_vol regime, confirmed sweep, reclaim above VWAP).
# Strategy C is permanently disabled — these baselines are kept for reference.
SWEEP_BASE: dict[str, object] = {
    "time": _T0,
    "bias_direction": "neutral",
    "regime": "range_high_vol",
    "h1_dist_from_vwap": 0.0,
    "h1_structure": None,
    "h1_atr_ratio": 1.0,
    "h1_volume_expansion": 0.0,
    "atr_ratio": 1.0,
    "bollinger_squeeze": 1.0,
    "volume_expansion": 0.5,
    "dist_from_vwap": 0.5,
    "structure": "HH",
    "close": 100.0,
    "swing_high": 110.0,
    "swing_low": 95.0,
    "or_high": None,
    "or_low": None,
    "liquidity_sweep_flag": 1,
    "lunch_zone_flag": 0,
}


def merged(base: dict[str, object], **overrides: object) -> dict[str, object]:
    """Return ``base`` with ``overrides`` applied (kwargs are ``SetupFeatures`` attr names)."""
    out = dict(base)
    out.update(overrides)
    return out


def feats(base: dict[str, object], **overrides: object) -> SetupFeatures:
    """Build a :class:`SetupFeatures` from a baseline with overrides."""
    return SetupFeatures(**merged(base, **overrides))  # type: ignore[arg-type]


def to_row(base: dict[str, object], **overrides: object) -> dict[str, object]:
    """Map a baseline (+ overrides) to an aligned-frame row dict."""
    kw = merged(base, **overrides)
    return {_ATTR_TO_COL[k]: v for k, v in kw.items()}


def frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    """Build an aligned 1H frame with the canonical :data:`SCHEMA` dtypes."""
    return pl.DataFrame(rows, schema=SCHEMA)
