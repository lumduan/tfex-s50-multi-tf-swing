"""Type contracts for the 5m execution engine (ROADMAP §5.4).

* :data:`ExitReason` — how a simulated trade closed.
* :class:`ExecutionConfig` — the entry / stop / take-profit / breakeven / time-stop knobs, frozen
  and bounded so an out-of-range env override fails at load (mirrors the other config models).
* :class:`Trade` — one fully-simulated trade. Prices and PnL are **Decimal** (money). PnL is
  expressed in **points** and **R-multiples** only — the THB conversion (the 200-THB/point S50
  multiplier) belongs to the Phase-7 risk engine and the cost model to Phase-8, both out of scope
  here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tfex_s50_multi_tf_swing.regime.models import Regime
from tfex_s50_multi_tf_swing.signals.models import SetupDirection, StrategyId

ExitReason = Literal[
    "take_profit",
    "stop_loss",
    "trailing_stop",
    "time_stop",
    "end_of_data",
]
"""How a simulated trade closed its (remaining) position."""

EXIT_REASONS: tuple[ExitReason, ...] = get_args(ExitReason)
"""Tuple of every :data:`ExitReason`, for iteration / parametrised tests."""


class ExecutionConfig(BaseModel):
    """Entry / exit / management knobs for :func:`simulate_trade`.

    ``k_atr_stop`` widens the structure stop to at least ``k·ATR`` from entry (noise buffer); the
    default is **2.0** (widened from 1.5 as a risk mitigation — a wider stop reduces noise /
    stop-hunt exits, and sizing shrinks proportionally so the per-trade risk budget is unchanged).
    At ``partial_tp_r`` (1R) the engine banks ``partial_fraction`` (50 %) and moves the stop to
    breakeven (entry ± ``breakeven_buffer``); the remainder trails ``trail_atr_mult·ATR`` behind
    the best close. ``time_stop_bars`` forces an exit if no target is reached; ``max_spread_mult``
    rejects an entry whose bar range exceeds ``mult × median`` (a spread proxy).
    """

    model_config = ConfigDict(frozen=True)

    k_atr_stop: float = Field(default=2.0, gt=0.0)
    partial_tp_r: float = Field(default=1.0, gt=0.0)
    partial_fraction: float = Field(default=0.5, ge=0.0, le=1.0)
    breakeven_buffer: float = Field(default=0.0, ge=0.0)
    trail_atr_mult: float = Field(default=1.5, gt=0.0)
    time_stop_bars: int = Field(default=8, ge=1)
    max_spread_mult: float = Field(default=3.0, gt=0.0)


class Trade(BaseModel):
    """One fully-simulated trade (partial + remainder folded into ``pnl_points``)."""

    model_config = ConfigDict(frozen=True)

    strategy_id: StrategyId
    direction: SetupDirection
    entry_time: datetime
    exit_time: datetime
    entry: Decimal
    stop: Decimal
    exit_price: Decimal
    pnl_points: Decimal
    r_multiple: Decimal
    bars_held: int = Field(ge=0)
    exit_reason: ExitReason
    regime: Regime | None = None

    @field_validator("entry_time", "exit_time")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(None):
            raise ValueError("trade timestamps must be UTC-aware")
        return value


__all__: list[str] = ["EXIT_REASONS", "ExecutionConfig", "ExitReason", "Trade"]
