"""Cost-model tests (ROADMAP §8.1) — commission + slippage + spread fold into net R."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tfex_s50_multi_tf_swing.backtest.costs import (
    CostModel,
    apply_costs,
    crosses_quarterly_expiry,
    is_illiquid_session,
)
from tfex_s50_multi_tf_swing.data.session import SessionCalendar
from tfex_s50_multi_tf_swing.risk.sizing import S50_MULTIPLIER

from .conftest import make_trade


def test_apply_costs_reduces_net_below_gross() -> None:
    trade = make_trade(r=Decimal("1"))  # gross +1R, risk 2 pts
    out = apply_costs(trade, atr_at_entry=2.0, illiquid=False, config=CostModel())
    assert out.cost_points > 0
    assert out.net_pnl_points < trade.pnl_points
    assert out.net_r_multiple < trade.r_multiple
    # commission folds via the multiplier; never re-typed inline.
    expected_commission = (Decimal("160") + Decimal("1")) / S50_MULTIPLIER
    assert out.commission_points == expected_commission


def test_illiquid_session_uplifts_slippage() -> None:
    trade = make_trade()
    liquid = apply_costs(trade, atr_at_entry=2.0, illiquid=False, config=CostModel())
    illiquid = apply_costs(trade, atr_at_entry=2.0, illiquid=True, config=CostModel())
    assert illiquid.slippage_points > liquid.slippage_points
    assert illiquid.cost_points > liquid.cost_points


def test_spread_is_tick_based() -> None:
    cfg = CostModel(spread_ticks=2.0, tick_size=Decimal("0.1"))
    out = apply_costs(make_trade(), atr_at_entry=0.0, illiquid=False, config=cfg)
    assert out.spread_points == Decimal("0.2")
    assert out.slippage_points == Decimal("0")  # atr 0 ⇒ no slippage


def test_net_trade_recomputes_pnl_and_r() -> None:
    trade = make_trade(r=Decimal("2"), entry=Decimal("100"), stop=Decimal("98"))
    out = apply_costs(trade, atr_at_entry=2.0, illiquid=False, config=CostModel())
    net = out.net_trade
    assert net.pnl_points == out.net_pnl_points
    assert net.r_multiple == out.net_r_multiple
    assert net.strategy_id == trade.strategy_id  # other fields preserved


def test_zero_risk_trade_yields_zero_net_r() -> None:
    flat = make_trade(r=Decimal("0"), entry=Decimal("100"), stop=Decimal("100"))
    out = apply_costs(flat, atr_at_entry=2.0, illiquid=False, config=CostModel())
    assert out.net_r_multiple == Decimal("0")


def test_cost_model_is_frozen() -> None:
    cfg = CostModel()
    try:
        cfg.spread_ticks = 9.0
    except (AttributeError, TypeError, ValueError):
        return
    raise AssertionError("CostModel should be frozen")


def test_is_illiquid_session_flags_night_and_lunch() -> None:
    cal = SessionCalendar()
    night = datetime(2026, 1, 5, 13, 0, tzinfo=UTC)  # 20:00 BKK — night
    lunch = datetime(2026, 1, 5, 5, 30, tzinfo=UTC)  # 12:30 BKK — lunch dead zone
    morning = datetime(2026, 1, 5, 3, 0, tzinfo=UTC)  # 10:00 BKK — liquid
    assert is_illiquid_session(cal, night) is True
    assert is_illiquid_session(cal, lunch) is True
    assert is_illiquid_session(cal, morning) is False


# --- Roll-over costs (a 1H position held across a quarterly contract expiry) ---


def test_crosses_quarterly_expiry_true_across_boundary() -> None:
    cal = SessionCalendar()
    # June (M) 2026 expiry is the last business day of June; entering mid-June and exiting in
    # July spans it.
    entry = datetime(2026, 6, 15, 3, 0, tzinfo=UTC)
    exit_ = datetime(2026, 7, 2, 3, 0, tzinfo=UTC)
    assert crosses_quarterly_expiry(entry, exit_, cal) is True


def test_crosses_quarterly_expiry_false_within_quarter() -> None:
    cal = SessionCalendar()
    # A short hold entirely inside a single quarter (mid-Jan → mid-Feb) crosses no expiry.
    entry = datetime(2026, 1, 15, 3, 0, tzinfo=UTC)
    exit_ = datetime(2026, 2, 15, 3, 0, tzinfo=UTC)
    assert crosses_quarterly_expiry(entry, exit_, cal) is False


def test_crosses_quarterly_expiry_false_same_day() -> None:
    cal = SessionCalendar()
    intraday_entry = datetime(2026, 1, 5, 3, 0, tzinfo=UTC)
    intraday_exit = datetime(2026, 1, 5, 7, 0, tzinfo=UTC)
    assert crosses_quarterly_expiry(intraday_entry, intraday_exit, cal) is False


def test_rollover_cost_added_when_crossing() -> None:
    trade = make_trade(r=Decimal("1"))
    base = apply_costs(trade, atr_at_entry=2.0, illiquid=False, config=CostModel())
    rolled = apply_costs(
        trade, atr_at_entry=2.0, illiquid=False, config=CostModel(), crosses_rollover=True
    )
    expected_rollover = Decimal("160") / S50_MULTIPLIER + Decimal("2.0")
    assert rolled.rollover_cost_points == expected_rollover
    assert rolled.cost_points == base.cost_points + expected_rollover
    assert rolled.net_pnl_points == base.net_pnl_points - expected_rollover
    assert rolled.net_r_multiple < base.net_r_multiple


def test_no_rollover_cost_by_default() -> None:
    trade = make_trade()
    out = apply_costs(trade, atr_at_entry=2.0, illiquid=False, config=CostModel())
    assert out.rollover_cost_points == Decimal("0")
