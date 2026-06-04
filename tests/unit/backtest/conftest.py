"""Synthetic, public-safe builders for the Phase-8 walk-forward + cost tests.

No real OHLCV: every fixture is a deterministic synthetic frame / trade. A rising ``ramp_bars``
series lets longs resolve; :func:`make_trade` / :func:`costed` build typed trades with a chosen
net R so the risk-driving and metric paths are exercised on known inputs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import polars as pl

from tfex_s50_multi_tf_swing.backtest.costs import CostedTrade
from tfex_s50_multi_tf_swing.execution.models import ExitReason, Trade
from tfex_s50_multi_tf_swing.regime.models import Regime
from tfex_s50_multi_tf_swing.signals.models import SetupDirection, StrategyId

# Monday 2026-01-05 03:00Z == 10:00 BKK (morning session, liquid).
T0 = datetime(2026, 1, 5, 3, 0, tzinfo=UTC)

BAR_SCHEMA: dict[str, pl.DataType] = {
    "time": pl.Datetime(time_unit="us", time_zone="UTC"),
    "open": pl.Float64(),
    "high": pl.Float64(),
    "low": pl.Float64(),
    "close": pl.Float64(),
    "atr": pl.Float64(),
}


def ramp_bars(
    n: int, *, start: datetime = T0, step_min: int = 60, base: float = 100.0, slope: float = 0.5
) -> pl.DataFrame:
    """A gently rising OHLCV ramp with constant ATR (longs trend into profit)."""
    rows = [
        {
            "time": start + timedelta(minutes=step_min * i),
            "open": base + slope * i,
            "high": base + slope * i + 1.0,
            "low": base + slope * i - 1.0,
            "close": base + slope * i,
            "atr": 2.0,
        }
        for i in range(n)
    ]
    return pl.DataFrame(rows, schema=BAR_SCHEMA)


def make_trade(
    *,
    r: Decimal = Decimal("1"),
    regime: Regime | None = "trend_up",
    entry: Decimal = Decimal("100"),
    stop: Decimal = Decimal("98"),
    sid: StrategyId = "A",
    direction: SetupDirection = "long",
    when: datetime | None = None,
    exit_reason: ExitReason = "take_profit",
) -> Trade:
    """A typed :class:`Trade` with a chosen R-multiple (risk = |entry − stop|)."""
    when = when or T0
    risk = abs(entry - stop)
    pnl_points = r * risk
    exit_price = entry + pnl_points if direction == "long" else entry - pnl_points
    return Trade(
        strategy_id=sid,
        direction=direction,
        entry_time=when,
        exit_time=when + timedelta(minutes=5),
        entry=entry,
        stop=stop,
        exit_price=exit_price,
        pnl_points=pnl_points,
        r_multiple=r,
        bars_held=1,
        exit_reason=exit_reason,
        regime=regime,
    )


def costed(trade: Trade, *, net_r: Decimal | None = None) -> CostedTrade:
    """Wrap a trade as a :class:`CostedTrade` with a chosen net R (zero modelled cost)."""
    net = trade.r_multiple if net_r is None else net_r
    risk = abs(trade.entry - trade.stop)
    return CostedTrade(
        gross=trade,
        cost_points=Decimal("0"),
        commission_points=Decimal("0"),
        slippage_points=Decimal("0"),
        spread_points=Decimal("0"),
        net_pnl_points=net * risk,
        net_r_multiple=net,
    )
