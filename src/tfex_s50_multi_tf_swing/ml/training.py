"""Walk-forward LightGBM training for the probability filter (ROADMAP §6.2 / §6.4).

Training is **anchored walk-forward only** — never a random split (TFEX hard rule #6).
Windows expand the train set from the start of history and test on the next out-of-sample
block; a test asserts every train fold strictly precedes its test fold in time, so no future
information leaks. The shipped model is then re-fit on the full history and gated by a
**feature-importance audit** (no single feature may carry more than a configured share of
total gain — the classic leakage smell).

LightGBM is imported lazily inside :func:`fit_model`; importing this module is cheap. Fits
are deterministic (``deterministic=True`` + single-thread + fixed ``seed``) so two runs
produce an identical booster — the basis of the reproducibility test.

Metrics are computed with NumPy only (no scikit-learn dependency): out-of-sample AUC
(tie-aware), accuracy at 0.5, the positive rate, and the row count.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, Field

from tfex_s50_multi_tf_swing.ml.errors import ImportanceAuditError, LabelError
from tfex_s50_multi_tf_swing.ml.features import FEATURE_COLUMNS
from tfex_s50_multi_tf_swing.ml.models import ModelCard, ModelTarget
from tfex_s50_multi_tf_swing.ml.store import LightGBMModel


class WalkForwardConfig(BaseModel):
    """Walk-forward + LightGBM hyper-parameters (bounded; defaults suit small TFEX data)."""

    model_config = ConfigDict(frozen=True)

    train_min_rows: int = Field(default=20, ge=2)
    test_span: int = Field(default=10, ge=1)
    step: int = Field(default=10, ge=1)
    num_boost_round: int = Field(default=50, ge=1)
    num_leaves: int = Field(default=15, ge=2)
    learning_rate: float = Field(default=0.05, gt=0.0, le=1.0)
    min_data_in_leaf: int = Field(default=1, ge=1)
    max_importance_share: float = Field(default=0.95, gt=0.0, le=1.0)


@dataclass(frozen=True)
class WalkForwardWindow:
    """One anchored fold: train ``[0, train_end)``, test ``[train_end, test_end)`` + metrics."""

    train_end: int
    test_end: int
    metrics: dict[str, float]


@dataclass(frozen=True)
class WalkForwardResult:
    """The shipped model + card, the per-window OOS metrics, and the importance audit."""

    model: LightGBMModel
    card: ModelCard
    windows: list[WalkForwardWindow]
    importances: dict[str, float]


def fit_model(
    features: npt.NDArray[np.float64],
    labels: npt.NDArray[np.int_],
    *,
    config: WalkForwardConfig,
    seed: int,
) -> LightGBMModel:
    """Fit one deterministic LightGBM binary classifier on the given rows."""
    import lightgbm as lgb

    dataset = lgb.Dataset(
        features,
        label=labels,
        params={"min_data_in_bin": 1, "feature_pre_filter": False, "verbose": -1},
        free_raw_data=False,
    )
    params: dict[str, object] = {
        "objective": "binary",
        "num_leaves": config.num_leaves,
        "learning_rate": config.learning_rate,
        "min_data_in_leaf": config.min_data_in_leaf,
        "min_sum_hessian_in_leaf": 1e-3,
        "feature_pre_filter": False,
        "deterministic": True,
        "force_row_wise": True,
        "num_threads": 1,
        "seed": seed,
        "bagging_seed": seed,
        "feature_fraction_seed": seed,
        "verbosity": -1,
    }
    booster = lgb.train(params, dataset, num_boost_round=config.num_boost_round)
    return LightGBMModel(booster)


def _rank_avg(scores: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Average (tie-aware) ranks, 1-based, for an AUC computation."""
    order = np.argsort(scores, kind="mergesort")
    ordered = scores[order]
    ranks = np.empty(len(scores), dtype=np.float64)
    pos = 0
    n = len(scores)
    while pos < n:
        end = pos
        while end + 1 < n and ordered[end + 1] == ordered[pos]:
            end += 1
        ranks[order[pos : end + 1]] = (pos + end) / 2.0 + 1.0
        pos = end + 1
    return ranks


