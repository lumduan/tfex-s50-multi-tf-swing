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

from pydantic import BaseModel, ConfigDict, Field

from tfex_s50_multi_tf_swing.data.session import SessionCalendar
from tfex_s50_multi_tf_swing.execution.models import Trade
from tfex_s50_multi_tf_swing.risk.sizing import S50_MULTIPLIER

logger = logging.getLogger(__name__)

_ZERO = Decimal(0)


class CostModel(BaseModel):
    """Frozen, bounded cost knobs for one S50 round-trip per contract.

    ``commission_per_contract`` / ``clearing_fee_per_contract`` are THB **round-trip** fees (entry
    + exit) per contract. ``slippage_atr_mult`` scales slippage to volatility; on an illiquid
    session (night / lunch dead-zone edge) it is multiplied by ``illiquid_session_mult``.
    ``spread_ticks`` × ``tick_size`` is the half-spread paid in index points.
    """

    model_config = ConfigDict(frozen=True)

    commission_per_contract: Decimal = Field(default=Decimal("85"), ge=0)
    clearing_fee_per_contract: Decimal = Field(default=Decimal("1"), ge=0)
    slippage_atr_mult: float = Field(default=0.05, ge=0.0)
    illiquid_session_mult: float = Field(default=2.0, ge=1.0)
    tick_size: Decimal = Field(default=Decimal("0.1"), gt=0)
    spread_ticks: float = Field(default=1.0, ge=0.0)


class CostedTrade(BaseModel):
    """A gross trade plus its deducted costs and the resulting net PnL (points + R)."""

    model_config = ConfigDict(frozen=True)

    gross: Trade
    cost_points: Decimal = Field(ge=0)
    commission_points: Decimal = Field(ge=0)
    slippage_points: Decimal = Field(ge=0)
    spread_points: Decimal = Field(ge=0)
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


def apply_costs(
    trade: Trade,
    *,
    atr_at_entry: float,
    illiquid: bool,
    config: CostModel,
) -> CostedTrade:
    """Deduct commission + slippage + spread from ``trade``; return the costed result.

    ``atr_at_entry`` is the (float) ATR at the fill bar used to scale slippage; ``illiquid`` flags
    a night / lunch-edge entry (see :func:`is_illiquid_session`). The trade's own risk distance
    ``|entry − stop|`` (already :class:`~decimal.Decimal`) normalises the net R-multiple.
    """
    session_mult = config.illiquid_session_mult if illiquid else 1.0
    slippage_points = Decimal(str(max(0.0, config.slippage_atr_mult * atr_at_entry * session_mult)))
    spread_points = Decimal(str(config.spread_ticks)) * config.tick_size
    commission_points = (config.commission_per_contract + config.clearing_fee_per_contract) / (
        S50_MULTIPLIER
    )
    cost_points = slippage_points + spread_points + commission_points

    risk_points = abs(trade.entry - trade.stop)
    net_pnl_points = trade.pnl_points - cost_points
    net_r = net_pnl_points / risk_points if risk_points > _ZERO else _ZERO

    logger.debug(
        "costed %s trade: gross=%sR net=%sR cost=%spts (illiquid=%s)",
        trade.strategy_id,
        trade.r_multiple,
        net_r,
        cost_points,
        illiquid,
    )
    return CostedTrade(
        gross=trade,
        cost_points=cost_points,
        commission_points=commission_points,
        slippage_points=slippage_points,
        spread_points=spread_points,
        net_pnl_points=net_pnl_points,
        net_r_multiple=net_r,
    )


__all__: list[str] = ["CostModel", "CostedTrade", "apply_costs", "is_illiquid_session"]
