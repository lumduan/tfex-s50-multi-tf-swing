"""Tests for the signal-layer models, config bounds, and error hierarchy."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from tfex_s50_multi_tf_swing.adapters.errors import TfexS50Error
from tfex_s50_multi_tf_swing.signals.errors import SignalError, SignalInputError
from tfex_s50_multi_tf_swing.signals.models import (
    SETUP_DIRECTIONS,
    STRATEGY_IDS,
    SetupFeatures,
    SetupSignal,
    SignalConfig,
)


def test_taxonomy_tuples() -> None:
    assert STRATEGY_IDS == ("A", "B", "C")
    assert SETUP_DIRECTIONS == ("long", "short")


def test_setup_signal_is_frozen_and_utc() -> None:
    sig = SetupSignal(
        strategy_id="A",
        time=datetime(2026, 1, 5, 3, 0, tzinfo=UTC),
        direction="long",
        trigger_price=Decimal("105.0"),
        stop_reference=Decimal("95.0"),
    )
    with pytest.raises(ValidationError):
        sig.direction = "short"


def test_setup_signal_rejects_naive_time() -> None:
    with pytest.raises(ValidationError, match="UTC-aware"):
        SetupSignal(
            strategy_id="A",
            time=datetime(2026, 1, 5, 3, 0),
            direction="long",
            trigger_price=Decimal("105.0"),
            stop_reference=Decimal("95.0"),
        )


def test_setup_features_rejects_naive_time() -> None:
    with pytest.raises(ValidationError, match="UTC-aware"):
        SetupFeatures(
            time=datetime(2026, 1, 5, 3, 0), bias_direction="long", regime=None, close=1.0
        )


def test_signal_config_bounds() -> None:
    with pytest.raises(ValidationError):
        SignalConfig(pullback_band=-0.1)
    with pytest.raises(ValidationError):
        SignalConfig(or_window=0)
    with pytest.raises(ValidationError):
        SignalConfig(swing_window=1)


def test_errors_inherit_base() -> None:
    assert issubclass(SignalError, TfexS50Error)
    assert issubclass(SignalInputError, SignalError)
