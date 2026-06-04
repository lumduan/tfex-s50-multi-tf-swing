"""§8 demonstration — anchored walk-forward backtest with a realistic cost model (public-safe).

Runs the Phase-8 harness end-to-end on whatever continuous snapshot the local store holds (the
engine's offline Parquet snapshot — never a tvkit fetch), driving the Phase-7 risk engine over
Phase-5 signals/execution with the cost model, and writes a **public-safe** artifact (trade counts
+ R-multiple metrics + risk-adjusted ratios + NAV index only, **no raw OHLCV**, **no equity
arrays**) to ``results/static/backtest/walk_forward.json``.

The real-data exit-criteria *magnitudes* (positive expectancy after costs, drawdown within budget,
regime stability) are **data-gated** on the 5-year TFEX backfill + engine TFEX data (see the plan's
Design Decisions). This script exercises the *harness*, not a magnitude claim. Per-window ML re-fit
is the injectable ``ml_filter_factory`` hook on ``run_walk_forward``; here it binds a pre-loaded
bundle when the ML filter is enabled (true per-window training is data-gated).

Usage::

    uv run python scripts/run_walk_forward.py
    uv run python scripts/run_walk_forward.py --with-4h --out-dir results/static/backtest
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final

import polars as pl

from tfex_s50_multi_tf_swing.backtest.data_source import (
    build_execution_bars,
    load_continuous_frames,
)
from tfex_s50_multi_tf_swing.backtest.models import (
    WalkForwardReport,
    WalkForwardResult,
    WindowResult,
)
from tfex_s50_multi_tf_swing.backtest.per_strategy import DetectFn, SignalFilter
from tfex_s50_multi_tf_swing.backtest.walk_forward import MLFilterFactory, run_walk_forward
from tfex_s50_multi_tf_swing.config.settings import get_settings
from tfex_s50_multi_tf_swing.data.store import ParquetStore
from tfex_s50_multi_tf_swing.ml.filter import filter_signals
from tfex_s50_multi_tf_swing.ml.store import load_bundle
from tfex_s50_multi_tf_swing.risk.models import LadderEvidence, RiskConfig
from tfex_s50_multi_tf_swing.signals import strategy_a, strategy_b, strategy_c
from tfex_s50_multi_tf_swing.signals.inputs import build_signal_inputs
from tfex_s50_multi_tf_swing.signals.models import (
    SetupSignal,
    SignalConfig,
    StrategyId,
)

logger: logging.Logger = logging.getLogger(__name__)

_LOG_FORMAT: Final[str] = "%(asctime)s [%(levelname)-7s] %(name)s - %(message)s"
_DEFAULT_OUT: Final[Path] = Path("results/static/backtest")

_DETECT: dict[StrategyId, Callable[[pl.DataFrame, SignalConfig], list[SetupSignal]]] = {
    "A": lambda df, cfg: strategy_a.to_signals(strategy_a.classify_frame(df, config=cfg)),
    "B": lambda df, cfg: strategy_b.to_signals(strategy_b.classify_frame(df, config=cfg)),
    "C": lambda df, cfg: strategy_c.to_signals(strategy_c.classify_frame(df, config=cfg)),
}


def _window_to_dict(wr: WindowResult) -> dict[str, object]:
    pf = wr.metrics.profit_factor
    return {
        "index": wr.window.index,
        "test_start": wr.window.test_start.isoformat(),
        "test_end": wr.window.test_end.isoformat(),
        "n_taken": wr.n_taken,
        "n_skipped_by_risk": wr.n_skipped_by_risk,
        "expectancy_r": float(wr.metrics.expectancy_r),
        "profit_factor": float(pf) if pf is not None else None,
        "max_drawdown_r": float(wr.drawdown.depth_r),
        "time_underwater": wr.drawdown.time_underwater,
        "recovery_trades": wr.drawdown.recovery_trades,
        "sharpe": wr.ratios.sharpe,
        "sortino": wr.ratios.sortino,
        "nav_index": wr.nav_index,
    }


def _result_to_dict(result: WalkForwardResult) -> dict[str, object]:
    """Public-safe view: counts + R-multiple metrics + ratios + NAV only (never any price/OHLCV)."""
    pf = result.overall.profit_factor
    conc = result.regime_concentration
    return {
        "strategy_id": result.strategy_id,
        "n_trades": result.overall.n_trades,
        "expectancy_r": float(result.overall.expectancy_r),
        "profit_factor": float(pf) if pf is not None else None,
        "max_drawdown_r": float(result.drawdown.depth_r),
        "time_underwater": result.drawdown.time_underwater,
        "recovery_trades": result.drawdown.recovery_trades,
        "win_rate": float(result.overall.win_rate),
        "sharpe": result.ratios.sharpe,
        "sortino": result.ratios.sortino,
        "regime_concentration": {
            "dominant_regime": conc.dominant_regime,
            "share": conc.share,
            "concentrated": conc.concentrated,
        },
        "per_regime": {
            regime: {"n_trades": rm.n_trades, "expectancy_r": float(rm.expectancy_r)}
            for regime, rm in result.overall.per_regime.items()
        },
        "nav_index": float(result.ending_equity / result.start_equity * 100)
        if result.start_equity > 0
        else 0.0,
        "windows": [_window_to_dict(w) for w in result.windows],
    }


def _report_to_dict(report: WalkForwardReport) -> dict[str, object]:
    return {
        "config": {
            "mode": report.config.mode,
            "train_span_days": report.config.train_span_days,
            "test_span_days": report.config.test_span_days,
            "step_days": report.config.step_days,
            "n_windows": len(report.windows),
        },
        "combined": _result_to_dict(report.combined),
        "per_strategy": {sid: _result_to_dict(res) for sid, res in report.per_strategy.items()},
        "note": (
            "Harness demonstration on the local engine/Parquet snapshot. The §8 exit-criteria "
            "magnitudes (positive expectancy after costs, drawdown within budget, regime "
            "stability) are data-gated on the 5-year TFEX backfill + engine TFEX data."
        ),
    }


def _ml_factory(model_dir: Path) -> MLFilterFactory | None:
    """Bind a pre-loaded ML bundle into a per-window filter factory, or ``None`` when disabled."""
    settings = get_settings()
    cfg = settings.ml_filter_config()
    if not cfg.enabled:
        return None
    bundle = load_bundle(model_dir)
    if bundle is None:
        logger.warning("ML filter enabled but no bundle at %s; running without it", model_dir)
        return None

    def factory(
        _train_inputs: pl.DataFrame, _train_raw: pl.DataFrame, _sid: StrategyId
    ) -> SignalFilter:
        def fitted(signals: list[SetupSignal], frame: pl.DataFrame) -> list[SetupSignal]:
            return filter_signals(signals, frame, config=cfg, bundle=bundle)

        return fitted

    return factory


def _bind(
    detect_fn: Callable[[pl.DataFrame, SignalConfig], list[SetupSignal]], cfg: SignalConfig
) -> DetectFn:
    """Bind the signal config into a strategy's detect step (typed; no untyped lambda)."""

    def run(df: pl.DataFrame) -> list[SetupSignal]:
        return detect_fn(df, cfg)

    return run


