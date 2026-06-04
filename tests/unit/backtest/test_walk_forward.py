"""Walk-forward harness tests (ROADMAP §8.1) — windows, risk-driving, end-to-end + edge cases."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import polars as pl

from tfex_s50_multi_tf_swing.backtest.costs import CostModel
from tfex_s50_multi_tf_swing.backtest.models import WalkForwardConfig
from tfex_s50_multi_tf_swing.backtest.walk_forward import (
    drive_costed_trades,
    generate_windows,
    run_walk_forward,
)
from tfex_s50_multi_tf_swing.data.session import SessionCalendar
from tfex_s50_multi_tf_swing.execution.models import ExecutionConfig
from tfex_s50_multi_tf_swing.risk.models import RiskConfig
from tfex_s50_multi_tf_swing.signals.models import SetupSignal

from .conftest import T0, costed, make_trade, ramp_bars

_START = datetime(2016, 1, 1, tzinfo=UTC)
_END = datetime(2024, 1, 1, tzinfo=UTC)


def _risk(**overrides: object) -> RiskConfig:
    """A backtest risk config — ``micro_live`` permits ≥1 contract (``paper`` caps to 0)."""
    return RiskConfig(deployment_stage="micro_live", **overrides)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# generate_windows — anchored / rolling, no look-ahead, deterministic
# ---------------------------------------------------------------------------


def test_generate_windows_anchored_no_look_ahead() -> None:
    cfg = WalkForwardConfig(train_span_days=1095, test_span_days=365, step_days=365)
    windows = generate_windows(start=_START, end=_END, config=cfg)
    assert windows  # at least one
    for w in windows:
        assert w.train_start == _START  # anchored: start fixed
        assert w.train_end == w.test_start  # no look-ahead: train ends where test starts
        assert w.train_end <= w.test_start
        assert w.test_start < _END


def test_generate_windows_rolling_fixed_width() -> None:
    cfg = WalkForwardConfig(mode="rolling", train_span_days=1095, test_span_days=365, step_days=365)
    windows = generate_windows(start=_START, end=_END, config=cfg)
    span = timedelta(days=1095)
    for w in windows:
        assert w.train_start == w.test_start - span
        assert w.train_end == w.test_start


def test_generate_windows_is_deterministic_not_random() -> None:
    cfg = WalkForwardConfig()
    first = generate_windows(start=_START, end=_END, config=cfg)
    second = generate_windows(start=_START, end=_END, config=cfg)
    assert first == second  # never a random split


def test_generate_windows_empty_when_span_too_short() -> None:
    cfg = WalkForwardConfig(train_span_days=1095)
    windows = generate_windows(start=_START, end=_START + timedelta(days=10), config=cfg)
    assert windows == []


# ---------------------------------------------------------------------------
# drive_costed_trades — the risk engine is driven per trade
# ---------------------------------------------------------------------------


def _cal() -> SessionCalendar:
    return SessionCalendar()


def test_drive_takes_winners_and_compounds_equity() -> None:
    trades = [costed(make_trade(r=Decimal("1"), when=T0), net_r=Decimal("1")) for _ in range(3)]
    out = drive_costed_trades(
        trades, risk_config=_risk(), start_equity=Decimal("200000"), calendar=_cal()
    )
    assert len(out.taken) == 3
    assert out.n_skipped == 0
    assert out.ending_equity > Decimal("200000")
    assert out.daily_returns == [3.0]  # one trading day, three +1R trades


def test_drive_skips_no_trade_regime() -> None:
    trade = costed(make_trade(regime="range_low_vol"), net_r=Decimal("1"))
    out = drive_costed_trades(
        [trade], risk_config=_risk(), start_equity=Decimal("200000"), calendar=_cal()
    )
    assert out.taken == []
    assert out.n_skipped == 1


def test_drive_kill_switch_skips_everything() -> None:
    trade = costed(make_trade(), net_r=Decimal("1"))
    out = drive_costed_trades(
        [trade],
        risk_config=_risk(kill_switch_engaged=True),
        start_equity=Decimal("200000"),
        calendar=_cal(),
    )
    assert out.taken == []
    assert out.n_skipped == 1


def test_drive_session_loss_limit_halts_midstream() -> None:
    losers = [costed(make_trade(when=T0), net_r=Decimal("-1")) for _ in range(4)]
    out = drive_costed_trades(
        losers, risk_config=_risk(), start_equity=Decimal("200000"), calendar=_cal()
    )
    # cumulative -2R after two losers halts the session; the rest are skipped.
    assert len(out.taken) == 2
    assert out.n_skipped == 2


def test_drive_paper_stage_takes_no_trades() -> None:
    # paper stage caps to 0 contracts — a backtest must run at micro_live or higher.
    trades = [costed(make_trade(when=T0), net_r=Decimal("1")) for _ in range(2)]
    out = drive_costed_trades(
        trades,
        risk_config=RiskConfig(deployment_stage="paper"),
        start_equity=Decimal("200000"),
        calendar=_cal(),
    )
    assert out.taken == []
    assert out.n_skipped == 2


def test_drive_skips_when_equity_wiped() -> None:
    trade = costed(make_trade(), net_r=Decimal("1"))
    out = drive_costed_trades(
        [trade], risk_config=_risk(), start_equity=Decimal("0"), calendar=_cal()
    )
    assert out.taken == []
    assert out.n_skipped == 1


def test_drive_skips_zero_stop_distance() -> None:
    flat = costed(
        make_trade(entry=Decimal("100"), stop=Decimal("100"), r=Decimal("0")), net_r=Decimal("1")
    )
    out = drive_costed_trades(
        [flat], risk_config=_risk(), start_equity=Decimal("200000"), calendar=_cal()
    )
    assert out.taken == []
    assert out.n_skipped == 1


def test_drive_aggregates_returns_per_day() -> None:
    day2 = T0 + timedelta(days=1)
    trades = [
        costed(make_trade(when=T0), net_r=Decimal("1")),
        costed(make_trade(when=day2), net_r=Decimal("1")),
    ]
    out = drive_costed_trades(
        trades, risk_config=_risk(), start_equity=Decimal("200000"), calendar=_cal()
    )
    assert len(out.daily_returns) == 2


# ---------------------------------------------------------------------------
# run_walk_forward — end-to-end on a synthetic ramp
# ---------------------------------------------------------------------------


def _detect_long(df: pl.DataFrame) -> list[SetupSignal]:
    if df.height < 5:
        return []
    row = df.row(0, named=True)
    return [
        SetupSignal(
            strategy_id="A",
            time=row["time"],
            direction="long",
            trigger_price=Decimal(str(row["close"])),
            stop_reference=Decimal(str(row["close"] - 2.0)),
            regime="trend_up",
        )
    ]


def _small_config() -> WalkForwardConfig:
    return WalkForwardConfig(train_span_days=10, test_span_days=5, step_days=5)


def _run(**kwargs: object):  # type: ignore[no-untyped-def]
    bars = ramp_bars(720)  # 30 days of hourly bars
    return run_walk_forward(
        inputs=bars,
        raw_bars=bars,
        detect={"A": _detect_long},
        wf_config=_small_config(),
        exec_config=ExecutionConfig(),
        risk_config=_risk(),
        cost_model=CostModel(),
        **kwargs,  # type: ignore[arg-type]
    )


def test_run_walk_forward_end_to_end() -> None:
    report = _run()
    assert len(report.windows) >= 1
    assert report.combined.overall.n_trades > 0
    assert report.per_strategy["A"].overall.n_trades > 0
    assert report.per_strategy["B"].overall.n_trades == 0  # B/C emit nothing here
    assert report.combined.start_equity == Decimal("200000")


def test_run_walk_forward_ml_factory_drops_all() -> None:
    def drop_all_factory(_ti: pl.DataFrame, _tr: pl.DataFrame, _sid: str):  # type: ignore[no-untyped-def]
        return lambda _sigs, _frame: []

    report = _run(ml_filter_factory=drop_all_factory)
    assert report.combined.overall.n_trades == 0


def test_run_walk_forward_ml_factory_none_is_identity() -> None:
    def none_factory(_ti: pl.DataFrame, _tr: pl.DataFrame, _sid: str):  # type: ignore[no-untyped-def]
        return None

    baseline = _run().combined.overall.n_trades
    gated = _run(ml_filter_factory=none_factory).combined.overall.n_trades
    assert gated == baseline


def test_run_walk_forward_empty_windows() -> None:
    small = ramp_bars(3)
    report = run_walk_forward(
        inputs=small,
        raw_bars=small,
        detect={"A": _detect_long},
        wf_config=WalkForwardConfig(),  # default 1095d train ≫ 3-bar span
        exec_config=ExecutionConfig(),
        risk_config=_risk(),
        cost_model=CostModel(),
    )
    assert report.windows == []
    assert report.combined.overall.n_trades == 0
