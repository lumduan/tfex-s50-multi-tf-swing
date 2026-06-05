"""Per-strategy backtest metrics (ROADMAP §5.5) + walk-forward metrics (§8.2).

Pure functions over a ``list[Trade]`` — expectancy (mean R), profit factor (gross-win-R /
gross-loss-R), max drawdown (on the cumulative-R equity curve), win rate, and a regime
stratification. Phase 8 adds the **drawdown profile** (depth + time underwater + recovery),
per-period **Sharpe / Sortino** (over a float return series), and a **regime-concentration** check
that fails loudly when one regime carries the edge. R-multiple quantities are
:class:`~decimal.Decimal`; risk-adjusted ratios and the concentration share are :class:`float`
(statistical quantities). All functions are empty-safe (no divide-by-zero, no exceptions on an
empty input).
"""

from __future__ import annotations

import math
from collections import defaultdict
from decimal import Decimal

from tfex_s50_multi_tf_swing.backtest.models import (
    BacktestMetrics,
    DrawdownProfile,
    PeriodRatios,
    RegimeConcentration,
    RegimeMetrics,
)
from tfex_s50_multi_tf_swing.execution.models import Trade
from tfex_s50_multi_tf_swing.regime.models import Regime
from tfex_s50_multi_tf_swing.signals.models import StrategyId

_ZERO = Decimal(0)

#: Approximate count of 1H bars in one TFEX S50-futures trading day (morning + afternoon +
#: night sessions). Used to convert a mean ``bars_held`` into market days. An approximation —
#: the exact bar count varies with the night-session schedule — but stable for reporting.
TFEX_BARS_PER_TRADING_DAY = 8


def avg_holding(trades: list[Trade]) -> tuple[float | None, float | None]:
    """Mean holding duration as ``(hours, market_days)``.

    On the 1H execution timeframe ``Trade.bars_held`` is the count of 1H bars held, i.e. the
    market-hours of exposure (overnight closed hours are not counted, so this never inflates).
    Market days divide that by :data:`TFEX_BARS_PER_TRADING_DAY`. Returns ``(None, None)`` when
    there are no trades.
    """
    if not trades:
        return None, None
    mean_hours = sum(t.bars_held for t in trades) / len(trades)
    return mean_hours, mean_hours / TFEX_BARS_PER_TRADING_DAY


def expectancy(trades: list[Trade]) -> Decimal:
    """Mean R-multiple per trade (``0`` when there are no trades)."""
    if not trades:
        return _ZERO
    total = sum((t.r_multiple for t in trades), _ZERO)
    return total / Decimal(len(trades))


def profit_factor(trades: list[Trade]) -> Decimal | None:
    """Gross-win-R / gross-loss-R; ``None`` when there are no losses (undefined / infinite)."""
    gross_win = sum((t.r_multiple for t in trades if t.r_multiple > 0), _ZERO)
    gross_loss = sum((-t.r_multiple for t in trades if t.r_multiple < 0), _ZERO)
    if gross_loss == _ZERO:
        return None
    return gross_win / gross_loss


def max_drawdown(trades: list[Trade]) -> Decimal:
    """Max peak-to-trough drop of the cumulative-R equity curve, as a non-negative Decimal."""
    equity = _ZERO
    peak = _ZERO
    worst = _ZERO
    for trade in trades:
        equity += trade.r_multiple
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def win_rate(trades: list[Trade]) -> Decimal:
    """Fraction of trades with positive R (``0`` when there are no trades)."""
    if not trades:
        return _ZERO
    wins = sum(1 for t in trades if t.r_multiple > 0)
    return Decimal(wins) / Decimal(len(trades))


def regime_stratified(trades: list[Trade]) -> dict[Regime, RegimeMetrics]:
    """Per-regime metrics; trades with no regime label are omitted (still in the aggregate)."""
    buckets: dict[Regime, list[Trade]] = defaultdict(list)
    for trade in trades:
        if trade.regime is not None:
            buckets[trade.regime].append(trade)
    result: dict[Regime, RegimeMetrics] = {}
    for regime, group in buckets.items():
        hours, market_days = avg_holding(group)
        result[regime] = RegimeMetrics(
            regime=regime,
            n_trades=len(group),
            expectancy_r=expectancy(group),
            profit_factor=profit_factor(group),
            win_rate=win_rate(group),
            avg_holding_hours=hours,
            avg_holding_market_days=market_days,
        )
    return result


