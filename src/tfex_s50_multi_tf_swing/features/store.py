"""Parquet store for feature panels.

Layout (rooted at ``Settings.data_dir``):

* ``features/<timeframe>.parquet``   — per-timeframe feature panel
* ``features/aligned_<base>.parquet`` — causally-aligned multi-timeframe view

Per-timeframe panels are validated against the column registry in
:mod:`tfex_s50_multi_tf_swing.features.models` before write so the on-disk shape
always matches the active :class:`FeatureConfig`. The aligned panel has a
config-dependent wide schema, so it is written as-is (only its ``time`` key is
checked).

Feature columns are Float64 / Int8 / Utf8 — never Decimal. Decimal is reserved
for money at the gateway boundary; features are internal statistical quantities.
"""

from __future__ import annotations

import logging
from pathlib import Path

import polars as pl

from tfex_s50_multi_tf_swing.data.models import Timeframe
from tfex_s50_multi_tf_swing.features.errors import FeatureSchemaError
from tfex_s50_multi_tf_swing.features.models import (
    PANEL_KEYS,
    FeatureConfig,
    feature_columns,
)

logger: logging.Logger = logging.getLogger(__name__)


class FeatureStore:
    """File-system Parquet store for feature panels."""

    def __init__(self, base_dir: Path, config: FeatureConfig | None = None) -> None:
        self._base: Path = base_dir
        self._config: FeatureConfig = config or FeatureConfig()
        self._base.mkdir(parents=True, exist_ok=True)

    @property
    def base_dir(self) -> Path:
        return self._base

    def features_path(self, timeframe: Timeframe) -> Path:
        return self._base / "features" / f"{timeframe}.parquet"

    def aligned_path(self, base_timeframe: Timeframe = "5m") -> Path:
        return self._base / "features" / f"aligned_{base_timeframe}.parquet"

    def write_panel(self, timeframe: Timeframe, panel: pl.DataFrame) -> Path:
        """Validate ``panel`` against the registry and write it."""
        self._validate_panel(panel, timeframe)
        path = self.features_path(timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)
        panel.write_parquet(path, compression="zstd")
        logger.info(
            "feature store: wrote panel tf=%s rows=%d path=%s", timeframe, panel.height, path
        )
        return path

    def read_panel(self, timeframe: Timeframe) -> pl.DataFrame:
        path = self.features_path(timeframe)
        if not path.exists():
            raise FeatureSchemaError(f"feature panel not found at {path}")
        panel = pl.read_parquet(path)
        self._validate_panel(panel, timeframe)
        return panel

    def write_aligned(self, aligned: pl.DataFrame, base_timeframe: Timeframe = "5m") -> Path:
        if "time" not in aligned.columns:
            raise FeatureSchemaError("aligned panel must contain a 'time' column")
        path = self.aligned_path(base_timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)
        aligned.write_parquet(path, compression="zstd")
        logger.info(
            "feature store: wrote aligned panel base=%s rows=%d cols=%d path=%s",
            base_timeframe,
            aligned.height,
            aligned.width,
            path,
        )
        return path

    def read_aligned(self, base_timeframe: Timeframe = "5m") -> pl.DataFrame:
        path = self.aligned_path(base_timeframe)
        if not path.exists():
            raise FeatureSchemaError(f"aligned panel not found at {path}")
        return pl.read_parquet(path)

    def _validate_panel(self, panel: pl.DataFrame, timeframe: Timeframe) -> None:
        expected = [*PANEL_KEYS, *(c.name for c in feature_columns(self._config, timeframe))]
        if list(panel.columns) != expected:
            raise FeatureSchemaError(
                f"panel columns for {timeframe!r} do not match registry: "
                f"expected {expected}, got {list(panel.columns)}"
            )


__all__: list[str] = ["FeatureStore"]
