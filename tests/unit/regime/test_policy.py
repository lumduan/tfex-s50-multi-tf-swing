"""Tests for the regime -> strategy / size policy (ROADMAP §3.4)."""

from __future__ import annotations

from typing import cast

import pytest

from tfex_s50_multi_tf_swing.regime.errors import UnknownRegimeError
from tfex_s50_multi_tf_swing.regime.models import REGIMES, Regime, RegimePolicy
from tfex_s50_multi_tf_swing.regime.policy import (
    is_no_trade,
    regime_policy,
    regime_to_size_multiplier,
    regime_to_strategies,
)

_EXPECTED_SIZE: dict[Regime, float] = {
    "trend_up": 1.0,
    "trend_down": 1.0,
    "range_high_vol": 1.0,
    "range_low_vol": 0.0,
    "panic": 0.5,
}

_EXPECTED_STRATEGIES: dict[Regime, frozenset[str]] = {
    "trend_up": frozenset({"A", "B"}),
    "trend_down": frozenset({"A", "B"}),
    "range_high_vol": frozenset({"C"}),
    "range_low_vol": frozenset(),
    "panic": frozenset(),
}


@pytest.mark.parametrize("regime", REGIMES)
def test_every_regime_has_a_policy(regime: Regime) -> None:
    policy = regime_policy(regime)
    assert isinstance(policy, RegimePolicy)
    assert policy.regime == regime
    assert policy.allowed_strategies == _EXPECTED_STRATEGIES[regime]
    assert policy.size_multiplier == _EXPECTED_SIZE[regime]


@pytest.mark.parametrize("regime", REGIMES)
def test_strategies_and_size_accessors(regime: Regime) -> None:
    assert regime_to_strategies(regime) == _EXPECTED_STRATEGIES[regime]
    assert regime_to_size_multiplier(regime) == _EXPECTED_SIZE[regime]


def test_directions() -> None:
    assert regime_policy("trend_up").direction == "long"
    assert regime_policy("trend_down").direction == "short"
    assert regime_policy("range_high_vol").direction == "both"
    assert regime_policy("range_low_vol").direction == "none"
    assert regime_policy("panic").direction == "none"


@pytest.mark.parametrize(
    ("regime", "expected"),
    [
        ("trend_up", False),
        ("trend_down", False),
        ("range_high_vol", False),
        ("range_low_vol", True),
        ("panic", True),
    ],
)
def test_is_no_trade(regime: Regime, expected: bool) -> None:
    assert is_no_trade(regime) is expected


def test_lunch_zone_forces_no_trade() -> None:
    assert is_no_trade("trend_up", lunch_zone=True) is True


def test_unknown_regime_raises() -> None:
    bogus = cast(Regime, "sideways")
    with pytest.raises(UnknownRegimeError, match="no policy for regime"):
        regime_policy(bogus)
    with pytest.raises(UnknownRegimeError):
        regime_to_strategies(bogus)
    with pytest.raises(UnknownRegimeError):
        regime_to_size_multiplier(bogus)
