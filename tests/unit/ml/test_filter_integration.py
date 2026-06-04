"""End-to-end: detect → label → train → save → load → filter → backtest, + identity regression."""

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
from tfex_s50_multi_tf_swing.signals import strategy_c
from tfex_s50_multi_tf_swing.signals.models import SetupSignal

from .conftest import aligned_frame, bars_frame, c_signals


def _detect_c(df: pl.DataFrame) -> list[SetupSignal]:
    return strategy_c.to_signals(strategy_c.classify_frame(df))


def _train_bundle(aligned: pl.DataFrame, bars: pl.DataFrame, model_dir: Path) -> None:
    signals = c_signals(aligned)
    labels = label_triple_barrier(signals, bars).filter(pl.col("target") == "fake_breakout")
    times = labels.get_column("time").to_list()
    matrix = feat.build_feature_frame(aligned, times)
    result = walk_forward_train(
        matrix,
        labels.get_column("label").to_numpy(),
        times,
        target="fake_breakout",
        threshold=0.5,
        seed=42,
    )
    save_model(result.model, result.card, model_dir)


def test_ml_filter_none_equals_phase5() -> None:
    aligned, bars = aligned_frame(120), bars_frame(120)
    baseline = run_per_strategy_backtest(_detect_c, aligned, bars, strategy_id="C")
    explicit_none = run_per_strategy_backtest(
        _detect_c, aligned, bars, strategy_id="C", ml_filter=None
    )
    assert explicit_none == baseline


def test_noop_gate_equals_phase5() -> None:
    aligned, bars = aligned_frame(120), bars_frame(120)
    baseline = run_per_strategy_backtest(_detect_c, aligned, bars, strategy_id="C")
    noop = run_per_strategy_backtest(
        _detect_c, aligned, bars, strategy_id="C", ml_filter=lambda s, _df: s
    )
    assert noop == baseline


def test_disabled_config_gate_equals_phase5() -> None:
    aligned, bars = aligned_frame(120), bars_frame(120)
    baseline = run_per_strategy_backtest(_detect_c, aligned, bars, strategy_id="C")
    gate = partial(filter_signals, config=MLFilterConfig(enabled=False), bundle=None)
    disabled = run_per_strategy_backtest(_detect_c, aligned, bars, strategy_id="C", ml_filter=gate)
    assert disabled == baseline


def test_end_to_end_trained_filter_can_only_reduce(tmp_path: Path) -> None:
    aligned, bars = aligned_frame(120), bars_frame(120)
    clear_bundle_cache()
    _train_bundle(aligned, bars, tmp_path)
    bundle = load_bundle(tmp_path)
    assert bundle is not None

    config = MLFilterConfig(enabled=True, model_dir=tmp_path, threshold_fake_breakout=0.5)
    gate = partial(filter_signals, config=config, bundle=bundle)

    unfiltered = run_per_strategy_backtest(_detect_c, aligned, bars, strategy_id="C")
    filtered = run_per_strategy_backtest(_detect_c, aligned, bars, strategy_id="C", ml_filter=gate)
    assert filtered.n_trades <= unfiltered.n_trades


def test_end_to_end_filter_keeps_subset(tmp_path: Path) -> None:
    aligned, bars = aligned_frame(120), bars_frame(120)
    clear_bundle_cache()
    _train_bundle(aligned, bars, tmp_path)
    bundle = load_bundle(tmp_path)
    config = MLFilterConfig(enabled=True, model_dir=tmp_path)
    raw = _detect_c(aligned)
    kept = filter_signals(raw, aligned, config=config, bundle=bundle)
    assert set(id(s) for s in kept) <= set(id(s) for s in raw)
