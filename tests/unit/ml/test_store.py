"""Tests for model persistence + the thread-safe cached loader."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest

from tfex_s50_multi_tf_swing.ml.errors import ModelLoadError
from tfex_s50_multi_tf_swing.ml.features import FEATURE_COLUMNS
from tfex_s50_multi_tf_swing.ml.store import (
    LightGBMModel,
    clear_bundle_cache,
    load_bundle,
    save_model,
)
from tfex_s50_multi_tf_swing.ml.training import WalkForwardConfig, fit_model

from .conftest import make_card

_K = len(FEATURE_COLUMNS)


def _model() -> LightGBMModel:
    rng = np.random.default_rng(0)
    x = rng.normal(size=(40, _K))
    y = (x[:, 0] > 0).astype(np.int_)
    return fit_model(x, y, config=WalkForwardConfig(), seed=1)


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    clear_bundle_cache()
    save_model(_model(), make_card("fake_breakout"), tmp_path)
    bundle = load_bundle(tmp_path)
    assert bundle is not None
    resolved = bundle.get("fake_breakout")
    assert resolved is not None
    model, card = resolved
    assert card.target == "fake_breakout"
    proba = model.predict_proba(np.zeros((3, _K), dtype=np.float64))
    assert proba.shape == (3,)


def test_predict_proba_empty_matrix(tmp_path: Path) -> None:
    clear_bundle_cache()
    save_model(_model(), make_card("fake_breakout"), tmp_path)
    bundle = load_bundle(tmp_path)
    assert bundle is not None
    model, _ = bundle.get("fake_breakout")  # type: ignore[misc]
    assert model.predict_proba(np.empty((0, _K), dtype=np.float64)).shape == (0,)


def test_cache_returns_same_object(tmp_path: Path) -> None:
    clear_bundle_cache()
    save_model(_model(), make_card("fake_breakout"), tmp_path)
    first = load_bundle(tmp_path)
    second = load_bundle(tmp_path)
    assert first is second
    clear_bundle_cache()
    assert load_bundle(tmp_path) is not first


def test_missing_directory_returns_none(tmp_path: Path) -> None:
    assert load_bundle(tmp_path / "nope") is None


def test_empty_directory_returns_none(tmp_path: Path) -> None:
    assert load_bundle(tmp_path) is None


def test_corrupt_model_raises(tmp_path: Path) -> None:
    clear_bundle_cache()
    (tmp_path / "fake_breakout.txt").write_text("not a booster", encoding="utf-8")
    (tmp_path / "fake_breakout.card.json").write_text(
        make_card("fake_breakout").model_dump_json(), encoding="utf-8"
    )
    with pytest.raises(ModelLoadError, match="could not parse"):
        load_bundle(tmp_path)


def test_invalid_card_raises(tmp_path: Path) -> None:
    clear_bundle_cache()
    save_model(_model(), make_card("fake_breakout"), tmp_path)
    (tmp_path / "fake_breakout.card.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(ModelLoadError, match="invalid model card"):
        load_bundle(tmp_path)


def test_feature_mismatch_raises(tmp_path: Path) -> None:
    clear_bundle_cache()
    save_model(_model(), make_card("fake_breakout"), tmp_path)
    stale = make_card("fake_breakout").model_copy(update={"feature_columns": ("only_one",)})
    (tmp_path / "fake_breakout.card.json").write_text(stale.model_dump_json(), encoding="utf-8")
    with pytest.raises(ModelLoadError, match="feature columns disagree"):
        load_bundle(tmp_path)


def test_from_string_round_trip() -> None:
    model = _model()
    restored = LightGBMModel.from_string(model.dumps())
    sample = np.zeros((2, _K), dtype=np.float64)
    assert np.allclose(restored.predict_proba(sample), model.predict_proba(sample))


def test_save_returns_paths(tmp_path: Path) -> None:
    model_path, card_path = save_model(_model(), make_card("fake_breakout"), tmp_path / "sub")
    assert model_path.is_file()
    assert card_path.name == "fake_breakout.card.json"


def test_train_window_preserved(tmp_path: Path) -> None:
    clear_bundle_cache()
    card = make_card("fake_breakout")
    save_model(_model(), card, tmp_path)
    bundle = load_bundle(tmp_path)
    assert bundle is not None
    _, loaded = bundle.get("fake_breakout")  # type: ignore[misc]
    assert loaded.train_window[1] - loaded.train_window[0] == timedelta(minutes=100)
