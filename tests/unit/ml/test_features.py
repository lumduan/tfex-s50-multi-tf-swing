"""Tests for feature extraction: encoding, missing/unknown handling, no-leakage shape."""

from __future__ import annotations

import math
from datetime import timedelta

import pytest

from tfex_s50_multi_tf_swing.ml.errors import FeatureExtractionError
from tfex_s50_multi_tf_swing.ml.features import (
    FEATURE_COLUMNS,
    build_feature_frame,
    build_matrix,
    build_row_index,
    encode_row,
    require_feature_columns,
)

from .conftest import T0, aligned_frame


def test_feature_columns_shape_and_order() -> None:
    assert len(FEATURE_COLUMNS) == 13
    assert FEATURE_COLUMNS[0] == "atr_ratio"
    assert FEATURE_COLUMNS[-1] == "lunch_zone_flag"
    # No raw OHLCV column may be a feature (public-data-boundary rule).
    assert not ({"open", "high", "low", "close", "volume"} & set(FEATURE_COLUMNS))


def test_encode_row_numeric_categorical_flags() -> None:
    row = {
        "atr_ratio": 0.9,
        "bollinger_squeeze": 0.7,
        "volume_expansion": 1.5,
        "dist_from_vwap": 0.5,
        "1h_dist_from_vwap": 0.2,
        "1h_atr_ratio": 0.8,
        "1h_volume_expansion": 0.1,
        "structure": "HH",
        "1h_structure": "LL",
        "1h_regime": "range_high_vol",
        "4h_bias_direction": "long",
        "liquidity_sweep_flag": 1,
        "lunch_zone_flag": 0,
    }
    vec = encode_row(row)
    assert len(vec) == len(FEATURE_COLUMNS)
    assert vec[0] == 0.9  # atr_ratio
    assert vec[7] == 1.0  # structure HH → 1
    assert vec[8] == 4.0  # 1h_structure LL → 4
    assert vec[9] == 4.0  # 1h_regime range_high_vol → 4
    assert vec[10] == 1.0  # 4h_bias_direction long → 1
    assert vec[11] == 1.0  # liquidity_sweep_flag


def test_encode_missing_numeric_is_nan() -> None:
    vec = encode_row({"structure": "HH"})
    assert math.isnan(vec[0])  # atr_ratio absent → NaN (LightGBM-missing)


def test_encode_unknown_category_is_zero_bucket() -> None:
    vec = encode_row({"structure": "??", "1h_regime": "mystery", "4h_bias_direction": None})
    assert vec[7] == 0.0  # unknown structure
    assert vec[9] == 0.0  # unknown regime
    assert vec[10] == 0.0  # null bias → unknown bucket


def test_encode_non_numeric_value_is_nan() -> None:
    assert math.isnan(encode_row({"atr_ratio": "oops"})[0])


@pytest.mark.parametrize(("value", "expected"), [(True, 1.0), (False, 0.0), (1, 1.0), (0, 0.0)])
def test_flag_encoding(value: object, expected: float) -> None:
    assert encode_row({"liquidity_sweep_flag": value})[11] == expected


def test_flag_non_numeric_is_zero() -> None:
    assert encode_row({"liquidity_sweep_flag": "x"})[11] == 0.0


def test_build_matrix_empty_and_nonempty() -> None:
    assert build_matrix([]).shape == (0, len(FEATURE_COLUMNS))
    matrix = build_matrix([{"atr_ratio": 1.0}, {"atr_ratio": 2.0}])
    assert matrix.shape == (2, len(FEATURE_COLUMNS))


def test_require_feature_columns_raises_on_missing() -> None:
    frame = aligned_frame(5).drop("atr_ratio")
    with pytest.raises(FeatureExtractionError, match="missing feature columns"):
        require_feature_columns(frame)


def test_build_row_index_keys_by_time() -> None:
    frame = aligned_frame(6)
    index = build_row_index(frame)
    assert T0 in index
    assert index[T0]["1d_regime"] == "trend_up"


def test_build_row_index_requires_time_column() -> None:
    frame = aligned_frame(3).drop("time")
    with pytest.raises(FeatureExtractionError):
        build_row_index(frame)


def test_build_feature_frame_matches_times() -> None:
    frame = aligned_frame(6)
    times = [T0, T0 + timedelta(hours=1)]
    matrix = build_feature_frame(frame, times)
    assert matrix.shape == (2, len(FEATURE_COLUMNS))


def test_build_feature_frame_missing_time_raises() -> None:
    frame = aligned_frame(6)
    with pytest.raises(FeatureExtractionError, match="no aligned-frame row"):
        build_feature_frame(frame, [T0 + timedelta(days=99)])
