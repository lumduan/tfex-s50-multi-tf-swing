"""End-to-end: detect → label → train → save → load → filter → backtest, + identity regression.

Updated for the 1H-execution migration: uses Strategy B (ORB) on the new 1H aligned frame.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

import polars as pl

from tfex_s50_multi_tf_swing.backtest.per_strategy import run_per_strategy_backtest
from tfex_s50_multi_tf_swing.ml import features as feat
from tfex_s50_multi_tf_swing.ml.filter import filter_signals
from tfex_s50_multi_tf_swing.ml.labels import label_triple_barrier
from tfex_s50_multi_tf_swing.ml.models import MLFilterConfig
from tfex_s50_multi_tf_swing.ml.store import clear_bundle_cache, load_bundle, save_model
from tfex_s50_multi_tf_swing.ml.training import walk_forward_train
from tfex_s50_multi_tf_swing.signals import strategy_b
from tfex_s50_multi_tf_swing.signals.models import SetupSignal

from .conftest import aligned_frame, b_signals, bars_frame


def _detect_b(df: pl.DataFrame) -> list[SetupSignal]:
    return strategy_b.to_signals(strategy_b.classify_frame(df))


def _train_bundle(aligned: pl.DataFrame, bars: pl.DataFrame, model_dir: Path) -> None:
    signals = b_signals(aligned)
    labels = label_triple_barrier(signals, bars).filter(pl.col("target") == "trend_continuation")
    times = labels.get_column("time").to_list()
    if len(times) <= 20:
        # Not enough signals from Strategy B in synthetic data — skip training gracefully.
        return
    matrix = feat.build_feature_frame(aligned, times)
    result = walk_forward_train(
        matrix,
        labels.get_column("label").to_numpy(),
        times,
        target="trend_continuation",
        threshold=0.5,
        seed=42,
    )
    save_model(result.model, result.card, model_dir)


def test_ml_filter_none_equals_phase5() -> None:
    aligned, bars = aligned_frame(120), bars_frame(120)
    baseline = run_per_strategy_backtest(_detect_b, aligned, bars, strategy_id="B")
    explicit_none = run_per_strategy_backtest(
        _detect_b, aligned, bars, strategy_id="B", ml_filter=None
    )
    assert explicit_none == baseline


def test_noop_gate_equals_phase5() -> None:
    aligned, bars = aligned_frame(120), bars_frame(120)
    baseline = run_per_strategy_backtest(_detect_b, aligned, bars, strategy_id="B")
    noop = run_per_strategy_backtest(
        _detect_b, aligned, bars, strategy_id="B", ml_filter=lambda s, _df: s
    )
    assert noop == baseline


def test_disabled_config_gate_equals_phase5() -> None:
    aligned, bars = aligned_frame(120), bars_frame(120)
    baseline = run_per_strategy_backtest(_detect_b, aligned, bars, strategy_id="B")
    gate = partial(filter_signals, config=MLFilterConfig(enabled=False), bundle=None)
    disabled = run_per_strategy_backtest(_detect_b, aligned, bars, strategy_id="B", ml_filter=gate)
    assert disabled == baseline


def test_end_to_end_trained_filter_can_only_reduce(tmp_path: Path) -> None:
    aligned, bars = aligned_frame(120), bars_frame(120)
    clear_bundle_cache()
    _train_bundle(aligned, bars, tmp_path)
    bundle = load_bundle(tmp_path)
    assert bundle is not None

    config = MLFilterConfig(enabled=True, model_dir=tmp_path, threshold_continuation=0.5)
    gate = partial(filter_signals, config=config, bundle=bundle)

    unfiltered = run_per_strategy_backtest(_detect_b, aligned, bars, strategy_id="B")
    filtered = run_per_strategy_backtest(_detect_b, aligned, bars, strategy_id="B", ml_filter=gate)
    assert filtered.n_trades <= unfiltered.n_trades


def test_end_to_end_filter_keeps_subset(tmp_path: Path) -> None:
    aligned, bars = aligned_frame(120), bars_frame(120)
    clear_bundle_cache()
    _train_bundle(aligned, bars, tmp_path)
    bundle = load_bundle(tmp_path)
    config = MLFilterConfig(enabled=True, model_dir=tmp_path)
    raw = _detect_b(aligned)
    kept = filter_signals(raw, aligned, config=config, bundle=bundle)
    assert set(id(s) for s in kept) <= set(id(s) for s in raw)
