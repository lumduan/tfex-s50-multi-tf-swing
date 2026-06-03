"""§5.5 demonstration — per-strategy backtest metrics (public-safe).

ROADMAP §5.5 asks each strategy to be backtested independently and reports expectancy / profit
factor / max drawdown / regime-stratified PnL. The real-data positive-expectancy *magnitude*
claim (the §5 exit criterion) is **data-gated** on the 5-year backfill (blocked on a TVKIT token
/ engine TFEX data) and a cost model (Phase 8) — see the plan's Design Decision D10. This script
runs the *harness* end-to-end on whatever continuous series the local store holds and writes a
**public-safe** artifact (trade counts + R-multiple metrics only, **no raw OHLCV**) to
``results/static/signals/per_strategy_metrics.json``.

Usage::

    uv run python scripts/per_strategy_backtest_demo.py
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

from tfex_s50_multi_tf_swing.backtest.models import BacktestMetrics
from tfex_s50_multi_tf_swing.backtest.per_strategy import run_per_strategy_backtest
from tfex_s50_multi_tf_swing.config.settings import get_settings
from tfex_s50_multi_tf_swing.data.models import Timeframe
from tfex_s50_multi_tf_swing.data.store import ParquetStore
from tfex_s50_multi_tf_swing.features.indicators import atr
from tfex_s50_multi_tf_swing.signals import strategy_a, strategy_b, strategy_c
from tfex_s50_multi_tf_swing.signals.inputs import build_signal_inputs
from tfex_s50_multi_tf_swing.signals.models import SetupSignal, SignalConfig, StrategyId

logger: logging.Logger = logging.getLogger(__name__)

_LOG_FORMAT: Final[str] = "%(asctime)s [%(levelname)-7s] %(name)s - %(message)s"
_DEFAULT_OUT: Final[Path] = Path("results/static/signals")
_ATR_PERIOD: Final[int] = 14

_DETECT: dict[StrategyId, Callable[[pl.DataFrame, SignalConfig], list[SetupSignal]]] = {
    "A": lambda df, cfg: strategy_a.to_signals(strategy_a.classify_frame(df, config=cfg)),
    "B": lambda df, cfg: strategy_b.to_signals(strategy_b.classify_frame(df, config=cfg)),
    "C": lambda df, cfg: strategy_c.to_signals(strategy_c.classify_frame(df, config=cfg)),
}


def _metrics_to_dict(metrics: BacktestMetrics) -> dict[str, object]:
    """Public-safe view: counts + R-multiple metrics only (never any price/OHLCV)."""
    pf = metrics.profit_factor
    return {
        "strategy_id": metrics.strategy_id,
        "n_trades": metrics.n_trades,
        "expectancy_r": float(metrics.expectancy_r),
        "profit_factor": float(pf) if pf is not None else None,
        "max_drawdown_r": float(metrics.max_drawdown_r),
        "win_rate": float(metrics.win_rate),
        "per_regime": {
            regime: {"n_trades": rm.n_trades, "expectancy_r": float(rm.expectancy_r)}
            for regime, rm in metrics.per_regime.items()
        },
    }


def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    store = ParquetStore(settings.data_dir)
    frames: dict[Timeframe, pl.DataFrame] = {
        "5m": store.read_continuous("5m"),
        "1h": store.read_continuous("1h"),
    }
    if args.with_4h:
        frames["4h"] = store.read_continuous("4h")

    sig_cfg = settings.signal_config()
    inputs = build_signal_inputs(
        frames,
        regime_thresholds=settings.regime_thresholds(),
        bias_config=settings.bias_config(),
        signal_config=sig_cfg,
    )
    bars = frames["5m"].with_columns(
        pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64),
        pl.col("close").cast(pl.Float64),
    )
    bars = bars.with_columns(atr(_ATR_PERIOD).alias("atr"))
    exec_cfg = settings.execution_config()

    summary: dict[str, object] = {}
    for sid, detect in _DETECT.items():
        metrics = run_per_strategy_backtest(
            lambda df, _detect=detect: _detect(df, sig_cfg),
            inputs,
            bars,
            strategy_id=sid,
            config=exec_cfg,
        )
        summary[sid] = _metrics_to_dict(metrics)

    summary["note"] = (
        "Harness demonstration on the local continuous store; the §5 positive-expectancy exit "
        "metric is data-gated on the 5-year backfill + a cost model (Phase 7/8)."
    )
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "per_strategy_metrics.json").write_text(json.dumps(summary, indent=2))
    logger.info("per-strategy backtest demo %s", summary)
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
