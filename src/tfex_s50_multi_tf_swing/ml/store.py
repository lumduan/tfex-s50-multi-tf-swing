"""Model artifact persistence + a thread-safe cached loader (ROADMAP §6.2).

A trained model ships as two files per target under the (gitignored) model directory:

* ``{target}.txt`` — the LightGBM booster, dumped via ``model_to_string`` (text, no pickle,
  no embedded credentials);
* ``{target}.card.json`` — the :class:`~tfex_s50_multi_tf_swing.ml.models.ModelCard`
  provenance + decision threshold.

:func:`load_bundle` reads whatever targets are present and returns a
:class:`~tfex_s50_multi_tf_swing.ml.models.ModelBundle`, or ``None`` when the directory is
absent / empty (the filter then degrades to a no-op). It is **lock-guarded and cached by
(path, file-mtimes)** so the booster is parsed once, not per call; a corrupt or
card-mismatched artifact raises :class:`ModelLoadError`.

LightGBM is imported **lazily** (only when a model is actually loaded / scored), so importing
this module — or the rest of the strategy — never pays the LightGBM import cost.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt

from tfex_s50_multi_tf_swing.ml.errors import ModelLoadError
from tfex_s50_multi_tf_swing.ml.features import FEATURE_COLUMNS
from tfex_s50_multi_tf_swing.ml.models import (
    MODEL_TARGETS,
    ModelBundle,
    ModelCard,
    ModelTarget,
)

if TYPE_CHECKING:
    import lightgbm as lgb


class LightGBMModel:
    """A :class:`~tfex_s50_multi_tf_swing.ml.models.ProbabilityModel` backed by a booster.

    Wraps a trained ``lightgbm.Booster`` so the rest of the layer depends only on the
    structural ``predict_proba`` protocol, never on LightGBM directly.
    """

    def __init__(self, booster: lgb.Booster) -> None:
        self._booster = booster

    def predict_proba(self, matrix: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """Probability of the positive class for each row (1-D, length ``matrix.shape[0]``)."""
        if matrix.shape[0] == 0:
            return np.empty((0,), dtype=np.float64)
        pred = self._booster.predict(matrix)
        return np.asarray(pred, dtype=np.float64).reshape(-1)

    def feature_importance_gain(self) -> list[float]:
        """Per-feature total gain (same order as the training matrix columns)."""
        return [float(x) for x in self._booster.feature_importance(importance_type="gain")]

    def dumps(self) -> str:
        """Serialise the booster to LightGBM's text format."""
        return str(self._booster.model_to_string())

    @classmethod
    def from_string(cls, text: str) -> LightGBMModel:
        """Reconstruct a model from a ``model_to_string`` dump."""
        import lightgbm as lgb

        try:
            booster = lgb.Booster(model_str=text)
        except Exception as exc:  # noqa: BLE001 — surface any LightGBM parse failure uniformly
            raise ModelLoadError(f"could not parse LightGBM booster: {exc}") from exc
        return cls(booster)


def save_model(model: LightGBMModel, card: ModelCard, model_dir: Path) -> tuple[Path, Path]:
    """Write ``{target}.txt`` + ``{target}.card.json`` for one target; return both paths."""
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / f"{card.target}.txt"
    card_path = model_dir / f"{card.target}.card.json"
    model_path.write_text(model.dumps(), encoding="utf-8")
    card_path.write_text(card.model_dump_json(indent=2), encoding="utf-8")
    return model_path, card_path


# (resolved-dir, ((filename, mtime_ns), ...)) → bundle. Guarded by ``_LOCK``.
_CACHE: dict[tuple[str, tuple[tuple[str, int], ...]], ModelBundle] = {}
_LOCK = threading.Lock()


def _artifact_paths(model_dir: Path) -> dict[ModelTarget, tuple[Path, Path]]:
    """Map each target with *both* files present to its ``(model_path, card_path)``."""
    found: dict[ModelTarget, tuple[Path, Path]] = {}
    for target in MODEL_TARGETS:
        model_path = model_dir / f"{target}.txt"
        card_path = model_dir / f"{target}.card.json"
        if model_path.is_file() and card_path.is_file():
            found[target] = (model_path, card_path)
    return found


def _cache_key(
    model_dir: Path, paths: dict[ModelTarget, tuple[Path, Path]]
) -> tuple[str, tuple[tuple[str, int], ...]]:
    files: list[tuple[str, int]] = []
    for model_path, card_path in paths.values():
        for p in (model_path, card_path):
            files.append((p.name, p.stat().st_mtime_ns))
    return str(model_dir.resolve()), tuple(sorted(files))


def _load_card(card_path: Path) -> ModelCard:
    try:
        card = ModelCard.model_validate_json(card_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — any malformed card is a load failure
        raise ModelLoadError(f"invalid model card {card_path.name}: {exc}") from exc
    if tuple(card.feature_columns) != tuple(FEATURE_COLUMNS):
        raise ModelLoadError(
            f"model card {card_path.name} feature columns disagree with the current "
            "FEATURE_COLUMNS (model is stale — retrain)"
        )
    return card


def load_bundle(model_dir: Path) -> ModelBundle | None:
    """Load the per-target models + cards from ``model_dir``; ``None`` if none present.

    A missing directory or no artifacts → ``None`` (the filter degrades to a no-op). A
    present-but-corrupt artifact, or a card whose ``feature_columns`` no longer match the
    code, raises :class:`ModelLoadError`. The result is cached by (path, file mtimes).
    """
    if not model_dir.is_dir():
        return None
    paths = _artifact_paths(model_dir)
    if not paths:
        return None

    key = _cache_key(model_dir, paths)
    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            return cached
        models: dict[ModelTarget, LightGBMModel] = {}
        cards: dict[ModelTarget, ModelCard] = {}
        for target, (model_path, card_path) in paths.items():
            cards[target] = _load_card(card_path)
            models[target] = LightGBMModel.from_string(model_path.read_text(encoding="utf-8"))
        bundle = ModelBundle(models=models, cards=cards)
        _CACHE[key] = bundle
        return bundle


def clear_bundle_cache() -> None:
    """Drop the in-process bundle cache (call from tests after rewriting artifacts)."""
    with _LOCK:
        _CACHE.clear()


__all__: list[str] = [
    "LightGBMModel",
    "clear_bundle_cache",
    "load_bundle",
    "save_model",
]
