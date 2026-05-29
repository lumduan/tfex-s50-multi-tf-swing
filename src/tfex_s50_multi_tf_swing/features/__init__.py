"""Feature engineering (Phase 2).

Public surface: the per-timeframe panel builder, the causal multi-timeframe
aligner, the feature store, and the configuration / column registry. Feature
math is Polars-native and look-ahead-free (see module docstrings).
"""

from __future__ import annotations

from tfex_s50_multi_tf_swing.features.align import align_timeframes
from tfex_s50_multi_tf_swing.features.errors import (
    AlignmentError,
    FeatureError,
    FeatureInputError,
    FeatureSchemaError,
    InsufficientLookbackError,
)
from tfex_s50_multi_tf_swing.features.models import (
    FeatureColumn,
    FeatureConfig,
    feature_columns,
)
from tfex_s50_multi_tf_swing.features.pipeline import build_aligned, build_panel
from tfex_s50_multi_tf_swing.features.store import FeatureStore

__all__: list[str] = [
    "AlignmentError",
    "FeatureColumn",
    "FeatureConfig",
    "FeatureError",
    "FeatureInputError",
    "FeatureSchemaError",
    "FeatureStore",
    "InsufficientLookbackError",
    "align_timeframes",
    "build_aligned",
    "build_panel",
    "feature_columns",
]
