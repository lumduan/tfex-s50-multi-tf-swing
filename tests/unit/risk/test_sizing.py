"""Position-sizing + volatility-scaling tests (ROADMAP §7.1 + §7.3)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tfex_s50_multi_tf_swing.risk.errors import RiskInputError
from tfex_s50_multi_tf_swing.risk.models import PositionSizeRequest, RiskConfig
from tfex_s50_multi_tf_swing.risk.sizing import (
    S50_MULTIPLIER,
    compute_position_size,
    volatility_scale_factor,
)


def test_multiplier_constant() -> None:
    assert Decimal("200") == S50_MULTIPLIER


def test_default_risk_per_trade_pct_is_half_percent() -> None:
    """The default per-trade budget is 0.5% (tightened from 1% as a risk mitigation)."""
    assert RiskConfig().risk_per_trade_pct == 0.005


def test_default_sizing_half_percent_is_zero_for_worked_example() -> None:
    """Under the 0.5% default, 100k / 5-pt stop sizes to 0 contracts (was 1 at 1%)."""
    result = compute_position_size(
        PositionSizeRequest(equity=Decimal("100000"), stop_distance_points=Decimal("5")),
        RiskConfig(),
    )
    assert result.contracts == 0
    assert result.risk_amount == Decimal("500")
    assert "sub-1-contract → no trade" in result.reasons


def test_worked_example_one_contract() -> None:
    """Verbatim risk-engine.md example: 100k equity, 1% risk, 5-pt stop ⇒ exactly 1 contract."""
    result = compute_position_size(
        PositionSizeRequest(equity=Decimal("100000"), stop_distance_points=Decimal("5")),
        RiskConfig(risk_per_trade_pct=0.01),
    )
    assert result.contracts == 1
    assert result.risk_amount == Decimal("1000.00")
    assert result.scale_factor == Decimal("1.0")


def test_wider_stop_shrinks_size() -> None:
    """A wider stop yields fewer contracts (floored)."""
    cfg = RiskConfig(risk_per_trade_pct=0.01)
    eq = Decimal("100000")
    # 4-pt stop: 1000 / (4*200) = 1.25 → 1 contract.
    assert (
        compute_position_size(
            PositionSizeRequest(equity=eq, stop_distance_points=Decimal("4")), cfg
        ).contracts
        == 1
    )
    # 2.5-pt stop: 1000 / (2.5*200) = 2.0 → 2 contracts.
    assert (
        compute_position_size(
            PositionSizeRequest(equity=eq, stop_distance_points=Decimal("2.5")), cfg
        ).contracts
        == 2
    )


def test_sub_one_contract_is_zero_not_rounded_up() -> None:
    """A sub-1-contract result is 0 (no trade), never a rounded-up 1."""
    result = compute_position_size(
        PositionSizeRequest(equity=Decimal("100000"), stop_distance_points=Decimal("10")),
        RiskConfig(),
    )
    assert result.contracts == 0
    assert "sub-1-contract → no trade" in result.reasons


def test_zero_and_negative_equity_raise() -> None:
    for equity in (Decimal("0"), Decimal("-100000")):
        with pytest.raises(RiskInputError):
            compute_position_size(
                PositionSizeRequest(equity=equity, stop_distance_points=Decimal("5")),
                RiskConfig(),
            )


def test_zero_and_negative_stop_distance_raise() -> None:
    """Zero stop distance must raise a typed error, never divide-by-zero."""
    for stop in (Decimal("0"), Decimal("-5")):
        with pytest.raises(RiskInputError):
            compute_position_size(
                PositionSizeRequest(equity=Decimal("100000"), stop_distance_points=stop),
                RiskConfig(),
            )


def test_volatility_scale_high_percentile_halves() -> None:
    cfg = RiskConfig()
    assert volatility_scale_factor(0.80, "trend_up", cfg) == Decimal("0.5")
    # Just below the high-vol percentile keeps full size.
    assert volatility_scale_factor(0.69, "trend_up", cfg) == Decimal("1.0")


def test_volatility_scale_panic_is_no_trade() -> None:
    cfg = RiskConfig()
    assert volatility_scale_factor(0.50, "panic", cfg) == Decimal("0.0")
    # With panic_no_trade off, the regime policy's 0.5 applies instead.
    no_panic_gate = RiskConfig(panic_no_trade=False)
    assert volatility_scale_factor(0.50, "panic", no_panic_gate) == Decimal("0.5")


def test_volatility_scale_range_low_vol_is_no_trade() -> None:
    assert volatility_scale_factor(0.10, "range_low_vol", RiskConfig()) == Decimal("0.0")


def test_volatility_scale_no_regime_no_percentile_full() -> None:
    assert volatility_scale_factor(None, None, RiskConfig()) == Decimal("1.0")


def test_scaling_applied_in_sizing() -> None:
    """High-vol scaling halves the sized contract count."""
    result = compute_position_size(
        PositionSizeRequest(
            equity=Decimal("200000"),
            stop_distance_points=Decimal("5"),
            rv_percentile=0.85,
            regime="trend_up",
        ),
        RiskConfig(risk_per_trade_pct=0.01),
    )
    # 2000 / (5*200) = 2.0, halved to 1.0 → 1 contract.
    assert result.contracts == 1
    assert result.scale_factor == Decimal("0.5")
    assert any("scale_factor" in r for r in result.reasons)
