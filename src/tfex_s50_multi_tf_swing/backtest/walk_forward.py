"""Anchored walk-forward harness (ROADMAP §8.1).

The first place the Phase-7 risk engine is actually *driven*. Per anchored window it (optionally)
re-fits an ML filter on the **train** slice, then on the **test** slice runs detection → ML gate →
execution (on the **raw per-contract** series, hard rule #3) → cost deduction, and sizes every
candidate trade through :func:`~tfex_s50_multi_tf_swing.risk.decision.evaluate_entry`. Trades the
risk engine rejects (kill switch / session halt / no-trade regime / sub-1 contract) are skipped.

**Anchored windows only — never a random / k-fold split** (TFEX hard rule #6): windows are derived
deterministically from the data span (tz-aware ``Asia/Bangkok``) and ``train_end ≤ test_start``
always holds (asserted in tests). The combined A+B+C run shares **one** daily
:class:`~tfex_s50_multi_tf_swing.risk.models.SessionRiskState` (portfolio-wide daily limits); each
per-strategy run uses its own. Equity (THB, ``Decimal``) compounds across windows.

The per-window ML re-fit is an injected ``ml_filter_factory`` (default ``None`` ⇒ no ML ⇒ Phase-5
behaviour byte-for-byte); the concrete training wiring lives in ``scripts/run_walk_forward.py`` so
this harness stays a lean leaf. Market data is supplied by the caller (the engine / Parquet
snapshot via :mod:`tfex_s50_multi_tf_swing.backtest.data_source`) — this module never fetches tvkit.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import polars as pl

from tfex_s50_multi_tf_swing.backtest.costs import (
    CostedTrade,
    CostModel,
    apply_costs,
    crosses_quarterly_expiry,
    is_illiquid_session,
)
from tfex_s50_multi_tf_swing.backtest.metrics import (
    compute_metrics,
    drawdown_profile,
    period_ratios,
    regime_concentration,
)
from tfex_s50_multi_tf_swing.backtest.models import (
    WalkForwardConfig,
    WalkForwardReport,
    WalkForwardResult,
    WalkForwardWindow,
    WindowResult,
)
from tfex_s50_multi_tf_swing.backtest.per_strategy import DetectFn, SignalFilter
from tfex_s50_multi_tf_swing.data.session import BKK, SessionCalendar
from tfex_s50_multi_tf_swing.execution.engine import simulate_signals
from tfex_s50_multi_tf_swing.execution.models import ExecutionConfig, Trade
from tfex_s50_multi_tf_swing.risk.decision import evaluate_entry
from tfex_s50_multi_tf_swing.risk.limits import register_outcome, start_session
from tfex_s50_multi_tf_swing.risk.models import (
    LadderEvidence,
    PositionSizeRequest,
    RiskConfig,
    TradeOutcome,
)
from tfex_s50_multi_tf_swing.risk.sizing import S50_MULTIPLIER
from tfex_s50_multi_tf_swing.signals.models import STRATEGY_IDS, StrategyId

logger = logging.getLogger(__name__)

_ZERO = Decimal(0)

MLFilterFactory = Callable[[pl.DataFrame, pl.DataFrame, StrategyId], SignalFilter | None]
"""``(train_inputs, train_raw, strategy_id) → fitted SignalFilter | None``.

