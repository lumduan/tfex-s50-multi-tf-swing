"""Kill-switch evaluation tests (ROADMAP §7.4) — incl. the fault-injection exit criterion."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from tfex_s50_multi_tf_swing.risk.killswitch import evaluate_kill_switch
from tfex_s50_multi_tf_swing.risk.models import (
    KillSwitchTrigger,
    MarketHealth,
    RiskConfig,
    SessionRiskState,
)

CFG = RiskConfig()
DAY = date(2026, 6, 4)


def test_clean_health_does_not_engage() -> None:
    state = evaluate_kill_switch(MarketHealth(), SessionRiskState(session_date=DAY), CFG)
    assert not state.engaged
    assert not state.flatten_positions
    assert not state.halt_entries
    assert state.triggers == ()


@pytest.mark.parametrize(
    ("health", "config", "session", "expected"),
    [
        (MarketHealth(), RiskConfig(kill_switch_engaged=True), None, "manual"),
        (MarketHealth(spread=10.0, median_spread=1.0), CFG, None, "spread_anomaly"),
        (MarketHealth(latency_ms=600.0), CFG, None, "latency_breach"),
        (MarketHealth(broker_connected=False), CFG, None, "broker_disconnect"),
        (MarketHealth(error_rate=0.5), CFG, None, "broker_disconnect"),
        (MarketHealth(market_halted=True), CFG, None, "market_halt"),
        (
            MarketHealth(),
            CFG,
            SessionRiskState(session_date=DAY, cumulative_r=Decimal("-2.0")),
            "daily_loss_limit",
        ),
    ],
)
def test_each_trigger_flattens_and_halts(
    health: MarketHealth,
    config: RiskConfig,
    session: SessionRiskState | None,
    expected: KillSwitchTrigger,
) -> None:
    """Fault injection: each trigger engages the switch and flattens + halts (exit criterion)."""
    state = evaluate_kill_switch(health, session, config)
    assert state.engaged
    assert state.flatten_positions is True
    assert state.halt_entries is True
    assert expected in state.triggers


def test_spread_anomaly_skipped_without_median() -> None:
    """A zero rolling median cannot trip the spread guard (no division-by-noise)."""
    state = evaluate_kill_switch(MarketHealth(spread=10.0, median_spread=0.0), None, CFG)
    assert "spread_anomaly" not in state.triggers


def test_multiple_triggers_combine_in_order() -> None:
    state = evaluate_kill_switch(
        MarketHealth(market_halted=True),
        SessionRiskState(session_date=DAY, cumulative_r=Decimal("-3.0")),
        RiskConfig(kill_switch_engaged=True),
    )
    assert state.engaged
    assert state.triggers == ("manual", "market_halt", "daily_loss_limit")


def test_no_session_state_skips_daily_loss() -> None:
    state = evaluate_kill_switch(MarketHealth(), None, CFG)
    assert "daily_loss_limit" not in state.triggers
    assert not state.engaged
