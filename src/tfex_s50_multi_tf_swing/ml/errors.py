"""ML-filter exception hierarchy (Phase 6).

Every ML error inherits from :class:`TfexS50Error` (the shared package root) so a caller
can catch the base when it needs to. Use the most specific subclass at the raise site.

The filter's *runtime* degrade paths (disabled, no model, a feature row missing for a
signal time) are **not** errors — they pass signals through unchanged. These exceptions
are reserved for genuine misconfiguration / corruption (an absent feature *column*, a
malformed label request, an unparseable model artifact).
"""

from __future__ import annotations

from tfex_s50_multi_tf_swing.adapters.errors import TfexS50Error


class MLFilterError(TfexS50Error):
    """Root exception for the ``ml`` (probability-filter) layer."""


class ModelLoadError(MLFilterError):
    """Raised when a model artifact is present but cannot be parsed / validated.

    A *missing* model directory is not an error — it degrades to a no-op filter (see
    :func:`tfex_s50_multi_tf_swing.ml.store.load_bundle`). This is raised only when an
    artifact exists but is corrupt, or its model card disagrees with the booster.
    """


class FeatureExtractionError(MLFilterError):
    """Raised when the aligned frame lacks a column the feature vector requires.

    Distinct from the runtime degrade where a *row* is missing for a signal's time
    (that keeps the signal); this is a fail-loud configuration error — the frame is the
    wrong shape entirely.
    """


class LabelError(MLFilterError):
    """Raised when a triple-barrier label request is malformed (bad bars / config)."""


class ImportanceAuditError(MLFilterError):
    """Raised when a trained model's feature importance is too concentrated.

    A single feature carrying most of the gain is the classic symptom of leakage; the
    walk-forward trainer refuses to emit such a model (ROADMAP §6.2 "no single feature
    dominating").
    """


__all__: list[str] = [
    "FeatureExtractionError",
    "ImportanceAuditError",
    "LabelError",
    "MLFilterError",
    "ModelLoadError",
]