def _binary_auc(y_true: npt.NDArray[np.int_], y_score: npt.NDArray[np.float64]) -> float:
    """ROC AUC via the Mann–Whitney statistic; ``nan`` when a class is absent."""
    positives = int(np.count_nonzero(y_true == 1))
    negatives = int(len(y_true) - positives)
    if positives == 0 or negatives == 0:
        return float("nan")
    ranks = _rank_avg(y_score)
    rank_sum = float(ranks[y_true == 1].sum())
    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def _oos_metrics(
    y_true: npt.NDArray[np.int_], y_score: npt.NDArray[np.float64]
) -> dict[str, float]:
    """Out-of-sample metrics for one fold."""
    if len(y_true) == 0:
        return {"n": 0.0, "pos_rate": float("nan"), "accuracy": float("nan"), "auc": float("nan")}
    predicted = (y_score >= 0.5).astype(np.int_)
    return {
        "n": float(len(y_true)),
        "pos_rate": float(np.mean(y_true)),
        "accuracy": float(np.mean(predicted == y_true)),
        "auc": _binary_auc(y_true, y_score),
    }


def make_windows(n_rows: int, config: WalkForwardConfig) -> list[tuple[int, int]]:
    """Anchored walk-forward folds as ``(train_end, test_end)`` index pairs."""
    windows: list[tuple[int, int]] = []
    train_end = config.train_min_rows
    while train_end < n_rows:
        test_end = min(train_end + config.test_span, n_rows)
        if test_end <= train_end:  # pragma: no cover — defensive; test_span≥1 keeps it larger
            break
        windows.append((train_end, test_end))
        train_end += config.step
    return windows


def audit_importance(model: LightGBMModel, *, max_share: float) -> dict[str, float]:
    """Per-feature gain share; raise :class:`ImportanceAuditError` if one feature dominates."""
    gains = model.feature_importance_gain()
    total = sum(gains)
    shares = {
        col: (g / total if total > 0 else 0.0)
        for col, g in zip(FEATURE_COLUMNS, gains, strict=True)
    }
    top_feature, top_share = max(shares.items(), key=lambda kv: kv[1])
    if total > 0 and top_share > max_share:
        raise ImportanceAuditError(
            f"feature {top_feature!r} carries {top_share:.0%} of gain "
            f"(> {max_share:.0%} cap) — likely leakage; refusing to ship the model"
        )
    return shares


def walk_forward_train(
    features: npt.NDArray[np.float64],
    labels: npt.NDArray[np.int_],
    times: Sequence[datetime],
    *,
    target: ModelTarget,
    threshold: float,
    config: WalkForwardConfig | None = None,
    seed: int = 42,
    git_sha: str = "",
) -> WalkForwardResult:
    """Walk-forward train ``target``, audit importance, and assemble the shipped model + card."""
    config = config or WalkForwardConfig()
    if features.shape[0] != len(labels) or features.shape[0] != len(times):
        raise LabelError("features, labels, and times must have equal length")
    if features.shape[0] < config.train_min_rows + 1:
        raise LabelError(
            f"need > {config.train_min_rows} rows to walk forward, got {features.shape[0]}"
        )
    if any(times[i] > times[i + 1] for i in range(len(times) - 1)):
        raise LabelError("times must be sorted ascending (walk-forward needs time order)")

    windows: list[WalkForwardWindow] = []
    for train_end, test_end in make_windows(features.shape[0], config):
        fold_model = fit_model(features[:train_end], labels[:train_end], config=config, seed=seed)
        scores = fold_model.predict_proba(features[train_end:test_end])
        metrics = _oos_metrics(labels[train_end:test_end], scores)
        windows.append(WalkForwardWindow(train_end=train_end, test_end=test_end, metrics=metrics))

    final = fit_model(features, labels, config=config, seed=seed)
    importances = audit_importance(final, max_share=config.max_importance_share)
    card = ModelCard(
        target=target,
        feature_columns=tuple(FEATURE_COLUMNS),
        threshold=threshold,
        train_window=(times[0], times[-1]),
        oos_metrics=_aggregate(windows),
        seed=seed,
        git_sha=git_sha,
    )
    return WalkForwardResult(model=final, card=card, windows=windows, importances=importances)


def _aggregate(windows: Sequence[WalkForwardWindow]) -> dict[str, float]:
    """Mean of each OOS metric across folds, ignoring NaNs.

    A metric that is undefined on every fold (e.g. AUC when each test block is single-class)
    is **omitted** rather than stored as NaN, so the model card stays finite and JSON-safe.
    """
    if not windows:
        return {}
    keys = windows[0].metrics.keys()
    out: dict[str, float] = {}
    for key in keys:
        values = [w.metrics[key] for w in windows if not np.isnan(w.metrics[key])]
        if values:
            out[f"oos_{key}"] = float(np.mean(values))
    return out


__all__: list[str] = [
    "WalkForwardConfig",
    "WalkForwardResult",
    "WalkForwardWindow",
    "audit_importance",
    "fit_model",
    "make_windows",
    "walk_forward_train",
]
