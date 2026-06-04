"""Tests for risk Pydantic models, settings wiring, and the error hierarchy."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from tfex_s50_multi_tf_swing.adapters.errors import TfexS50Error
from tfex_s50_multi_tf_swing.config.settings import Settings
from tfex_s50_multi_tf_swing.risk.errors import (
    RiskConfigError,
    RiskError,
    RiskInputError,
    RiskLimitError,
)
from tfex_s50_multi_tf_swing.risk.models import (
    KillSwitchState,
    MarketHealth,
    PositionSizeRequest,
    PositionSizeResult,
    RiskConfig,
    RiskDecision,
)


def test_error_hierarchy_roots_at_tfex_base() -> None:
    assert issubclass(RiskError, TfexS50Error)
    for sub in (RiskInputError, RiskLimitError, RiskConfigError):
        assert issubclass(sub, RiskError)


def test_risk_config_bounds() -> None:
    RiskConfig(risk_per_trade_pct=0.02)  # in range
    with pytest.raises(ValidationError):
        RiskConfig(risk_per_trade_pct=0.0)
    with pytest.raises(ValidationError):
        RiskConfig(risk_per_trade_pct=1.5)
    with pytest.raises(ValidationError):
        RiskConfig(daily_loss_limit_r=0.0)
    with pytest.raises(ValidationError):
        RiskConfig(max_consecutive_losses=0)
    with pytest.raises(ValidationError):
        RiskConfig(high_vol_percentile=1.5)


def test_risk_config_is_frozen() -> None:
    cfg = RiskConfig()
    with pytest.raises(ValidationError):
        cfg.risk_per_trade_pct = 0.5


def test_settings_risk_config_matches_defaults() -> None:
    """Guard against Settings defaults drifting from RiskConfig defaults."""
    assert Settings().risk_config() == RiskConfig()


def test_settings_invalid_deployment_stage_fails_at_build() -> None:
    settings = Settings(risk_deployment_stage="bogus")
    with pytest.raises(ValidationError):
        settings.risk_config()


def test_position_size_result_contracts_non_negative() -> None:
    PositionSizeResult(
        contracts=0,
        risk_amount=Decimal("0"),
        scale_factor=Decimal("1"),
        raw_contracts=Decimal("0"),
    )
    with pytest.raises(ValidationError):
        PositionSizeResult(
            contracts=-1,
            risk_amount=Decimal("0"),
            scale_factor=Decimal("1"),
            raw_contracts=Decimal("0"),
        )


def test_position_size_request_percentile_bounds() -> None:
    PositionSizeRequest(equity=Decimal("1"), stop_distance_points=Decimal("1"), rv_percentile=0.5)
    with pytest.raises(ValidationError):
        PositionSizeRequest(
            equity=Decimal("1"), stop_distance_points=Decimal("1"), rv_percentile=1.5
        )


def test_market_health_bounds() -> None:
    MarketHealth(error_rate=0.5)
    with pytest.raises(ValidationError):
        MarketHealth(error_rate=1.5)
    with pytest.raises(ValidationError):
        MarketHealth(spread=-1.0)


def test_risk_decision_carries_kill_switch() -> None:
    ks = KillSwitchState(engaged=False)
    decision = RiskDecision(allow_entry=True, contracts=1, kill_switch=ks)
    assert decision.kill_switch is ks
    assert decision.size_result is None
