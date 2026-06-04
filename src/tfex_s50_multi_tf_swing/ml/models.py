"""Type contracts for the ML probability-filter layer (ROADMAP §6).

* :data:`ModelTarget` — the two probabilities the layer predicts: ``trend_continuation``
  (gates Strategies A & B) and ``fake_breakout`` (gates Strategy C).
* :class:`MLFilterConfig` — the runtime knobs: the master ``enabled`` toggle (default
  **off**), the per-target decision thresholds, the model directory, and the determinism
  seed. Frozen + bounded so an out-of-range env override fails loud at load time (mirrors
  :class:`~tfex_s50_multi_tf_swing.signals.models.SignalConfig`).
* :class:`TripleBarrierConfig` — the TP / SL / time barriers the labeller uses.
* :class:`ModelCard` — the provenance + decision threshold that ships *with* a model so a
  booster and the threshold it was validated at travel together. Carries **no secrets**.
* :class:`ProbabilityModel` — the structural type a scorer satisfies (a real LightGBM
  booster wrapper or a test stub): ``predict_proba(matrix) -> probabilities``.
* :class:`ModelBundle` — the loaded per-target models + cards the filter scores against.

All ML quantities are :class:`float` — internal statistics that never cross the gateway
boundary, so the Decimal-for-money rule does not apply (only :class:`SetupSignal` prices
are Decimal, and the filter never touches them).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, get_args, runtime_checkable

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, Field, field_validator

from tfex_s50_multi_tf_swing.signals.models import StrategyId

ModelTarget = Literal["trend_continuation", "fake_breakout"]
"""The two probabilities the filter scores: A/B continuation, C fake-breakout."""

MODEL_TARGETS: tuple[ModelTarget, ...] = get_args(ModelTarget)
"""Tuple of every :data:`ModelTarget`, for iteration / parametrised tests."""

# Which probability gates which strategy (ROADMAP §6.2). A/B share the continuation
# model; C uses the fake-breakout model.
_STRATEGY_TARGET: dict[StrategyId, ModelTarget] = {
    "A": "trend_continuation",
    "B": "trend_continuation",
    "C": "fake_breakout",
}


def target_for_strategy(strategy_id: StrategyId) -> ModelTarget:
    """Return the :data:`ModelTarget` whose probability gates ``strategy_id``."""
    return _STRATEGY_TARGET[strategy_id]


class MLFilterConfig(BaseModel):
    """Runtime configuration for the probability filter.

    ``enabled`` defaults to **False** so an unset environment is a no-op and Phase-5
    behaviour is reproduced byte-for-byte. Thresholds are bounded to ``[0, 1]``; an
    out-of-range env override fails at load time. ``model_dir`` points at the (gitignored)
    artifact directory; a missing directory degrades the filter to a no-op rather than
    raising.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    model_dir: Path = Path("./data/models")
    threshold_continuation: float = Field(default=0.55, ge=0.0, le=1.0)
    threshold_fake_breakout: float = Field(default=0.50, ge=0.0, le=1.0)
    seed: int = Field(default=42, ge=0)

    def threshold_for(self, target: ModelTarget) -> float:
        """Decision threshold for ``target``."""
        if target == "trend_continuation":
            return self.threshold_continuation
        return self.threshold_fake_breakout


class TripleBarrierConfig(BaseModel):
    """TP / SL / time barriers for triple-barrier labelling (ROADMAP §6.1).

    Barriers are ATR-scaled from the signal's entry, mirroring the execution engine's
    risk geometry. ``horizon_bars`` is the time barrier (5m bars) after which an unresolved
    trade is labelled by the sign of its return.
    """

    model_config = ConfigDict(frozen=True)

    tp_atr_mult: float = Field(default=1.0, gt=0.0)
    sl_atr_mult: float = Field(default=1.0, gt=0.0)
    horizon_bars: int = Field(default=24, ge=1)


class ModelCard(BaseModel):
    """Provenance + decision threshold that ships alongside a trained model.

    Records *what* the model is and *how* it was validated — never a secret. Serialised to
    ``{target}.card.json`` next to the booster so the threshold a model was validated at
    cannot drift from the model itself.
    """

    model_config = ConfigDict(frozen=True)

    target: ModelTarget
    feature_columns: tuple[str, ...]
    threshold: float = Field(ge=0.0, le=1.0)
    train_window: tuple[datetime, datetime]
    oos_metrics: dict[str, float] = Field(default_factory=dict)
    seed: int = Field(ge=0)
    git_sha: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("created_at", "train_window")
    @classmethod
    def _require_utc(cls, value: datetime | tuple[datetime, datetime]) -> object:
        """Reject tz-naive / non-UTC timestamps (store-UTC rule)."""
        values = value if isinstance(value, tuple) else (value,)
        for item in values:
            if item.tzinfo is None or item.utcoffset() != UTC.utcoffset(None):
                raise ValueError("model-card timestamps must be UTC-aware")
        return value


@runtime_checkable
class ProbabilityModel(Protocol):
    """Structural type for a probability scorer (LightGBM wrapper or test stub).

    Implementations return the probability of the positive class for each row of the
    feature matrix, as a 1-D float array of length ``matrix.shape[0]`` with values in
    ``[0, 1]``.
    """

    def predict_proba(self, matrix: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:  # noqa: D102
        ...


@dataclass(frozen=True)
class ModelBundle:
    """The loaded per-target models + cards the filter scores against.

    A target may be absent (only one model trained / shipped); the filter degrades to a
    passthrough for any strategy whose target is missing.
    """

    models: Mapping[ModelTarget, ProbabilityModel]
    cards: Mapping[ModelTarget, ModelCard]

    def get(self, target: ModelTarget) -> tuple[ProbabilityModel, ModelCard] | None:
        """Return the ``(model, card)`` for ``target`` if both are present, else ``None``."""
        model = self.models.get(target)
        card = self.cards.get(target)
        if model is None or card is None:
            return None
        return model, card

    def is_empty(self) -> bool:
        """True when no usable per-target model is loaded."""
        return all(self.get(t) is None for t in MODEL_TARGETS)


__all__: list[str] = [
    "MODEL_TARGETS",
    "MLFilterConfig",
    "ModelBundle",
    "ModelCard",
    "ModelTarget",
    "ProbabilityModel",
    "TripleBarrierConfig",
    "target_for_strategy",
]
