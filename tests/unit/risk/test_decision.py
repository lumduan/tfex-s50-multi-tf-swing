"""Risk-decision orchestrator tests (ROADMAP §7)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from tfex_s50_multi_tf_swing.risk.decision import evaluate_entry
from tfex_s50_multi_tf_swing.risk.errors import RiskInputError
from tfex_s50_multi_tf_swing.risk.limits import start_session
from tfex_s50_multi_tf_swing.risk.models import (
    LadderEvidence,
    MarketHealth,
    PositionSizeRequest,
    RiskConfig,
    SessionRiskState,
)

DAY = date(2026, 6, 4)
MICRO = RiskConfig(deployment_stage="micro_live")


def test_happy_path_sizes_one_contract() -> None:
    decision = evaluate_entry(
        request=PositionSizeRequest(equity=Decimal("100000"), stop_distance_points=Decimal("5")),
        session_state=start_session(DAY),
        config=MICRO,
    )
    assert decision.allow_entry
    assert decision.contracts == 1
    assert not decision.kill_switch.engaged
    assert decision.size_result is not None


def test_kill_switch_overrides_a_valid_setup() -> None:
    decision = evaluate_entry(
        request=PositionSizeRequest(equity=Decimal("100000"), stop_distance_points=Decimal("5")),
        session_state=start_session(DAY),
        config=RiskConfig(deployment_stage="micro_live", kill_switch_engaged=True),
    )
    assert not decision.allow_entry
    assert decision.contracts == 0
    assert decision.kill_switch.engaged
    assert decision.kill_switch.flatten_positions
    assert any("kill switch" in r for r in decision.reasons)


def test_panic_regime_no_trade() -> None:
    decision = evaluate_entry(
        request=PositionSizeRequest(
            equity=Decimal("100000"), stop_distance_points=Decimal("5"), regime="panic"
        ),
        session_state=start_session(DAY),
        config=MICRO,
    )
    assert not decision.allow_entry
    assert decision.contracts == 0


def test_halted_session_blocks_entry() -> None:
    halted = SessionRiskState(session_date=DAY, halted=True, halt_reason="daily loss limit")
    decision = evaluate_entry(
        request=PositionSizeRequest(equity=Decimal("100000"), stop_distance_points=Decimal("5")),
        session_state=halted,
        config=MICRO,
    )
    assert not decision.allow_entry
    assert decision.contracts == 0
    assert not decision.kill_switch.engaged
    assert "daily loss limit" in decision.reasons


def test_ladder_caps_size() -> None:
    # 200k / (2.5*200) = 4 contracts, capped to 1 at micro-live.
    decision = evaluate_entry(
        request=PositionSizeRequest(equity=Decimal("200000"), stop_distance_points=Decimal("2.5")),
        session_state=start_session(DAY),
        config=MICRO,
    )
    assert decision.allow_entry
    assert decision.contracts == 1
    assert any("ladder cap" in r for r in decision.reasons)


def test_paper_stage_blocks_all_entries() -> None:
    decision = evaluate_entry(
        request=PositionSizeRequest(equity=Decimal("100000"), stop_distance_points=Decimal("5")),
        session_state=start_session(DAY),
        config=RiskConfig(),  # default stage = paper → cap 0
    )
    assert not decision.allow_entry
    assert decision.contracts == 0


def test_validated_stage_with_evidence() -> None:
    decision = evaluate_entry(
        request=PositionSizeRequest(equity=Decimal("200000"), stop_distance_points=Decimal("2.5")),
        session_state=start_session(DAY),
        config=RiskConfig(deployment_stage="validated"),
        market_health=MarketHealth(),
        evidence=LadderEvidence(
            months_live=6.0, expectancy_stable=True, drawdown_within_budget=True
        ),
    )
    assert decision.allow_entry
    assert decision.contracts == 2


def test_bad_input_propagates() -> None:
    with pytest.raises(RiskInputError):
        evaluate_entry(
            request=PositionSizeRequest(
                equity=Decimal("100000"), stop_distance_points=Decimal("0")
            ),
            session_state=start_session(DAY),
            config=MICRO,
        )