Called once per window per strategy to re-fit the ML gate on the train slice; ``None`` (the
default) means no ML, reproducing Phase-5 behaviour byte-for-byte. The concrete factory (which
reuses ``ml.training.walk_forward_train`` behind the default-OFF gate) is built in the owner script,
so this module never pulls the ML graph in at import time."""


def generate_windows(
    *, start: datetime, end: datetime, config: WalkForwardConfig
) -> list[WalkForwardWindow]:
    """Yield deterministic anchored (default) or rolling train/test windows over ``[start, end)``.

    Anchored: the train window is ``[start, test_start)`` (start fixed, expanding). Rolling: the
    train window is ``[test_start − train_span, test_start)`` (fixed width). The test block is
    ``[test_start, test_start + test_span)`` clipped to ``end``; ``test_start`` advances by
    ``step_days``. ``train_end == test_start`` so there is never look-ahead.
    """
    train_span = timedelta(days=config.train_span_days)
    test_span = timedelta(days=config.test_span_days)
    step = timedelta(days=config.step_days)

    windows: list[WalkForwardWindow] = []
    test_start = start + train_span
    index = 0
    while test_start < end:
        test_end = min(test_start + test_span, end)
        train_start = start if config.mode == "anchored" else test_start - train_span
        windows.append(
            WalkForwardWindow(
                index=index,
                train_start=train_start,
                train_end=test_start,
                test_start=test_start,
                test_end=test_end,
            )
        )
        index += 1
        test_start += step
    return windows


@dataclass(frozen=True)
class _DriveResult:
    """Outcome of driving one set of costed trades through the risk engine."""

    taken: list[Trade] = field(default_factory=list)
    taken_costed: list[CostedTrade] = field(default_factory=list)
    n_skipped: int = 0
    ending_equity: Decimal = _ZERO
    daily_returns: list[float] = field(default_factory=list)
    breaker_tripped: bool = False


def drive_costed_trades(
    costed: list[CostedTrade],
    *,
    risk_config: RiskConfig,
    start_equity: Decimal,
    calendar: SessionCalendar,
    ladder_evidence: LadderEvidence | None = None,
    window_index: int | None = None,
) -> _DriveResult:
    """Size every costed trade through ``evaluate_entry``; return the taken net trades + equity.

    Trades are walked in ``entry_time`` order. A fresh :class:`SessionRiskState` starts on each new
    BKK trading date; the **net** R of a taken trade is folded back in (so daily-loss / streak /
    count limits react to post-cost outcomes). A trade is skipped when the engine disallows it
    (kill switch / halt / no-trade regime / sub-1 contract) or when equity has been wiped out.

    **Per-window circuit breaker.** A running ``window_cum_r`` accumulates the net R of taken
    trades from the start of this call (= one walk-forward window). Once it breaches
    ``risk_config.per_window_loss_limit_r`` (default ``-5R``), the breaker trips: the event is
    logged (``window_index``, trades taken, drawdown-at-trip) and **every remaining candidate this
    window is suppressed** (counted into ``n_skipped``). Each call is one window, so the breaker
    auto-resets at the next window boundary. ``window_index`` is for the log line only.

    ``ladder_evidence`` is threaded into the capital-deployment guard. **The ladder caps the
    ``paper`` stage to 0 contracts**, so a backtest must run ``risk_config`` at ``micro_live`` or
    higher (with matching evidence) — ``paper`` is logic-validation only and takes no trades.
    """
    evidence = ladder_evidence if ladder_evidence is not None else LadderEvidence()
    breaker_floor = Decimal(str(risk_config.per_window_loss_limit_r))
    ordered = sorted(costed, key=lambda ct: ct.gross.entry_time)
    equity = start_equity
    taken: list[Trade] = []
    taken_costed: list[CostedTrade] = []
    skipped = 0
    daily_r: dict[date, Decimal] = defaultdict(lambda: _ZERO)
    current_day: date | None = None
    session = start_session(date(1970, 1, 1))
    window_cum_r = _ZERO
    breaker_tripped = False

    for i, ct in enumerate(ordered):
        if breaker_tripped:
            skipped += 1
            continue

        bkk_day = ct.gross.entry_time.astimezone(BKK).date()
        if bkk_day != current_day:
            current_day = bkk_day
            session = start_session(bkk_day)

        stop_distance = abs(ct.gross.entry - ct.gross.stop)
        if equity <= _ZERO or stop_distance <= _ZERO:
            skipped += 1
            continue

        decision = evaluate_entry(
            request=PositionSizeRequest(
                equity=equity,
                stop_distance_points=stop_distance,
                rv_percentile=None,
                regime=ct.gross.regime,
            ),
            session_state=session,
            config=risk_config,
            evidence=evidence,
        )
        if not decision.allow_entry or decision.contracts == 0:
            skipped += 1
            continue

        net = ct.net_trade
        taken.append(net)
        taken_costed.append(ct)
        equity += Decimal(decision.contracts) * net.pnl_points * S50_MULTIPLIER
        daily_r[bkk_day] += net.r_multiple
        window_cum_r += net.r_multiple
        session = register_outcome(
            session, TradeOutcome(r_multiple=net.r_multiple, session_date=bkk_day), risk_config
        )

        if window_cum_r <= breaker_floor:
            breaker_tripped = True
            logger.warning(
                "circuit breaker tripped (window=%s): cumulative %sR ≤ floor %sR after %d "
                "trade(s); suppressing %d remaining candidate(s) this window",
                window_index,
                window_cum_r,
                breaker_floor,
                len(taken),
                len(ordered) - i - 1,
            )

    returns = [float(daily_r[d]) for d in sorted(daily_r)]
    return _DriveResult(
        taken=taken,
        taken_costed=taken_costed,
        n_skipped=skipped,
        ending_equity=equity,
        daily_returns=returns,
        breaker_tripped=breaker_tripped,
    )


def _slice(df: pl.DataFrame, start: datetime, end: datetime) -> pl.DataFrame:
    """Rows with ``start ≤ time < end`` (bounds coerced to UTC instants)."""
    lo, hi = start.astimezone(UTC), end.astimezone(UTC)
    return df.filter((pl.col("time") >= lo) & (pl.col("time") < hi))


def _atr_map(raw_bars: pl.DataFrame) -> dict[datetime, float]:
    """``entry_time → ATR`` lookup for cost scaling (skips null ATR rows)."""
    times = raw_bars.get_column("time").to_list()
    atrs = raw_bars.get_column("atr").to_list()
    return {t: float(a) for t, a in zip(times, atrs, strict=True) if a is not None}


def _costed_trades_for_window(
    window: WalkForwardWindow,
    *,
    inputs: pl.DataFrame,
    raw_bars: pl.DataFrame,
    detect: Mapping[StrategyId, DetectFn],
    exec_config: ExecutionConfig,
    cost_model: CostModel,
    calendar: SessionCalendar,
    ml_filter_factory: MLFilterFactory | None,
) -> dict[StrategyId, list[CostedTrade]]:
    """Detect → (optional ML gate) → simulate on raw bars → cost, per strategy, for one window."""
    test_inputs = _slice(inputs, window.test_start, window.test_end)
    test_raw = _slice(raw_bars, window.test_start, window.test_end)
    train_inputs = _slice(inputs, window.train_start, window.train_end)
    train_raw = _slice(raw_bars, window.train_start, window.train_end)
    atr_at = _atr_map(test_raw)

    by_sid: dict[StrategyId, list[CostedTrade]] = {}
    for sid, detect_fn in detect.items():
        signals = detect_fn(test_inputs)
        if ml_filter_factory is not None:
            fitted = ml_filter_factory(train_inputs, train_raw, sid)
            if fitted is not None:
                signals = fitted(signals, test_inputs)
        trades = simulate_signals(signals, test_raw, config=exec_config)
        costed: list[CostedTrade] = []
        for trade in trades:
            atr_entry = atr_at.get(trade.entry_time, 0.0)
            illiquid = is_illiquid_session(calendar, trade.entry_time)
            rollover = crosses_quarterly_expiry(trade.entry_time, trade.exit_time, calendar)
            costed.append(
                apply_costs(
                    trade,
                    atr_at_entry=atr_entry,
                    illiquid=illiquid,
                    config=cost_model,
                    crosses_rollover=rollover,
                )
            )
        by_sid[sid] = costed
    return by_sid


def _window_result(
    window: WalkForwardWindow,
    drive: _DriveResult,
    start_equity: Decimal,
    *,
    strategy_id: StrategyId | None,
) -> WindowResult:
    nav = float(drive.ending_equity / start_equity * 100) if start_equity > _ZERO else 0.0
    return WindowResult(
        window=window,
        metrics=compute_metrics(drive.taken, strategy_id=strategy_id),
        drawdown=drawdown_profile(drive.taken),
        ratios=period_ratios(drive.daily_returns),
        n_taken=len(drive.taken),
        n_skipped_by_risk=drive.n_skipped,
        ending_equity=drive.ending_equity,
        nav_index=nav,
        circuit_breaker_tripped=drive.breaker_tripped,
        trades=drive.taken_costed,
    )


def _aggregate(
    *,
    strategy_id: StrategyId | None,
    windows: list[WindowResult],
    trades: list[Trade],
    daily: list[float],
    start_equity: Decimal,
    ending_equity: Decimal,
) -> WalkForwardResult:
    metrics = compute_metrics(trades, strategy_id=strategy_id)
    return WalkForwardResult(
        strategy_id=strategy_id,
        windows=windows,
        overall=metrics,
        drawdown=drawdown_profile(trades),
        ratios=period_ratios(daily),
        regime_concentration=regime_concentration(metrics),
        start_equity=start_equity,
        ending_equity=ending_equity,
    )


def run_walk_forward(
    *,
    inputs: pl.DataFrame,
    raw_bars: pl.DataFrame,
    detect: Mapping[StrategyId, DetectFn],
    wf_config: WalkForwardConfig,
    exec_config: ExecutionConfig,
    risk_config: RiskConfig,
    cost_model: CostModel,
    calendar: SessionCalendar | None = None,
    ml_filter_factory: MLFilterFactory | None = None,
    ladder_evidence: LadderEvidence | None = None,
) -> WalkForwardReport:
    """Run the anchored walk-forward over every window: combined (shared session) + per-strategy.

    ``inputs`` is the aligned 5m signal-input frame (built off the back-adjusted continuous);
    ``raw_bars`` is the raw per-contract 5m execution frame (``time``/OHLC/``atr``). The data span
    is read from ``inputs`` and converted to BKK for window generation. ``ladder_evidence`` flows to
    the capital-deployment guard — run ``risk_config`` at ``micro_live`` or higher, since ``paper``
    caps to 0 contracts and takes no trades (see :func:`drive_costed_trades`).
    """
    cal = calendar or SessionCalendar()
    times = inputs.get_column("time")
    lo, hi = times.min(), times.max()
    windows: list[WalkForwardWindow] = []
    if isinstance(lo, datetime) and isinstance(hi, datetime):
        windows = generate_windows(
            start=lo.astimezone(BKK), end=hi.astimezone(BKK), config=wf_config
        )

    combined_results: list[WindowResult] = []
    combined_trades: list[Trade] = []
    combined_daily: list[float] = []
    combined_equity = wf_config.start_equity

    sids: tuple[StrategyId, ...] = STRATEGY_IDS
    sid_results: dict[StrategyId, list[WindowResult]] = {s: [] for s in sids}
    sid_trades: dict[StrategyId, list[Trade]] = {s: [] for s in sids}
    sid_daily: dict[StrategyId, list[float]] = {s: [] for s in sids}
    sid_equity: dict[StrategyId, Decimal] = {s: wf_config.start_equity for s in sids}

    for window in windows:
        by_sid = _costed_trades_for_window(
            window,
            inputs=inputs,
            raw_bars=raw_bars,
            detect=detect,
            exec_config=exec_config,
            cost_model=cost_model,
            calendar=cal,
            ml_filter_factory=ml_filter_factory,
        )

        merged = [ct for s in sids for ct in by_sid.get(s, [])]
        drive = drive_costed_trades(
            merged,
            risk_config=risk_config,
            start_equity=combined_equity,
            calendar=cal,
            ladder_evidence=ladder_evidence,
            window_index=window.index,
        )
        combined_results.append(_window_result(window, drive, combined_equity, strategy_id=None))
        combined_trades.extend(drive.taken)
        combined_daily.extend(drive.daily_returns)
        combined_equity = drive.ending_equity

        for sid in sids:
            sd = drive_costed_trades(
                by_sid.get(sid, []),
                risk_config=risk_config,
                start_equity=sid_equity[sid],
                calendar=cal,
                ladder_evidence=ladder_evidence,
                window_index=window.index,
            )
            sid_results[sid].append(_window_result(window, sd, sid_equity[sid], strategy_id=sid))
            sid_trades[sid].extend(sd.taken)
            sid_daily[sid].extend(sd.daily_returns)
            sid_equity[sid] = sd.ending_equity

    combined = _aggregate(
        strategy_id=None,
        windows=combined_results,
        trades=combined_trades,
        daily=combined_daily,
        start_equity=wf_config.start_equity,
        ending_equity=combined_equity,
    )
    per_strategy = {
        sid: _aggregate(
            strategy_id=sid,
            windows=sid_results[sid],
            trades=sid_trades[sid],
            daily=sid_daily[sid],
            start_equity=wf_config.start_equity,
            ending_equity=sid_equity[sid],
        )
        for sid in sids
    }
    return WalkForwardReport(
        config=wf_config, windows=windows, combined=combined, per_strategy=per_strategy
    )


__all__: list[str] = [
    "MLFilterFactory",
    "drive_costed_trades",
    "generate_windows",
    "run_walk_forward",
]
