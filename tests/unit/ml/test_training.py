"""Tests for walk-forward training: folds, determinism, no-leakage guards, importance audit."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from tfex_s50_multi_tf_swing.ml.errors import ImportanceAuditError, LabelError
from tfex_s50_multi_tf_swing.ml.features import FEATURE_COLUMNS
from tfex_s50_multi_tf_swing.ml.training import (
    WalkForwardConfig,
    _aggregate,
    _binary_auc,
    _oos_metrics,
    audit_importance,
    fit_model,
    make_windows,
    walk_forward_train,
)

from .conftest import T0

_K = len(FEATURE_COLUMNS)


def _times(n: int) -> list[datetime]:
    return [T0 + timedelta(minutes=5 * i) for i in range(n)]


def _learnable(n: int, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """A multi-feature separable-ish dataset (no single feature dominates)."""
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, _K))
    y = (x[:, 0] + 0.4 * x[:, 3] + rng.normal(scale=0.5, size=n) > 0).astype(np.int_)
    return x, y


def test_make_windows_anchored() -> None:
    windows = make_windows(45, WalkForwardConfig(train_min_rows=20, test_span=10, step=10))
    assert windows == [(20, 30), (30, 40), (40, 45)]


def test_make_windows_empty_when_too_short() -> None:
    assert make_windows(20, WalkForwardConfig(train_min_rows=20)) == []


def test_walk_forward_trains_and_cards() -> None:
    x, y = _learnable(60)
    result = walk_forward_train(
        x, y, _times(60), target="trend_continuation", threshold=0.55, seed=1
    )
    assert result.card.target == "trend_continuation"
    assert result.card.threshold == 0.55
    assert tuple(result.card.feature_columns) == tuple(FEATURE_COLUMNS)
    assert result.card.train_window == (T0, _times(60)[-1])
    assert len(result.windows) == len(make_windows(60, WalkForwardConfig()))
    assert "oos_accuracy" in result.card.oos_metrics


def test_training_is_deterministic() -> None:
    x, y = _learnable(50)
    a = fit_model(x, y, config=WalkForwardConfig(), seed=7)
    b = fit_model(x, y, config=WalkForwardConfig(), seed=7)
    assert a.dumps() == b.dumps()


def test_length_mismatch_raises() -> None:
    x, y = _learnable(40)
    with pytest.raises(LabelError, match="equal length"):
        walk_forward_train(x, y[:-1], _times(40), target="fake_breakout", threshold=0.5)


def test_too_few_rows_raises() -> None:
    x, y = _learnable(10)
    with pytest.raises(LabelError, match="walk forward"):
        walk_forward_train(x, y, _times(10), target="fake_breakout", threshold=0.5)


def test_unsorted_times_raises() -> None:
    x, y = _learnable(40)
    times = _times(40)
    times[5], times[6] = times[6], times[5]
    with pytest.raises(LabelError, match="sorted ascending"):
        walk_forward_train(x, y, times, target="fake_breakout", threshold=0.5)


def test_importance_audit_blocks_dominating_feature() -> None:
    # Make column 0 equal the label exactly → it carries ~all the gain → audit rejects.
    rng = np.random.default_rng(3)
    n = 60
    x = rng.normal(size=(n, _K))
    y = (x[:, 0] > 0).astype(np.int_)
    x[:, 0] = y.astype(np.float64)
    with pytest.raises(ImportanceAuditError, match="leakage"):
        walk_forward_train(
            x,
            y,
            _times(n),
            target="fake_breakout",
            threshold=0.5,
            config=WalkForwardConfig(max_importance_share=0.5),
        )


def test_audit_importance_returns_shares() -> None:
    x, y = _learnable(60)
    model = fit_model(x, y, config=WalkForwardConfig(), seed=1)
    shares = audit_importance(model, max_share=0.99)
    assert set(shares) == set(FEATURE_COLUMNS)
    assert abs(sum(shares.values()) - 1.0) < 1e-6 or sum(shares.values()) == 0.0


def test_binary_auc_single_class_is_nan() -> None:
    assert np.isnan(_binary_auc(np.array([1, 1, 1]), np.array([0.1, 0.2, 0.3])))


def test_binary_auc_perfect_separation() -> None:
    auc = _binary_auc(np.array([0, 0, 1, 1]), np.array([0.1, 0.2, 0.8, 0.9]))
    assert auc == 1.0


def test_oos_metrics_empty() -> None:
    metrics = _oos_metrics(np.array([], dtype=np.int_), np.array([], dtype=np.float64))
    assert metrics["n"] == 0.0
    assert np.isnan(metrics["auc"])


def test_aggregate_omits_all_nan_metric() -> None:
    assert _aggregate([]) == {}
