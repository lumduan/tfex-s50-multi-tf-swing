"""Tests for regime Pydantic models, settings wiring, and the error hierarchy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from tfex_s50_multi_tf_swing.adapters.errors import TfexS50Error
from tfex_s50_multi_tf_swing.config.settings import Settings
from tfex_s50_multi_tf_swing.regime.errors import (
    RegimeError,
    RegimeInputError,
    RegimePolicyError,
    UnknownRegimeError,
)
from tfex_s50_multi_tf_swing.regime.models import (
    RegimeClassification,
    RegimeFeatures,
    RegimeThresholds,
)


def test_error_hierarchy_roots_at_tfex_base() -> None:
    assert issubclass(RegimeError, TfexS50Error)
    assert issubclass(RegimeInputError, RegimeError)
    assert issubclass(RegimePolicyError, RegimeError)
    assert issubclass(UnknownRegimeError, RegimePolicyError)


def test_thresholds_bounds_validation() -> None:
    RegimeThresholds(panic_rv=0.99)  # in range
    with pytest.raises(ValidationError):
        RegimeThresholds(panic_rv=1.5)
    with pytest.raises(ValidationError):
        RegimeThresholds(panic_volume_z=0.0)


def test_regime_features_bounds() -> None:
    with pytest.raises(ValidationError):
        RegimeFeatures(
            ema_fast_minus_slow=0.0,
            ema_slope_fast=0.0,
            structure=None,
            dist_from_vwap=0.0,
            rv_percentile=1.5,  # out of [0, 1]
            trend_persistence=0.0,
            volume_expansion=0.0,
            range_compression=0,
        )
    with pytest.raises(ValidationError):
        RegimeFeatures(
            ema_fast_minus_slow=0.0,
            ema_slope_fast=0.0,
            structure=None,
            dist_from_vwap=0.0,
            rv_percentile=0.5,
            trend_persistence=0.0,
            volume_expansion=0.0,
            range_compression=2,  # only 0/1 allowed
        )


def test_classification_requires_utc_time() -> None:
    ok = RegimeClassification(
        time=datetime(2026, 5, 29, 1, 0, tzinfo=UTC), timeframe="4h", regime="trend_up"
    )
    assert ok.regime == "trend_up"

    with pytest.raises(ValidationError):
        RegimeClassification(time=datetime(2026, 5, 29, 1, 0), timeframe="4h", regime="trend_up")
    bkk = timezone(timedelta(hours=7))
    with pytest.raises(ValidationError):
        RegimeClassification(
            time=datetime(2026, 5, 29, 8, 0, tzinfo=bkk), timeframe="4h", regime="trend_up"
        )


def test_models_are_frozen() -> None:
    thr = RegimeThresholds()
    with pytest.raises(ValidationError):
        thr.panic_rv = 0.5


def test_settings_regime_thresholds_match_defaults() -> None:
    """Guard against Settings defaults drifting from RegimeThresholds defaults."""
    assert Settings().regime_thresholds() == RegimeThresholds()
