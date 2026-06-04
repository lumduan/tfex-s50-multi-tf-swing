"""ML probability-filter layer (ROADMAP §6).

ML is a **filter**, never a strategy (TFEX hard rule #7): the models gate already-fired
rule-based setups, they do not generate trades. Public surface:

* :func:`~tfex_s50_multi_tf_swing.ml.filter.filter_signals` — the gate (default-off / degrade
  paths are the identity function).
* :class:`~tfex_s50_multi_tf_swing.ml.models.MLFilterConfig` / ``ModelBundle`` / ``ModelCard``
  — the runtime contracts.
* :func:`~tfex_s50_multi_tf_swing.ml.store.load_bundle` — the cached, thread-safe loader.
* :func:`~tfex_s50_multi_tf_swing.ml.labels.label_triple_barrier` and
  :func:`~tfex_s50_multi_tf_swing.ml.training.walk_forward_train` — the (owner-side) training
  pipeline.

LightGBM is imported lazily, so importing this package is cheap.
"""

from __future__ import annotations

from tfex_s50_multi_tf_swing.ml.features import FEATURE_COLUMNS
from tfex_s50_multi_tf_swing.ml.filter import filter_signals
from tfex_s50_multi_tf_swing.ml.labels import label_triple_barrier
from tfex_s50_multi_tf_swing.ml.models import (
    MLFilterConfig,
    ModelBundle,
    ModelCard,
    ModelTarget,
    TripleBarrierConfig,
    target_for_strategy,
)
from tfex_s50_multi_tf_swing.ml.store import load_bundle, save_model
from tfex_s50_multi_tf_swing.ml.training import WalkForwardConfig, walk_forward_train

__all__: list[str] = [
    "FEATURE_COLUMNS",
    "MLFilterConfig",
    "ModelBundle",
    "ModelCard",
    "ModelTarget",
    "TripleBarrierConfig",
    "WalkForwardConfig",
    "filter_signals",
    "label_triple_barrier",
    "load_bundle",
    "save_model",
    "target_for_strategy",
    "walk_forward_train",
]
