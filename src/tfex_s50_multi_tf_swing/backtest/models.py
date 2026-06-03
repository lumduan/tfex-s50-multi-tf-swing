"""Type contracts for the per-strategy backtest (ROADMAP §5.5).

All metrics are **Decimal** and expressed in **R-multiples** (and counts) — no THB, no cost
model (those are Phase 7 / 8). ``profit_factor`` is ``None`` when there are no losing trades
(the ratio is undefined / infinite) so it never silently reports a misleading number.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from tfex_s50_multi_tf_swing.regime.models import Regime
from tfex_s50_multi_tf_swing.signals.models import StrategyId


class RegimeMetrics(BaseModel):
    """Per-regime slice of a strategy's performance."""

    model_config = ConfigDict(frozen=True)

    regime: Regime
    n_trades: int = Field(ge=0)
    expectancy_r: Decimal
    profit_factor: Decimal | None = None
    win_rate: Decimal = Field(ge=0, le=1)


class BacktestMetrics(BaseModel):
    """Aggregate per-strategy backtest report (ROADMAP §5.5)."""

    model_config = ConfigDict(frozen=True)

    strategy_id: StrategyId | None = None
    n_trades: int = Field(ge=0)
    expectancy_r: Decimal
    profit_factor: Decimal | None = None
    max_drawdown_r: Decimal = Field(ge=0)
    win_rate: Decimal = Field(ge=0, le=1)
    per_regime: dict[Regime, RegimeMetrics] = Field(default_factory=dict)


__all__: list[str] = ["BacktestMetrics", "RegimeMetrics"]
