"""Settings tests for the risk-mitigation knobs (enabled strategies, regime allow-set, breaker)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tfex_s50_multi_tf_swing.config.settings import Settings


def test_enabled_strategies_default_is_orb_only() -> None:
    assert Settings().enabled_strategy_ids() == frozenset({"B"})


def test_enabled_strategies_parses_and_uppercases() -> None:
    assert Settings(enabled_strategies="a, b ,c").enabled_strategy_ids() == frozenset(
        {"A", "B", "C"}
    )


def test_enabled_strategies_rejects_unknown_id() -> None:
    with pytest.raises(ValidationError):
        Settings(enabled_strategies="A,X")


def test_allowed_regimes_default_is_trend_up() -> None:
    assert Settings().signal_config().allowed_regimes == frozenset({"trend_up"})


def test_allowed_regimes_parses_multiple() -> None:
    cfg = Settings(signal_allowed_regimes="trend_up, range_low_vol").signal_config()
    assert cfg.allowed_regimes == frozenset({"trend_up", "range_low_vol"})


def test_allowed_regimes_rejects_unknown_regime() -> None:
    with pytest.raises(ValidationError):
        Settings(signal_allowed_regimes="trend_up,bull_market")


def test_per_window_loss_limit_default_and_wiring() -> None:
    assert Settings().risk_config().per_window_loss_limit_r == -5.0


def test_per_window_loss_limit_must_be_negative() -> None:
    with pytest.raises(ValidationError):
        Settings(risk_per_window_loss_limit_r=0.0)
