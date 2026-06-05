"""Type contracts for the per-strategy backtest (ROADMAP §5.5) and the walk-forward harness (§8).

Phase-5 metrics are **Decimal** R-multiples (and counts). Phase-8 adds the walk-forward result
models: anchored windows, per-window / aggregate results, the drawdown profile (depth + time
underwater + recovery), per-period Sharpe / Sortino ratios, and the regime-concentration flag.
``profit_factor`` is ``None`` when there are no losing trades (undefined / infinite) so it never
silently reports a misleading number. Risk-adjusted ratios stay **float** (statistical quantities);
equity stays **Decimal** (THB money).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tfex_s50_multi_tf_swing.backtest.costs import CostedTrade
from tfex_s50_multi_tf_swing.regime.models import Regime
from tfex_s50_multi_tf_swing.signals.models import StrategyId

WindowMode = Literal["anchored", "rolling"]
"""Walk-forward window shape: ``anchored`` (train start fixed, expands) or ``rolling`` (fixed-width
train start rolling forward). Both are deterministic and time-ordered — never a random / k-fold
split (TFEX hard rule #6)."""


class RegimeMetrics(BaseModel):
    """Per-regime slice of a strategy's performance."""

    model_config = ConfigDict(frozen=True)

    regime: Regime
    n_trades: int = Field(ge=0)
    expectancy_r: Decimal
    profit_factor: Decimal | None = None
    win_rate: Decimal = Field(ge=0, le=1)
    # Average holding duration: mean ``bars_held`` (1H bars ⇒ market hours of exposure) and the
    # same converted to market days. ``None`` when the regime slice has no trades.
    avg_holding_hours: float | None = None
    avg_holding_market_days: float | None = None


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
    # Average holding duration: mean ``bars_held`` (1H bars ⇒ market hours of exposure) and the
    # same converted to market days. ``None`` when there are no trades.
    avg_holding_hours: float | None = None
    avg_holding_market_days: float | None = None


# ---------------------------------------------------------------------------
# Phase 8 — walk-forward harness contracts
# ---------------------------------------------------------------------------


class WalkForwardConfig(BaseModel):
    """Frozen, bounded knobs for the anchored walk-forward harness (ROADMAP §8.1).

    ``mode`` defaults to ``anchored`` (train start fixed at the data start, expanding each step);
    ``rolling`` keeps a fixed-width ``train_span_days`` train window whose start rolls forward.
    ``start_equity`` seeds the THB equity curve; ``seed`` is threaded into any per-window ML re-fit.
    ``refit_ml`` only re-fits when the ML filter is also enabled (default off ⇒ Phase-5 behaviour).
    """

    model_config = ConfigDict(frozen=True)

    mode: WindowMode = "anchored"
    train_span_days: int = Field(default=1095, ge=1)
    test_span_days: int = Field(default=365, ge=1)
    step_days: int = Field(default=365, ge=1)
    start_equity: Decimal = Field(default=Decimal("200000"), gt=0)
    seed: int = Field(default=42, ge=0)
    refit_ml: bool = False


class WalkForwardWindow(BaseModel):
    """One anchored train/test split. ``train_end ≤ test_start`` always holds (no look-ahead)."""

    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=0)
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime


class DrawdownProfile(BaseModel):
    """Max peak-to-trough drawdown plus survivability detail (in R-multiples / trade counts)."""

    model_config = ConfigDict(frozen=True)

    depth_r: Decimal = Field(ge=0)
    time_underwater: int = Field(ge=0)
    recovery_trades: int | None = None


class PeriodRatios(BaseModel):
    """Per-period (daily-summed net-R) risk-adjusted ratios; ``None`` when undefined."""

    model_config = ConfigDict(frozen=True)

    sharpe: float | None = None
    sortino: float | None = None
    n_periods: int = Field(ge=0)


class RegimeConcentration(BaseModel):
    """Fails loudly when one regime carries the edge (ROADMAP §8.2 robustness check)."""

    model_config = ConfigDict(frozen=True)

    dominant_regime: Regime | None = None
    share: float = Field(default=0.0, ge=0.0, le=1.0)
    concentrated: bool = False


class WindowResult(BaseModel):
    """Post-cost, risk-driven result for a single walk-forward window."""

    model_config = ConfigDict(frozen=True)

    window: WalkForwardWindow
    metrics: BacktestMetrics
    drawdown: DrawdownProfile
    ratios: PeriodRatios
    n_taken: int = Field(ge=0)
    n_skipped_by_risk: int = Field(ge=0)
    ending_equity: Decimal
    nav_index: float
    circuit_breaker_tripped: bool = False
    # The taken trades (post-cost) for this window: each :class:`CostedTrade` carries the gross
    # :class:`Trade` (entry/exit times + prices, gross R, exit reason, regime) plus the net R and
    # the per-trade cost breakdown (commission / slippage / spread / roll-over). Empty when the
    # window took no trades. Used for trade-log / deep-dive analysis — never serialised to the
    # public JSON (it carries price levels).
    trades: list[CostedTrade] = Field(default_factory=list)


class WalkForwardResult(BaseModel):
    """Aggregate over every window for one track (``strategy_id=None`` ⇒ the combined A+B+C run)."""

    model_config = ConfigDict(frozen=True)

    strategy_id: StrategyId | None = None
    windows: list[WindowResult] = Field(default_factory=list)
    overall: BacktestMetrics
    drawdown: DrawdownProfile
    ratios: PeriodRatios
    regime_concentration: RegimeConcentration
    start_equity: Decimal
    ending_equity: Decimal


class WalkForwardReport(BaseModel):
    """The full Phase-8 report: the combined run + the per-strategy (isolated) runs."""

    model_config = ConfigDict(frozen=True)

    config: WalkForwardConfig
    windows: list[WalkForwardWindow] = Field(default_factory=list)
    combined: WalkForwardResult
    per_strategy: dict[StrategyId, WalkForwardResult] = Field(default_factory=dict)


__all__: list[str] = [
    "BacktestMetrics",
    "DrawdownProfile",
    "PeriodRatios",
    "RegimeConcentration",
    "RegimeMetrics",
    "WalkForwardConfig",
    "WalkForwardReport",
    "WalkForwardResult",
    "WalkForwardWindow",
    "WindowMode",
    "WindowResult",
]
