"""FeatureConfig / registry and the exception hierarchy."""

from __future__ import annotations

import pytest

from tfex_s50_multi_tf_swing.adapters.errors import TfexS50Error
from tfex_s50_multi_tf_swing.features.errors import (
    AlignmentError,
    FeatureError,
    FeatureInputError,
    FeatureSchemaError,
    InsufficientLookbackError,
)
from tfex_s50_multi_tf_swing.features.models import (
    INTRADAY_TIMEFRAMES,
    FeatureConfig,
    feature_columns,
    panel_arrow_schema,
    panel_polars_schema,
)


def test_intraday_columns_only_on_intraday_timeframes() -> None:
    cfg = FeatureConfig()
    cols_5m = {c.name for c in feature_columns(cfg, "5m")}
    cols_4h = {c.name for c in feature_columns(cfg, "4h")}
    assert "or_high_15" in cols_5m and "ib_high" in cols_5m
    assert "or_high_15" not in cols_4h and "ib_high" not in cols_4h
    # The non-intraday features are identical across timeframes.
    assert (cols_5m - cols_4h) == {
        "or_high_15",
        "or_low_15",
        "or_high_30",
        "or_low_30",
        "or_high_60",
        "or_low_60",
        "ib_high",
        "ib_low",
    }
    assert "5m" in INTRADAY_TIMEFRAMES and "4h" not in INTRADAY_TIMEFRAMES


def test_ema_span_columns_track_config() -> None:
    cfg = FeatureConfig(ema_spans=(8, 21, 55))
    names = {c.name for c in feature_columns(cfg, "1h")}
    assert {"ema_slope_8", "ema_slope_21", "ema_slope_55"} <= names


def test_max_lookback_is_the_largest_window() -> None:
    cfg = FeatureConfig(rv_percentile_window=500)
    assert cfg.max_lookback() == 500


def test_schemas_have_matching_columns() -> None:
    cfg = FeatureConfig()
    pol = panel_polars_schema(cfg, "5m")
    arr = panel_arrow_schema(cfg, "5m")
    assert list(pol.keys()) == arr.names


def test_error_hierarchy() -> None:
    for exc in (
        FeatureError,
        FeatureInputError,
        InsufficientLookbackError,
        FeatureSchemaError,
        AlignmentError,
    ):
        assert issubclass(exc, TfexS50Error)
    assert issubclass(InsufficientLookbackError, FeatureError)


def test_winsor_quantile_bounds_validated() -> None:
    with pytest.raises(ValueError):
        FeatureConfig(winsor_lower_q=0.7)  # must be ≤ 0.5
