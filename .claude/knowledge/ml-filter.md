# ML Probability Filter

ML is a **filter**, **ranking** layer, and **probability engine** — never a strategy.
The model gates rule-based signals; it does not invent trades.

## What the model predicts

| Target | Use |
| --- | --- |
| `P(trend_continuation)` | Gate Strategies A and B |
| `P(fake_breakout)` | Gate Strategy C |
| `P(volatility_expansion)` | Optional sizing input |

## What the model does NOT predict

- Next candle direction
- Exact price target
- "When the market will crash"

These framings are seductive and useless. Stay with probabilities over discrete
setups.

## Model family

LightGBM / XGBoost / CatBoost. **No Deep Learning at this stage.** Reasons:

- TFEX data volume is small.
- Markets are non-stationary; DL overfits faster than it generalises.
- Trees are interpretable; importance audits catch leakage early.

## Training discipline

- **Walk-forward only**: train on `[t0, t1]`, evaluate on `[t1, t2]`; advance window.
- Re-fit per window (e.g., quarterly).
- Out-of-sample metrics required to ship — no in-sample bragging.
- Feature importance audited; no single feature may dominate.
- Triple-barrier labels (TP / SL / time) standardise the target.

## Thresholds

Each model has a documented decision threshold (e.g., enter if
`P(trend_continuation) > 0.55`). Thresholds are themselves walked forward — tuning
on the full dataset is leakage.

## A/B integration

Every model release is A/B compared against the unfiltered ruleset on a held-out
window. Ship the filter only if it improves out-of-sample expectancy or profit factor
without making any regime worse.

## What NOT to do

- Never random-split a time series.
- Never train on the full dataset before walk-forward validation.
- Never let a model with no economic story ship — the model must align with a
  documented hypothesis (trend continuation, mean reversion, regime persistence).
- Never replace the rule-based strategy with the model. The model is a gate.

## Implementation (Phase 6, shipped 2026-06-04 — default-OFF, magnitude data-gated)

The design above is realised by the `src/tfex_s50_multi_tf_swing/ml/` leaf package
(`signals/ → ml/`; imports nothing downstream). Full plan:
[`docs/plans/phase-6-ml-probability-filter.md`](../../docs/plans/phase-6-ml-probability-filter.md).

| Module | Responsibility |
| --- | --- |
| `ml/models.py` | `MLFilterConfig` (frozen; `enabled` default **False**, per-target thresholds), `ModelTarget`, `TripleBarrierConfig`, `ModelCard` (provenance + threshold, UTC), `ProbabilityModel` (Protocol), `ModelBundle`, `target_for_strategy` (A/B→continuation, C→fake_breakout) |
| `ml/features.py` | Fixed ordered `FEATURE_COLUMNS` (13); deterministic encoders — categoricals → fixed small ints with a `0` unknown bucket, missing numerics → `NaN` (LightGBM-missing); **no raw OHLCV is ever a feature** |
| `ml/labels.py` | `label_triple_barrier` (TP/SL/time over forward 5m bars; SL assumed first on a tie); `save_labels` → gitignored `data/labels/` |
| `ml/training.py` | `walk_forward_train` — anchored walk-forward (never random split), per-fold OOS metrics (NumPy-only AUC), `audit_importance` rejecting a dominating feature; deterministic fits (`deterministic=True` + 1 thread + seed) |
| `ml/store.py` | `LightGBMModel` (booster wrapper), `save_model` (text dump + `ModelCard` JSON), `load_bundle` (thread-safe, cached by (path, mtimes); missing dir → `None`, corrupt → `ModelLoadError`) |
| `ml/filter.py` | `filter_signals(signals, inputs, *, config, bundle)` — order-preserving subset of the *same* instances; identity on disabled / no-model / missing-row |

**Hook:** an optional, default-`None` `ml_filter` param on
`backtest.per_strategy.run_per_strategy_backtest` (ROADMAP-pure: no API / `risk/` /
`extended_data`). **Config env:** `TFEX_S50_MULTI_TF_SWING_ML_FILTER_ENABLED` (OFF),
`…_ML_MODEL_DIR`, `…_ML_THRESHOLD_CONTINUATION` (0.55), `…_ML_THRESHOLD_FAKE_BREAKOUT`
(0.50), `…_ML_SEED` (42) → `Settings.ml_filter_config()`.

**Degradation contract:** disabled, no bundle, a strategy's per-target model absent, or no
aligned-frame row at a signal's time ⇒ the signal is **kept** (identity). So OFF (or no
artifact) reproduces Phase 5 byte-for-byte.

**Performance:** model parsed once (cached); features read from the already-built aligned
frame (no recompute); one batched `predict` per target. With the filter OFF the path is the
Phase-5 path plus a single boolean check.

**Status:** machinery + synthetic tests (100 % coverage on `ml/`) shipped; real trained
models + the OOS A/B expectancy/profit-factor claim are **data-gated** on the 5-year
backfill (same gate as Phases 1/3/4/5). Lifecycle: `.claude/playbooks/ml-filter-lifecycle.md`;
public-safe demo `scripts/ml_filter_demo.py`. **Never commit a model binary or a tvkit cookie.**
