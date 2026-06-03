"""Tests for the bias models, config, and error hierarchy."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tfex_s50_multi_tf_swing.adapters.errors import TfexS50Error
from tfex_s50_multi_tf_swing.bias.errors import BiasError, BiasInputError
from tfex_s50_multi_tf_swing.bias.models import (
    BIAS_DIRECTIONS,
    DEFAULT_NEUTRAL_REGIMES,
    BiasConfig,
    BiasSignal,
)
from tfex_s50_multi_tf_swing.config.settings import Settings


def test_bias_directions_tuple() -> None:
    assert BIAS_DIRECTIONS == ("long", "short", "neutral")


def test_config_defaults() -> None:
    config = BiasConfig()
    assert config.slope_deadband == 0.0
    assert config.vwap_deadband == 0.0
    assert config.neutral_regimes == DEFAULT_NEUTRAL_REGIMES == ("panic", "range_low_vol")


def test_config_is_frozen() -> None:
    config = BiasConfig()
    with pytest.raises(ValidationError):
        config.slope_deadband = 1.0


@pytest.mark.parametrize("field", ["slope_deadband", "vwap_deadband"])
def test_negative_deadband_rejected(field: str) -> None:
    with pytest.raises(ValidationError):
        BiasConfig.model_validate({field: -0.1})


def test_bias_signal_frozen() -> None:
    signal = BiasSignal(direction="long", reasons=["ema_fast>ema_slow (long)"])
    assert signal.direction == "long"
    with pytest.raises(ValidationError):
        signal.direction = "short"


def test_error_hierarchy() -> None:
    assert issubclass(BiasError, TfexS50Error)
    assert issubclass(BiasInputError, BiasError)


def test_settings_bias_config_accessor() -> None:
    settings = Settings(bias_slope_deadband=0.7, bias_vwap_deadband=0.2)
    config = settings.bias_config()
    assert config.slope_deadband == 0.7
    assert config.vwap_deadband == 0.2
    assert config.neutral_regimes == ("panic", "range_low_vol")
