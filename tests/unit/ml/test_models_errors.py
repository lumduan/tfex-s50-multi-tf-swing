"""Tests for the ML contracts: config bounds, target mapping, card validation, bundle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from tfex_s50_multi_tf_swing.ml.models import (
    MODEL_TARGETS,
    MLFilterConfig,
    ModelBundle,
    ModelCard,
    TripleBarrierConfig,
    target_for_strategy,
)

from .conftest import ConstantModel, make_card

_T0 = datetime(2026, 1, 5, 3, 0, tzinfo=UTC)


def test_filter_config_defaults_off() -> None:
    config = MLFilterConfig()
    assert config.enabled is False
    assert config.threshold_continuation == 0.55
    assert config.threshold_fake_breakout == 0.50


def test_threshold_for_selects_per_target() -> None:
    config = MLFilterConfig(threshold_continuation=0.6, threshold_fake_breakout=0.4)
    assert config.threshold_for("trend_continuation") == 0.6
    assert config.threshold_for("fake_breakout") == 0.4


@pytest.mark.parametrize("field", ["threshold_continuation", "threshold_fake_breakout"])
@pytest.mark.parametrize("value", [-0.1, 1.1])
def test_threshold_bounds_rejected(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        MLFilterConfig.model_validate({field: value})


def test_filter_config_is_frozen() -> None:
    config = MLFilterConfig()
    with pytest.raises(ValidationError):
        config.enabled = True


@pytest.mark.parametrize(
    ("strategy_id", "target"),
    [("A", "trend_continuation"), ("B", "trend_continuation"), ("C", "fake_breakout")],
)
def test_target_for_strategy(strategy_id: str, target: str) -> None:
    assert target_for_strategy(strategy_id) == target  # type: ignore[arg-type]


def test_triple_barrier_bounds() -> None:
    with pytest.raises(ValidationError):
        TripleBarrierConfig(tp_atr_mult=0.0)
    with pytest.raises(ValidationError):
        TripleBarrierConfig(horizon_bars=0)


def test_model_card_requires_utc() -> None:
    naive = datetime(2026, 1, 5, 3, 0)  # noqa: DTZ001 — deliberately tz-naive
    with pytest.raises(ValidationError):
        ModelCard(
            target="fake_breakout",
            feature_columns=("a",),
            threshold=0.5,
            train_window=(_T0, _T0 + timedelta(minutes=1)),
            seed=1,
            created_at=naive,
        )
    with pytest.raises(ValidationError):
        ModelCard(
            target="fake_breakout",
            feature_columns=("a",),
            threshold=0.5,
            train_window=(naive, naive),
            seed=1,
        )


def test_model_card_threshold_bounds() -> None:
    with pytest.raises(ValidationError):
        ModelCard(
            target="fake_breakout",
            feature_columns=("a",),
            threshold=1.5,
            train_window=(_T0, _T0 + timedelta(minutes=1)),
            seed=1,
        )


def test_bundle_get_and_is_empty() -> None:
    empty = ModelBundle(models={}, cards={})
    assert empty.is_empty() is True
    assert empty.get("fake_breakout") is None

    populated = ModelBundle(
        models={"fake_breakout": ConstantModel(0.9)},
        cards={"fake_breakout": make_card("fake_breakout")},
    )
    assert populated.is_empty() is False
    resolved = populated.get("fake_breakout")
    assert resolved is not None
    assert populated.get("trend_continuation") is None


def test_bundle_get_none_when_card_missing() -> None:
    # A model without its card is unusable → get() returns None, is_empty() True.
    half = ModelBundle(models={"fake_breakout": ConstantModel(0.5)}, cards={})
    assert half.get("fake_breakout") is None
    assert half.is_empty() is True


def test_model_targets_tuple() -> None:
    assert set(MODEL_TARGETS) == {"trend_continuation", "fake_breakout"}
