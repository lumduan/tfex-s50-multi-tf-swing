"""Configurable trade-cost model (ROADMAP §8.1).

A backtest without costs is a marketing exercise (see ``.claude/knowledge/backtest-protocol.md``).
:func:`apply_costs` turns a gross :class:`~tfex_s50_multi_tf_swing.execution.models.Trade` into a
:class:`CostedTrade` by deducting **commission + clearing fee**, **slippage** (ATR-scaled, worse
on illiquid sessions), and **spread** (tick-based).

Every cost is folded into **points per contract** so the net R-multiple stays contract-agnostic
and directly comparable to the gross R:

    cost_points = slippage_points + spread_points + (commission + clearing) / S50_MULTIPLIER
    slippage_points = slippage_atr_mult · atr · (illiquid_session_mult if illiquid else 1.0)
    spread_points   = spread_ticks · tick_size

The fee→points conversion is the single use of
:data:`~tfex_s50_multi_tf_swing.risk.sizing.S50_MULTIPLIER`
here, imported (never re-typed inline). Money quantities (fees, tick size) are
:class:`~decimal.Decimal`; the slippage / spread multipliers are :class:`float` (statistical
inputs that never cross the gateway boundary).
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from tfex_s50_multi_tf_swing.data.contracts import MONTH_CODES, expiry_for
from tfex_s50_multi_tf_swing.data.session import SessionCalendar
from tfex_s50_multi_tf_swing.execution.models import Trade
from tfex_s50_multi_tf_swing.risk.sizing import S50_MULTIPLIER

logger = logging.getLogger(__name__)

_ZERO = Decimal(0)
_BKK = ZoneInfo("Asia/Bangkok")


class CostModel(BaseModel):
    """Frozen, bounded cost knobs for one S50 round-trip per contract.

    ``commission_per_contract`` / ``clearing_fee_per_contract`` are THB **round-trip** fees (entry
    + exit) per contract. Default commission is **160 THB round-trip** (80 THB/side incl. VAT/fees,
    1H-execution migration retail rate). ``slippage_atr_mult`` scales slippage to volatility; on an
    illiquid session (night / lunch dead-zone edge) it is multiplied by ``illiquid_session_mult``.
    ``spread_ticks`` × ``tick_size`` is the half-spread paid in index points.
    """

    model_config = ConfigDict(frozen=True)

    commission_per_contract: Decimal = Field(default=Decimal("160"), ge=0)
    clearing_fee_per_contract: Decimal = Field(default=Decimal("1"), ge=0)
    slippage_atr_mult: float = Field(default=0.05, ge=0.0)
    illiquid_session_mult: float = Field(default=2.0, ge=1.0)
    tick_size: Decimal = Field(default=Decimal("0.1"), gt=0)
    spread_ticks: float = Field(default=1.0, ge=0.0)
    # Roll-over penalty applied once when a trade is held across a quarterly contract expiry
    # (end of Mar/Jun/Sep/Dec). ``rollover_commission_per_contract`` is the THB close+open
    # commission of rolling the position; ``rollover_spread_points`` is the index-point gap
    # penalty for the price discontinuity at the roll.
    rollover_commission_per_contract: Decimal = Field(default=Decimal("160"), ge=0)
    rollover_spread_points: Decimal = Field(default=Decimal("2.0"), ge=0)


class CostedTrade(BaseModel):
    """A gross trade plus its deducted costs and the resulting net PnL (points + R)."""

    model_config = ConfigDict(frozen=True)

    gross: Trade
    cost_points: Decimal = Field(ge=0)
    commission_points: Decimal = Field(ge=0)
    slippage_points: Decimal = Field(ge=0)
    spread_points: Decimal = Field(ge=0)
    rollover_cost_points: Decimal = Field(default=_ZERO, ge=0)
    net_pnl_points: Decimal
    net_r_multiple: Decimal

    @property
    def net_trade(self) -> Trade:
        """The gross :class:`Trade` with ``pnl_points`` / ``r_multiple`` replaced by net values.

        Lets every existing R-multiple metric run unchanged over the post-cost outcome.
        """
        return self.gross.model_copy(
            update={"pnl_points": self.net_pnl_points, "r_multiple": self.net_r_multiple}
        )


def is_illiquid_session(calendar: SessionCalendar, dt: datetime) -> bool:
    """``True`` on the night session or inside the 12:00–14:00 BKK lunch dead-zone edge."""
    return calendar.session_of(dt) == "night" or calendar.is_lunch_dead_zone(dt)


def crosses_quarterly_expiry(
    entry_time: datetime, exit_time: datetime, calendar: SessionCalendar | None = None
) -> bool:
    """``True`` if ``[entry_time, exit_time]`` spans a quarterly S50 contract expiry.

    Quarterly contracts expire on the **last business day** of Mar (H) / Jun (M) / Sep (U) /
    Dec (Z). A 1H position held over that boundary must be rolled to the next contract. The
    bounds are compared as Asia/Bangkok calendar dates; the crossing is half-open
    ``entry_date < expiry <= exit_date`` so a same-day entry-and-exit on the expiry never
    double-counts. Reuses :func:`~tfex_s50_multi_tf_swing.data.contracts.expiry_for`.
    """
    entry_date = entry_time.astimezone(_BKK).date()
    exit_date = exit_time.astimezone(_BKK).date()
    if exit_date <= entry_date:
        return False
    for year in range(entry_date.year, exit_date.year + 1):
        for code in MONTH_CODES:
            expiry = expiry_for(f"S50{code}{year}", calendar)
            if entry_date < expiry <= exit_date:
                return True
    return False


def apply_costs(
    trade: Trade,
    *,
    atr_at_entry: float,
    illiquid: bool,
    config: CostModel,
    crosses_rollover: bool = False,
) -> CostedTrade:
    """Deduct commission + slippage + spread from ``trade``; return the costed result.

    ``atr_at_entry`` is the (float) ATR at the fill bar used to scale slippage; ``illiquid`` flags
    a night / lunch-edge entry (see :func:`is_illiquid_session`). The trade's own risk distance
    ``|entry − stop|`` (already :class:`~decimal.Decimal`) normalises the net R-multiple.

    When ``crosses_rollover`` is ``True`` (the trade spans a quarterly expiry — see
    :func:`crosses_quarterly_expiry`) an extra roll-over penalty is added:
    ``rollover_commission_per_contract / S50_MULTIPLIER + rollover_spread_points`` points,
    recorded separately on :attr:`CostedTrade.rollover_cost_points` for audit.
    """
    session_mult = config.illiquid_session_mult if illiquid else 1.0
    slippage_points = Decimal(str(max(0.0, config.slippage_atr_mult * atr_at_entry * session_mult)))
    spread_points = Decimal(str(config.spread_ticks)) * config.tick_size
    commission_points = (config.commission_per_contract + config.clearing_fee_per_contract) / (
        S50_MULTIPLIER
    )
    rollover_cost_points = _ZERO
    if crosses_rollover:
        rollover_cost_points = (
            config.rollover_commission_per_contract / S50_MULTIPLIER + config.rollover_spread_points
        )
    cost_points = slippage_points + spread_points + commission_points + rollover_cost_points

    risk_points = abs(trade.entry - trade.stop)
    net_pnl_points = trade.pnl_points - cost_points
    net_r = net_pnl_points / risk_points if risk_points > _ZERO else _ZERO

    logger.debug(
        "costed %s trade: gross=%sR net=%sR cost=%spts (illiquid=%s rollover=%s)",
        trade.strategy_id,
        trade.r_multiple,
        net_r,
        cost_points,
        illiquid,
        crosses_rollover,
    )
    return CostedTrade(
        gross=trade,
        cost_points=cost_points,
        commission_points=commission_points,
        slippage_points=slippage_points,
        spread_points=spread_points,
        rollover_cost_points=rollover_cost_points,
        net_pnl_points=net_pnl_points,
        net_r_multiple=net_r,
    )


__all__: list[str] = [
    "CostModel",
    "CostedTrade",
    "apply_costs",
    "crosses_quarterly_expiry",
    "is_illiquid_session",
]