def _backtest_risk(settings_risk: RiskConfig) -> tuple[RiskConfig, LadderEvidence]:
    """Pick a backtest deployment stage + evidence (``paper`` caps to 0 contracts).

    A backtest measures the strategy's *scaled-capacity* edge, so when the configured stage is
    ``paper`` (logic-validation only) we evaluate at ``scale`` with full evidence. The live
    capital ladder remains gated by the real (env-configured) stage — this only affects the
    historical sizing in the backtest.
    """
    evidence = LadderEvidence(
        months_live=settings_risk.scale_min_months_live,
        expectancy_stable=True,
        drawdown_within_budget=True,
    )
    if settings_risk.deployment_stage == "paper":
        return settings_risk.model_copy(update={"deployment_stage": "scale"}), evidence
    return settings_risk, evidence


def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    store = ParquetStore(settings.data_dir)
    frames = load_continuous_frames(store, with_4h=args.with_4h)

    sig_cfg = settings.signal_config()
    inputs = build_signal_inputs(
        frames,
        regime_thresholds=settings.regime_thresholds(),
        bias_config=settings.bias_config(),
        signal_config=sig_cfg,
    )
    raw_bars = build_execution_bars(frames["5m"])

    risk_config, ladder_evidence = _backtest_risk(settings.risk_config())
    report = run_walk_forward(
        inputs=inputs,
        raw_bars=raw_bars,
        detect={sid: _bind(detect, sig_cfg) for sid, detect in _DETECT.items()},
        wf_config=settings.walk_forward_config(),
        exec_config=settings.execution_config(),
        risk_config=risk_config,
        cost_model=settings.cost_model(),
        ml_filter_factory=_ml_factory(settings.ml_model_dir),
        ladder_evidence=ladder_evidence,
    )

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = _report_to_dict(report)
    (out_dir / "walk_forward.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info(
        "walk-forward demo: %d windows, combined=%s", len(report.windows), payload["combined"]
    )
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--with-4h",
        action="store_true",
        help="Include the 4H frame (mirror source only; the engine source declines 4h).",
    )
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT)
    parser.add_argument(
        "--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(level=args.log_level, format=_LOG_FORMAT)
    return _run(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
