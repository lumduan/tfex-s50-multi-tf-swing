"""§6 demonstration — ML probability filter end-to-end (public-safe, synthetic).

ROADMAP §6 uses ML as a **filter, not a strategy**: a LightGBM model gates already-fired
rule-based setups. The real trained models and the out-of-sample A/B *magnitude* claim are
**data-gated** on the 5-year backfill (same gate as Phases 1/3/4/5). This script runs the
whole machinery — detect → triple-barrier label → walk-forward train → save → load → filter →
A/B backtest — on a **synthetic, deterministic** Strategy-C series so it is public-safe (no raw
OHLCV is fetched, stored, or emitted) and reproducible.

It writes a public-safe artifact (counts + R-multiple metrics + OOS metrics only) to
``results/static/ml/filter_demo.json``.

Usage::

    uv run python scripts/ml_filter_demo.py
"""

from __future__ import annotations

import json
import logging
import math
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Final

import polars as pl

from tfex_s50_multi_tf_swing.backtest.models import BacktestMetrics
from tfex_s50_multi_tf_swing.backtest.per_strategy import run_per_strategy_backtest
from tfex_s50_multi_tf_swing.ml import features as feat
from tfex_s50_multi_tf_swing.ml.filter import filter_signals
from tfex_s50_multi_tf_swing.ml.labels import label_triple_barrier
from tfex_s50_multi_tf_swing.ml.models import MLFilterConfig
from tfex_s50_multi_tf_swing.ml.store import clear_bundle_cache, load_bundle, save_model
from tfex_s50_multi_tf_swing.ml.training import WalkForwardConfig, walk_forward_train
from tfex_s50_multi_tf_swing.signals import strategy_c
from tfex_s50_multi_tf_swing.signals.models import SetupSignal

logger: logging.Logger = logging.getLogger(__name__)

_LOG_FORMAT: Final[str] = "%(asctime)s [%(levelname)-7s] %(name)s - %(message)s"
_OUT: Final[Path] = Path("results/static/ml")
_T0: Final[datetime] = datetime(2026, 1, 5, 3, 0, tzinfo=UTC)
_N_BARS: Final[int] = 240


def _synthetic_series() -> tuple[pl.DataFrame, pl.DataFrame]:
    """Build a deterministic Strategy-C aligned frame + matching 5m execution bars.

    The price ramps **up then down** (a triangle) while sweep setups fire in **alternating**
    directions every third bar. So a long in the up-leg or a short in the down-leg continues
    (a genuine setup), while the counter-trend half fakes out — yielding a realistic *mix* of
    triple-barrier labels for the model to separate. Fully deterministic, no real OHLCV.
    """
    half = _N_BARS // 2
    aligned: list[dict[str, object]] = []
    bars: list[dict[str, object]] = []
    for i in range(_N_BARS):
        t = _T0 + timedelta(minutes=5 * i)
        ramp = 0.6 * i if i < half else 0.6 * half - 0.6 * (i - half)
        mid = 1000.0 + ramp + 0.3 * math.sin(i / 8.0)
        is_long = i % 2 == 0
        dist = 1.0 if is_long else -1.0
        close = mid + (0.6 if is_long else -0.6)
        bars.append(
            {
                "time": t,
                "open": Decimal(f"{mid:.2f}"),
                "high": Decimal(f"{mid + 0.5:.2f}"),
                "low": Decimal(f"{mid - 0.5:.2f}"),
                "close": Decimal(f"{close:.2f}"),
                "atr": Decimal("1.0"),
            }
        )
        aligned.append(
            {
                "time": t,
                "4h_bias_direction": "neutral",
                "1h_regime": "range_high_vol",
                "1h_dist_from_vwap": dist,
                "1h_structure": None,
                "1h_atr_ratio": 1.0,
                "1h_volume_expansion": 0.0,
                "atr_ratio": 1.0,
                "bollinger_squeeze": 1.0,
                "volume_expansion": 0.6,
                "dist_from_vwap": dist,
                "structure": "HH" if is_long else "LL",
                "close": close,
                "swing_high": mid + 6.0,
                "swing_low": mid - 6.0,
                "liquidity_sweep_flag": 1 if i % 3 == 0 else 0,
                "lunch_zone_flag": 0,
            }
        )
    return pl.DataFrame(aligned), pl.DataFrame(bars)


def _detect_c(df: pl.DataFrame) -> list[SetupSignal]:
    return strategy_c.to_signals(strategy_c.classify_frame(df))


def _metrics_view(metrics: BacktestMetrics) -> dict[str, object]:
    pf = metrics.profit_factor
    return {
        "n_trades": metrics.n_trades,
        "expectancy_r": round(float(metrics.expectancy_r), 4),
        "profit_factor": round(float(pf), 4) if pf is not None else None,
        "win_rate": round(float(metrics.win_rate), 4),
    }


def main() -> int:
    """Run the demo and write the public-safe artifact; return a process exit code."""
    logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)
    aligned, bars = _synthetic_series()

    signals = _detect_c(aligned)
    logger.info("fired %d Strategy-C setups on the synthetic series", len(signals))

    label_frame = label_triple_barrier(signals, bars)
    fake = label_frame.filter(pl.col("target") == "fake_breakout")
    logger.info("labelled %d fake_breakout rows", fake.height)

    times = fake.get_column("time").to_list()
    matrix = feat.build_feature_frame(aligned, times)
    labels = fake.get_column("label").to_numpy()
    result = walk_forward_train(
        matrix,
        labels,
        times,
        target="fake_breakout",
        threshold=0.50,
        config=WalkForwardConfig(),
        seed=42,
    )
    logger.info("walk-forward OOS metrics: %s", result.card.oos_metrics)

    model_dir = Path(tempfile.mkdtemp(prefix="ml_demo_models_"))
    save_model(result.model, result.card, model_dir)
    clear_bundle_cache()
    bundle = load_bundle(model_dir)

    config = MLFilterConfig(enabled=True, model_dir=model_dir, threshold_fake_breakout=0.50)
    ml_gate = partial(filter_signals, config=config, bundle=bundle)

    unfiltered = run_per_strategy_backtest(_detect_c, aligned, bars, strategy_id="C")
    filtered = run_per_strategy_backtest(
        _detect_c, aligned, bars, strategy_id="C", ml_filter=ml_gate
    )

    artifact: dict[str, object] = {
        "target": "fake_breakout",
        "n_signals": len(signals),
        "n_labelled": fake.height,
        "threshold": 0.50,
        "oos_metrics": {k: round(v, 4) for k, v in result.card.oos_metrics.items()},
        "top_feature_importance": round(max(result.importances.values()), 4),
        "backtest_unfiltered": _metrics_view(unfiltered),
        "backtest_filtered": _metrics_view(filtered),
        "note": "synthetic, public-safe; real model + A/B magnitude are data-gated",
    }
    _OUT.mkdir(parents=True, exist_ok=True)
    out_path = _OUT / "filter_demo.json"
    out_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    logger.info(
        "ML filter demo: %d → %d trades after the filter; wrote %s",
        unfiltered.n_trades,
        filtered.n_trades,
        out_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