def drawdown_profile(trades: list[Trade]) -> DrawdownProfile:
    """Max peak-to-trough drawdown plus time-underwater and recovery (in trade counts).

    ``time_underwater`` counts trades while the equity curve sits below its running peak;
    ``recovery_trades`` is how many trades after the *deepest* trough the curve takes to reclaim
    the prior peak — ``None`` if it never recovers within the sample.
    """
    equity = _ZERO
    peak = _ZERO
    worst = _ZERO
    underwater = 0
    trough_at = -1
    peak_before_trough = _ZERO
    for i, trade in enumerate(trades):
        equity += trade.r_multiple
        if equity > peak:
            peak = equity
        if equity < peak:
            underwater += 1
        drop = peak - equity
        if drop > worst:
            worst = drop
            trough_at = i
            peak_before_trough = peak

    recovery: int | None = None
    if trough_at >= 0:
        running = _ZERO
        for j, trade in enumerate(trades):
            running += trade.r_multiple
            if j > trough_at and running >= peak_before_trough:
                recovery = j - trough_at
                break
    return DrawdownProfile(depth_r=worst, time_underwater=underwater, recovery_trades=recovery)


def sharpe(returns: list[float]) -> float | None:
    """Sample Sharpe over a per-period return series (mean / stdev); ``None`` if undefined."""
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(variance)
    if std == 0.0:
        return None
    return mean / std


def sortino(returns: list[float]) -> float | None:
    """Sortino over a per-period series (mean / downside-deviation); ``None`` if undefined."""
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    downside = [r for r in returns if r < 0.0]
    if not downside:
        return None
    downside_var = sum(r**2 for r in downside) / len(returns)
    downside_dev = math.sqrt(downside_var)
    # downside is non-empty here, so every r**2 > 0 ⇒ downside_dev > 0 (no zero-division).
    return mean / downside_dev


def period_ratios(returns: list[float]) -> PeriodRatios:
    """Bundle Sharpe + Sortino over ``returns`` (each per-period net-R)."""
    return PeriodRatios(sharpe=sharpe(returns), sortino=sortino(returns), n_periods=len(returns))


def regime_concentration(
    metrics: BacktestMetrics, *, threshold: float = 0.8
) -> RegimeConcentration:
    """Flag when one regime carries a dominant share of the total absolute expectancy contribution.

    Each regime's contribution is ``|expectancy_r · n_trades|``; the share is the dominant regime's
    contribution over the sum across regimes. ``concentrated`` is ``True`` when that share exceeds
    ``threshold`` **and** more than one regime traded — robustness fails loudly (ROADMAP §8.2).
    """
    contributions: dict[Regime, float] = {
        regime: abs(float(rm.expectancy_r) * rm.n_trades)
        for regime, rm in metrics.per_regime.items()
    }
    total = sum(contributions.values())
    if total <= 0.0 or not contributions:
        return RegimeConcentration()
    dominant = max(contributions, key=lambda r: contributions[r])
    share = contributions[dominant] / total
    concentrated = share > threshold and len(contributions) > 1
    return RegimeConcentration(dominant_regime=dominant, share=share, concentrated=concentrated)


def compute_metrics(
    trades: list[Trade], *, strategy_id: StrategyId | None = None
) -> BacktestMetrics:
    """Assemble the full :class:`BacktestMetrics` report (empty-safe)."""
    hours, market_days = avg_holding(trades)
    return BacktestMetrics(
        strategy_id=strategy_id,
        n_trades=len(trades),
        expectancy_r=expectancy(trades),
        profit_factor=profit_factor(trades),
        max_drawdown_r=max_drawdown(trades),
        win_rate=win_rate(trades),
        per_regime=regime_stratified(trades),
        avg_holding_hours=hours,
        avg_holding_market_days=market_days,
    )


__all__: list[str] = [
    "TFEX_BARS_PER_TRADING_DAY",
    "avg_holding",
    "compute_metrics",
    "drawdown_profile",
    "expectancy",
    "max_drawdown",
    "period_ratios",
    "profit_factor",
    "regime_concentration",
    "regime_stratified",
    "sharpe",
    "sortino",
    "win_rate",
]
