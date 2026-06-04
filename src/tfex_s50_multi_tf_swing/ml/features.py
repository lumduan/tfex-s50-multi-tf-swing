"""Feature extraction for the probability filter (ROADMAP §6.2).

The model reads a **fixed, ordered** :data:`FEATURE_COLUMNS` vector built only from columns
the aligned 5m signal-input frame already carries (``signals.build_signal_inputs``). Those
columns are availability-shifted by construction, so reading them at a signal's trigger time
is **look-ahead-free** — the filter never re-derives or re-fetches anything.

Encoding rules (deterministic, so a model trained today scores identically tomorrow):

* **Numeric** features pass through as ``float``; ``None`` / NaN become ``np.nan``, which
  LightGBM treats natively as missing (no misleading sentinel value is injected).
* **Categoricals** (``structure`` / ``1h_structure`` / ``1h_regime`` / ``4h_bias_direction``)
  map to fixed small integers with an explicit ``0`` "unknown" bucket for any unseen / null
  value — an unseen category never raises at inference.
* **Flags** are already ``0`` / ``1``; ``None`` becomes ``0``.

No raw OHLCV column (``open`` / ``high`` / ``low`` / ``close`` / ``volume``) is ever a
feature — the public-data-boundary rule applies to the model just as to the gateway.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime

import numpy as np
import numpy.typing as npt
import polars as pl

from tfex_s50_multi_tf_swing.ml.errors import FeatureExtractionError

#: Numeric features (passed through; missing → ``np.nan``).
NUMERIC_FEATURES: tuple[str, ...] = (
    "atr_ratio",
    "bollinger_squeeze",
    "volume_expansion",
    "dist_from_vwap",
    "1h_dist_from_vwap",
    "1h_atr_ratio",
    "1h_volume_expansion",
)

#: Categorical features (encoded to a fixed small-int space with a ``0`` unknown bucket).
CATEGORICAL_FEATURES: tuple[str, ...] = (
    "structure",
    "1h_structure",
    "1h_regime",
    "4h_bias_direction",
)

#: Binary session flags (``0`` / ``1``; missing → ``0``).
FLAG_FEATURES: tuple[str, ...] = ("liquidity_sweep_flag", "lunch_zone_flag")

#: The ordered feature vector the model consumes. Order is part of the contract — a model
#: card records it so a frame with shuffled columns cannot be silently mis-scored.
FEATURE_COLUMNS: tuple[str, ...] = (*NUMERIC_FEATURES, *CATEGORICAL_FEATURES, *FLAG_FEATURES)

# Fixed categorical encodings. ``0`` is the reserved "unknown / null" bucket everywhere.
_STRUCTURE_CODE: dict[str, float] = {"HH": 1.0, "HL": 2.0, "LH": 3.0, "LL": 4.0}
_REGIME_CODE: dict[str, float] = {
    "trend_up": 1.0,
    "trend_down": 2.0,
    "range_low_vol": 3.0,
    "range_high_vol": 4.0,
    "panic": 5.0,
}
_BIAS_CODE: dict[str, float] = {"neutral": 0.0, "long": 1.0, "short": 2.0}

_CATEGORICAL_CODES: dict[str, dict[str, float]] = {
    "structure": _STRUCTURE_CODE,
    "1h_structure": _STRUCTURE_CODE,
    "1h_regime": _REGIME_CODE,
    "4h_bias_direction": _BIAS_CODE,
}


def _to_float(value: object) -> float:
    """Cast a numeric cell to ``float``; ``None`` / NaN → ``np.nan`` (LightGBM-missing)."""
    if value is None:
        return math.nan
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return math.nan
    return out


def _encode_categorical(column: str, value: object) -> float:
    """Map a categorical cell to its fixed code; unseen / null → the ``0`` unknown bucket."""
    if not isinstance(value, str):
        return 0.0
    return _CATEGORICAL_CODES[column].get(value, 0.0)


def _encode_flag(value: object) -> float:
    """Map a session flag to ``0`` / ``1``; ``None`` / non-numeric → ``0``."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return 1.0 if int(value) else 0.0
    return 0.0


def encode_row(row: Mapping[str, object]) -> list[float]:
    """Encode one aligned-frame row to the ordered :data:`FEATURE_COLUMNS` float vector."""
    out: list[float] = []
    for column in NUMERIC_FEATURES:
        out.append(_to_float(row.get(column)))
    for column in CATEGORICAL_FEATURES:
        out.append(_encode_categorical(column, row.get(column)))
    for column in FLAG_FEATURES:
        out.append(_encode_flag(row.get(column)))
    return out


def build_matrix(rows: Sequence[Mapping[str, object]]) -> npt.NDArray[np.float64]:
    """Stack encoded rows into a ``(len(rows), len(FEATURE_COLUMNS))`` float matrix."""
    if not rows:
        return np.empty((0, len(FEATURE_COLUMNS)), dtype=np.float64)
    return np.asarray([encode_row(row) for row in rows], dtype=np.float64)


def require_feature_columns(inputs: pl.DataFrame) -> None:
    """Raise :class:`FeatureExtractionError` if ``inputs`` lacks a required feature column.

    Categorical columns may legitimately be absent on the ``engine`` source (e.g. no 4H
    frame); those are excluded from the hard requirement and default to the unknown bucket.
    Only the always-present 5m base columns are required.
    """
    required = (*NUMERIC_FEATURES[:4], *FLAG_FEATURES, "structure")
    missing = [c for c in required if c not in inputs.columns]
    if missing:
        raise FeatureExtractionError(f"aligned frame missing feature columns: {sorted(missing)}")


def build_row_index(inputs: pl.DataFrame) -> dict[datetime, dict[str, object]]:
    """Index the aligned frame by ``time`` for O(1) per-signal row lookup.

    On the rare duplicate ``time`` the last row wins (frames are time-sorted; a duplicate
    would be a malformed input the upstream pipeline already guards against).
    """
    require_feature_columns(inputs)
    if "time" not in inputs.columns:
        raise FeatureExtractionError("aligned frame missing the 'time' column")
    index: dict[datetime, dict[str, object]] = {}
    for row in inputs.iter_rows(named=True):
        index[row["time"]] = row
    return index


def build_feature_frame(inputs: pl.DataFrame, times: Sequence[datetime]) -> npt.NDArray[np.float64]:
    """Build the feature matrix for ``times`` (each must exist in ``inputs``).

    Used by training where every labelled time comes from the frame. The inference filter
    instead looks rows up itself so it can *degrade* (keep the signal) on a missing row,
    rather than raise.
    """
    index = build_row_index(inputs)
    rows: list[Mapping[str, object]] = []
    for t in times:
        row = index.get(t)
        if row is None:
            raise FeatureExtractionError(f"no aligned-frame row for time {t!r}")
        rows.append(row)
    return build_matrix(rows)


__all__: list[str] = [
    "CATEGORICAL_FEATURES",
    "FEATURE_COLUMNS",
    "FLAG_FEATURES",
    "NUMERIC_FEATURES",
    "build_feature_frame",
    "build_matrix",
    "build_row_index",
    "encode_row",
    "require_feature_columns",
]
