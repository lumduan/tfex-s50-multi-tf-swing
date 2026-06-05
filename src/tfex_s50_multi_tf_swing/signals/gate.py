"""Entry gates for the setup layer — enabled-strategy selection + regime gating (risk mitigation).

A 14-month walk-forward exposed a 31.13R drawdown driven by the high-turnover Strategy C and by
entries taken in unfavourable regimes. This module is the single, auditable, config-driven seam that

* **selects which strategies trade** (``build_detect_map``) — the active pool is driven by
  :func:`~tfex_s50_multi_tf_swing.config.settings.Settings.enabled_strategy_ids` (default ``{"B"}``,
  ORB-only core), so disabling C or re-enabling A is a pure env change, never a code edit; and
* **gates entries by HTF regime** (:func:`apply_regime_gate`) — a fired bar is demoted to a clean
  "No Trade" whenever its **1D regime** (``1d_regime``) is outside the configured allow-set
  (:attr:`~tfex_s50_multi_tf_swing.signals.models.SignalConfig.allowed_regimes`, default
  ``{"trend_up"}``).

Strategy C is **permanently removed** from the active registry (2026-06-05, 1H-execution
migration) — the module stays importable but no code path reaches it.

Both gates layer **on top of** the existing Phase-3 per-strategy regime whitelist (each strategy's
``classify_frame`` already restricts itself to its policy regimes) — they only ever *remove* trades,
never add them, so the strategy modules and the walk-forward harness stay untouched.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import polars as pl

from tfex_s50_multi_tf_swing.regime.models import Regime
from tfex_s50_multi_tf_swing.signals import strategy_a, strategy_b
from tfex_s50_multi_tf_swing.signals.base import SIGNAL
from tfex_s50_multi_tf_swing.signals.errors import SignalInputError
from tfex_s50_multi_tf_swing.signals.inputs import COL_REGIME
from tfex_s50_multi_tf_swing.signals.models import (
    NO_SIGNAL,
    STRATEGY_IDS,
    SetupSignal,
    SignalConfig,
    StrategyId,
)

logger = logging.getLogger(__name__)

DetectFn = Callable[[pl.DataFrame], list[SetupSignal]]
"""A strategy's detect step: aligned signal-input frame → fired setup signals (post-gate)."""

# Per-strategy classify / materialise functions (typed, so the composed map stays mypy-clean).
_CLASSIFY: dict[StrategyId, Callable[[pl.DataFrame, SignalConfig], pl.DataFrame]] = {
    "A": lambda df, cfg: strategy_a.classify_frame(df, config=cfg),
    "B": lambda df, cfg: strategy_b.classify_frame(df, config=cfg),
    # "C" permanently disabled per the 1H-execution migration (2026-06-05).
}
_TO_SIGNALS: dict[StrategyId, DetectFn] = {
    "A": strategy_a.to_signals,
    "B": strategy_b.to_signals,
    # "C": strategy_c.to_signals,  # permanently disabled per the 1H-execution migration.
}


def apply_regime_gate(
    classified: pl.DataFrame,
    *,
    allowed_regimes: frozenset[Regime],
    strategy_id: StrategyId,
) -> pl.DataFrame:
    """Demote fired bars whose 1H regime is not in ``allowed_regimes`` to a clean "No Trade".

    Vectorised: the :data:`~tfex_s50_multi_tf_swing.signals.base.SIGNAL` column is overwritten to
    :data:`~tfex_s50_multi_tf_swing.signals.models.NO_SIGNAL` wherever ``1h_regime`` is outside the
    allow-set (a null regime is treated as blocked). Downstream
    :func:`~tfex_s50_multi_tf_swing.signals.base.to_signals` already skips ``NO_SIGNAL`` rows, so a
    blocked bar simply emits no :class:`SetupSignal`. One structured log line records how many
    signals were blocked and in which regimes.

    Raises :class:`SignalInputError` if the frame carries neither the regime nor the signal column.
    """
    missing = [c for c in (COL_REGIME, SIGNAL) if c not in classified.columns]
    if missing:
        raise SignalInputError(f"regime gate input frame missing columns: {sorted(missing)}")

    allowed = sorted(allowed_regimes)
    allowed_mask = pl.col(COL_REGIME).is_in(allowed).fill_null(False)

    blocked = classified.filter((pl.col(SIGNAL) != NO_SIGNAL) & ~allowed_mask)
    if blocked.height:
        by_regime = {
            str(row[COL_REGIME]): int(row["len"])
            for row in blocked.group_by(COL_REGIME).len().sort(COL_REGIME).iter_rows(named=True)
        }
        logger.info(
            "regime gate blocked %d %s entry signal(s); allowed=%s blocked_by_regime=%s",
            blocked.height,
            strategy_id,
            allowed,
            by_regime,
        )

    return classified.with_columns(
        pl.when(allowed_mask).then(pl.col(SIGNAL)).otherwise(pl.lit(NO_SIGNAL)).alias(SIGNAL)
    )


def _build_detect(
    strategy_id: StrategyId,
    sig_cfg: SignalConfig,
    allowed_regimes: frozenset[Regime],
) -> DetectFn:
    """Compose one strategy's ``classify_frame → apply_regime_gate → to_signals`` detect step."""
    classify = _CLASSIFY[strategy_id]
    materialise = _TO_SIGNALS[strategy_id]

    def detect(df: pl.DataFrame) -> list[SetupSignal]:
        classified = classify(df, sig_cfg)
        gated = apply_regime_gate(
            classified, allowed_regimes=allowed_regimes, strategy_id=strategy_id
        )
        return materialise(gated)

    return detect


def build_detect_map(
    sig_cfg: SignalConfig,
    *,
    enabled: frozenset[StrategyId],
    allowed_regimes: frozenset[Regime] | None = None,
) -> dict[StrategyId, DetectFn]:
    """Build the active ``{strategy_id → detect}`` map: only ``enabled`` strategies, regime-gated.

    ``allowed_regimes`` defaults to ``sig_cfg.allowed_regimes``. Each detect step is
    ``classify_frame → apply_regime_gate → to_signals``, so the returned map is a drop-in for the
    walk-forward harness' ``detect`` argument while realising the "disable C / ORB-core" and
    "regime-gated entries" mitigations purely from config.
    """
    regimes = allowed_regimes if allowed_regimes is not None else sig_cfg.allowed_regimes
    detect: dict[StrategyId, DetectFn] = {}
    for sid in STRATEGY_IDS:
        if sid in enabled:
            if sid not in _CLASSIFY:
                logger.info(
                    "build_detect_map: skipping %s — not in the active registry "
                    "(permanently disabled per the 1H-execution migration)",
                    sid,
                )
                continue
            detect[sid] = _build_detect(sid, sig_cfg, regimes)
    if not detect:
        logger.warning("build_detect_map: no strategies enabled (enabled=%s)", sorted(enabled))
    else:
        logger.info(
            "active strategies=%s; entry regimes=%s",
            sorted(detect),
            sorted(regimes),
        )
    return detect


__all__: list[str] = ["DetectFn", "apply_regime_gate", "build_detect_map"]
