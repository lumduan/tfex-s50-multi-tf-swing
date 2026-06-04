"""The probability filter itself (ROADMAP §6.3).

:func:`filter_signals` gates already-fired rule-based setups with the per-target models:
``P(trend_continuation)`` keeps Strategies A & B when *high*, ``P(fake_breakout)`` keeps
Strategy C when *low*. It returns a **subset of the same** :class:`SetupSignal` instances,
in their original order — never mutating, re-sorting, or rebuilding a signal.

It is the **identity function** (returns its input unchanged) whenever it cannot or must not
score:

* the filter is disabled (``config.enabled`` is ``False``),
* no model bundle is loaded (``bundle`` is ``None`` / empty),
* a strategy's per-target model is absent, or
* the aligned frame has no row for a signal's trigger time.

This guarantees Phase-5 behaviour is reproduced byte-for-byte in the default configuration.
Inference is synchronous and CPU-bound; a future live/async caller must invoke this via
``asyncio.to_thread`` so it never blocks the event loop (no async path exists in Phase 6).
"""

from __future__ import annotations

import logging

import polars as pl

from tfex_s50_multi_tf_swing.ml.features import build_matrix, build_row_index
from tfex_s50_multi_tf_swing.ml.models import (
    MLFilterConfig,
    ModelBundle,
    ModelTarget,
    target_for_strategy,
)
from tfex_s50_multi_tf_swing.signals.models import SetupSignal

logger = logging.getLogger(__name__)


def _keeps(target: ModelTarget, probability: float, threshold: float) -> bool:
    """Per-target gate: continuation keeps high probabilities, fake-breakout keeps low ones."""
    if target == "trend_continuation":
        return probability >= threshold
    return probability <= threshold


def filter_signals(
    signals: list[SetupSignal],
    inputs: pl.DataFrame,
    *,
    config: MLFilterConfig,
    bundle: ModelBundle | None,
) -> list[SetupSignal]:
    """Gate ``signals`` with the loaded models; return the surviving subset (same instances)."""
    if not config.enabled or bundle is None or bundle.is_empty():
        logger.debug("ml filter disabled or no model loaded; passing %d signals", len(signals))
        return list(signals)
    if not signals:
        return []

    index = build_row_index(inputs)

    # Bucket the indices that can actually be scored by their per-target model; everything
    # else is kept untouched (degrade). ``keep`` defaults True so unscored signals survive.
    keep = [True] * len(signals)
    scored_rows: dict[ModelTarget, list[dict[str, object]]] = {}
    scored_positions: dict[ModelTarget, list[int]] = {}

    for position, signal in enumerate(signals):
        target = target_for_strategy(signal.strategy_id)
        if bundle.get(target) is None:
            continue
        row = index.get(signal.time)
        if row is None:
            logger.warning(
                "ml filter: no aligned-frame row for %s setup at %s; keeping signal",
                signal.strategy_id,
                signal.time,
            )
            continue
        scored_rows.setdefault(target, []).append(row)
        scored_positions.setdefault(target, []).append(position)

    for target, positions in scored_positions.items():
        resolved = bundle.get(target)
        if resolved is None:  # pragma: no cover — positions only populated when get() is truthy
            continue
        model, _card = resolved
        threshold = config.threshold_for(target)
        matrix = build_matrix(scored_rows[target])
        probabilities = model.predict_proba(matrix)
        rejected = 0
        for position, probability in zip(positions, probabilities.tolist(), strict=True):
            if not _keeps(target, float(probability), threshold):
                keep[position] = False
                rejected += 1
                logger.debug(
                    "ml filter reject %s at %s: P(%s)=%.3f vs τ=%.3f",
                    signals[position].strategy_id,
                    signals[position].time,
                    target,
                    probability,
                    threshold,
                )
        logger.info(
            "ml filter target=%s scored=%d kept=%d rejected=%d",
            target,
            len(positions),
            len(positions) - rejected,
            rejected,
        )

    return [signal for position, signal in enumerate(signals) if keep[position]]


__all__: list[str] = ["filter_signals"]
