"""Tests for the gate: default-off / degrade identity, per-target thresholds, order, selection."""

from __future__ import annotations

import logging

import numpy as np
import numpy.typing as npt
import pytest

from tfex_s50_multi_tf_swing.ml.filter import filter_signals
from tfex_s50_multi_tf_swing.ml.models import MLFilterConfig, ModelBundle

from .conftest import aligned_frame, make_card, make_signal, stub_bundle

_ENABLED = MLFilterConfig(enabled=True, threshold_fake_breakout=0.5, threshold_continuation=0.55)
_DISABLED = MLFilterConfig(enabled=False)


class _ListModel:
    """Stub model returning a preset probability per row (in scoring order)."""

    def __init__(self, probs: list[float]) -> None:
        self._probs = probs

    def predict_proba(self, matrix: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        assert matrix.shape[0] == len(self._probs)
        return np.asarray(self._probs, dtype=np.float64)


def test_disabled_is_identity() -> None:
    frame = aligned_frame(6)
    signals = [make_signal(minute=0), make_signal(minute=60)]
    out = filter_signals(signals, frame, config=_DISABLED, bundle=stub_bundle(0.99))
    assert out == signals
    assert out[0] is signals[0] and out[1] is signals[1]


def test_none_bundle_is_identity() -> None:
    frame = aligned_frame(6)
    signals = [make_signal(minute=0)]
    assert filter_signals(signals, frame, config=_ENABLED, bundle=None) == signals


def test_empty_bundle_is_identity() -> None:
    frame = aligned_frame(6)
    signals = [make_signal(minute=0)]
    empty = ModelBundle(models={}, cards={})
    assert filter_signals(signals, frame, config=_ENABLED, bundle=empty) == signals


def test_empty_signals_returns_empty() -> None:
    frame = aligned_frame(6)
    assert filter_signals([], frame, config=_ENABLED, bundle=stub_bundle(0.1)) == []


def test_trend_continuation_rejects_low_probability() -> None:
    frame = aligned_frame(6)
    signals = [make_signal(strategy_id="B", minute=0), make_signal(strategy_id="B", minute=60)]
    # P(continuation)=0.1 < τ=0.5 → both dropped (B maps to trend_continuation).
    out = filter_signals(
        signals,
        frame,
        config=_ENABLED,
        bundle=stub_bundle(0.1, target="trend_continuation"),
    )
    assert out == []


def test_trend_continuation_keeps_high_probability() -> None:
    frame = aligned_frame(6)
    signals = [make_signal(strategy_id="B", minute=0)]
    out = filter_signals(
        signals,
        frame,
        config=_ENABLED,
        bundle=stub_bundle(0.9, target="trend_continuation"),
    )
    assert out == signals


def test_continuation_keeps_high_probability() -> None:
    frame = aligned_frame(6)
    signals = [make_signal(strategy_id="A", minute=0)]
    bundle = stub_bundle(0.9, target="trend_continuation")
    assert filter_signals(signals, frame, config=_ENABLED, bundle=bundle) == signals


def test_continuation_rejects_low_probability() -> None:
    frame = aligned_frame(6)
    signals = [make_signal(strategy_id="A", minute=0)]
    bundle = stub_bundle(0.1, target="trend_continuation")
    assert filter_signals(signals, frame, config=_ENABLED, bundle=bundle) == []


def test_missing_model_for_target_passes_through() -> None:
    frame = aligned_frame(6)
    # Strategy-B signals but only the fake_breakout model is loaded → pass-through for B.
    signals = [make_signal(strategy_id="B", minute=0)]
    bundle = stub_bundle(0.9, target="fake_breakout")
    assert filter_signals(signals, frame, config=_ENABLED, bundle=bundle) == signals


def test_missing_row_degrades_to_keep() -> None:
    frame = aligned_frame(6)
    # minute=30 is off the 1H grid → no aligned row → keep despite a reject-prone model.
    signals = [make_signal(strategy_id="B", minute=30)]
    assert filter_signals(signals, frame, config=_ENABLED, bundle=stub_bundle(0.9)) == signals


def test_order_and_identity_preserved_on_selective_keep() -> None:
    frame = aligned_frame(12)
    signals = [
        make_signal(strategy_id="B", minute=0),
        make_signal(strategy_id="B", minute=60),
        make_signal(strategy_id="B", minute=120),
    ]
    # B maps to trend_continuation; high=keep, low=reject. [0.1, 0.9, 0.1] → keep middle.
    bundle = ModelBundle(
        models={"trend_continuation": _ListModel([0.1, 0.9, 0.1])},
        cards={"trend_continuation": make_card("trend_continuation", threshold=0.5)},
    )
    out = filter_signals(signals, frame, config=_ENABLED, bundle=bundle)
    assert out == [signals[1]]
    assert out[0] is signals[1]


def test_info_log_emitted(caplog: pytest.LogCaptureFixture) -> None:
    frame = aligned_frame(6)
    signals = [make_signal(strategy_id="B", minute=0)]
    with caplog.at_level(logging.INFO, logger="tfex_s50_multi_tf_swing.ml.filter"):
        filter_signals(
            signals,
            frame,
            config=_ENABLED,
            bundle=stub_bundle(0.9, target="trend_continuation"),
        )
    assert any("ml filter target=trend_continuation" in rec.message for rec in caplog.records)
