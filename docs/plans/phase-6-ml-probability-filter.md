# Phase 6 — ML Probability Filter

**Feature:** `feature-tfex-integration` — Phase 6: ML Probability Filter
**Branch:** `feature/phase-6-ml-probability-filter`
**Created:** 2026-06-04
**Status:** Complete (machinery; magnitude data-gated)
**Depends On:** Phase 5 (Complete — Strategies A/B/C + execution + per-strategy backtest)

---

## Table of Contents

1. [Overview](#overview)
2. [Originating Prompt](#originating-prompt)
3. [Scope](#scope)
4. [Design Decisions](#design-decisions)
5. [Filter Contract](#filter-contract)
6. [ML Approach](#ml-approach)
7. [Configuration Surface](#configuration-surface)
8. [Implementation Steps](#implementation-steps)
9. [File Changes](#file-changes)
10. [Test Strategy](#test-strategy)
11. [Edge Cases](#edge-cases)
12. [Rollout / Cutover](#rollout--cutover)
13. [Success Criteria](#success-criteria)
14. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 6 adds the **ML Probability Filter** — the Intelligence-layer component that the
ROADMAP (§6) and `.claude/knowledge/ml-filter.md` describe as a **gate, never a
strategy** (TFEX hard rule #7). A LightGBM model emits a probability over an
already-fired rule-based setup; the setup survives only if it clears a configurable
threshold:

- `P(trend_continuation) > τ_cont` gates **Strategies A & B** (keep when *high*).
- `P(fake_breakout) < τ_fake` gates **Strategy C** (drop when the breakout looks fake).

The filter **defaults OFF**. When disabled — or when no model artifact exists, or a
feature row cannot be located — it is the **identity function**: the exact list of
`SetupSignal`s it received, unchanged and in order. This guarantees Phase-5 behaviour
is byte-for-byte reproduced in the default configuration.

### Scope decisions (confirmed with the requester)

1. **Machinery, default-off, synthetic-tested, real model deferred.** This phase
   ships the full `ml/` package code-complete (labelling, walk-forward training,
   LightGBM models, the gating filter, config), tested ≥ 90 % on **synthetic** data,
   with a public-safe demo script. The real trained-model artifacts and the
   out-of-sample A/B expectancy claim are **data-gated** on the still-pending 5-year
   backfill — exactly how Phases 3–5 shipped their machinery while deferring the
   magnitude claim. **No model binaries are committed.**
2. **Wired only at the backtest/detect layer** (ROADMAP-pure, like Phase 5):
   `filter_signals(...)` plus an optional, default-`None` `ml_filter` parameter on
   `run_per_strategy_backtest`. No FastAPI endpoint, no live/runtime wiring, no
   `extended_data` change this phase.

### Discrepancy with the originating prompt (surfaced, resolved per the prompt's own rule)

The originating prompt repeatedly names `adapters/` and `risk/` as the touched
packages subject to the ≥ 90 % coverage gate. The ROADMAP (§6) and the codebase place
the filter in a **new `ml/` package**, and `risk/` is a **Phase-7** package that does
not exist yet. The prompt instructs: *"If the roadmap and this prompt ever conflict,
follow the roadmap and call out the discrepancy."* Accordingly, the ≥ 90 % coverage
gate is applied to the new **`ml/`** package, which is added to the coverage
configuration exactly as every prior phase added its own package. `adapters/` and
`risk/` are not touched.

### Where Phase 6 composes with the existing pipeline

```
data/ → features/ → regime/ → bias/ → signals/ ──to_signals()──▶ list[SetupSignal]
                                                                        │
                                              ┌─────── Phase 6 hook ────┘
                                              ▼
                            ml.filter_signals(signals, aligned_inputs, …)
                                              │  (subset, same instances)
                                              ▼
                          execution.simulate_signals(…) → backtest.compute_metrics(…)
```

The aligned 5m frame produced by `signals.build_signal_inputs` already carries every
feature the model needs, **availability-shifted** so a lookup at `signal.time` is
look-ahead-free by construction. The filter never re-fetches or re-derives data.

---

## Originating Prompt

The following prompt initiated this phase (embedded verbatim per the project's
plan-doc convention):

````
You are working in the `quant-trading-system` umbrella repo. Your task is to implement **Phase 6 — ML Probability Filter** for the TFEX strategy service at
`strategies/tfex-s50-multi-tf-swing/`. This sub-directory is its own independent git repository (remote `github.com/lumduan/tfex-s50-multi-tf-swing`) — do all
git work from inside that sub-repo, never from the umbrella.

## Step 0 — Ground yourself in the existing design (READ BEFORE ANYTHING)

Read these in order and build a mental model of the current architecture, conventions, and where Phase 6 fits. Do not skip — your plan must be consistent with
what already exists:

1. `CLAUDE.md` (umbrella, repo-root) — system map, ingestion contract, cross-cutting rules.
2. `strategies/tfex-s50-multi-tf-swing/CLAUDE.md` — the strategy's own conventions, quality gate (ruff, mypy **strict**, pytest ≥90% on `adapters/` +
`risk/`), `uv`-only command rule.
3. `strategies/tfex-s50-multi-tf-swing/docs/plans/ROADMAP.md` — the authoritative per-strategy roadmap; locate the **Phase 6 — ML Probability Filter** entry
and any phases it depends on. Treat the roadmap's wording as the source of truth for scope, naming, and acceptance bar. If the roadmap and this prompt ever
conflict, follow the roadmap and call out the discrepancy.
4. Walk the actual source tree of `strategies/tfex-s50-multi-tf-swing/` — especially the existing signal/setup-detection pipeline, the `adapters/` and `risk/`
packages, config/env handling, the OHLCV read path (the `TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE = mirror | engine` flag), and the existing test layout.
Identify the exact module boundary where an ML probability filter must hook in (i.e. after a candidate setup/signal is generated, before it becomes an
order/exposure).

Then summarize back, in your plan doc, what Phase 6 actually requires according to the roadmap and how it composes with the existing multi-timeframe swing
setup detection.

## Step 1 — Create a feature branch

Inside `strategies/tfex-s50-multi-tf-swing/`, create a new branch off the repo's integration base (confirm the base branch from the sub-repo's own conventions
/ current branch; do NOT assume `main` if the repo uses something else). Use a descriptive name such as `feature/phase6-ml-probability-filter`.

## Step 2 — Write the implementation plan FIRST (plan before code)

Before writing any production code, author a complete implementation plan as a markdown file at:

`strategies/tfex-s50-multi-tf-swing/docs/plans/{phase_name}.md`

Use the structure and depth of the format reference at `strategies/csm-set/docs/plans/examples/phase1-sample.md` — match its sectioning, tone, and level of
detail. The plan MUST:

- Embed **this entire prompt verbatim** in a clearly labeled "Originating Prompt" section near the top.
- State the objective, scope, and explicit non-goals of Phase 6.
- Define the ML probability filter contract precisely: what it consumes (feature inputs derived from the multi-tf setup + market-data engine OHLCV), what it
emits (a calibrated probability / confidence score and a pass/reject decision against a configurable threshold), and how it gates an otherwise-valid setup.
- Specify the model approach with justification (favor a simple, interpretable, reproducible model — e.g. gradient-boosted trees or logistic regression with
well-defined features — over anything heavy or opaque, unless the roadmap dictates otherwise). Define feature engineering, label definition, train/validation
split that respects time ordering (walk-forward / no look-ahead leakage), and how the model artifact is versioned, stored, and loaded at inference time.
- Specify configuration surface: env vars / settings (follow the existing naming convention, e.g. an `ENABLE_ML_FILTER` toggle defaulting OFF for backward
compatibility, plus threshold and model-path settings) and how the filter degrades gracefully (if disabled or the model artifact is missing, the strategy must
behave exactly as Phase 5).
- Map every file you will add or change, with project-relative paths.
- Define the test strategy to clear the ≥90% gate on touched `adapters/`/`risk/` code: unit tests for feature extraction, scoring, threshold gating,
no-leakage guarantees, disabled-flag passthrough, and missing/corrupt-model error handling; plus an integration test exercising a setup → filter → decision
path end-to-end.
- List edge cases (insufficient history for features, NaN/missing bars, class imbalance, probability calibration, concurrency/thread-safety of model loading,
determinism/seed control).
- Provide a rollout/cutover note: default-off behind the toggle, how to enable, and migration impact (none to the ingestion contract — confirm no gateway
schema change is needed; strategy-specific fields belong in `extended_data`, never new gateway columns).

## Step 3 — Implement against the plan

Only after the plan doc exists, implement Phase 6 to match it. Hard requirements:

- All Python commands go through `uv run` (never bare `python`/`pip`).
- **mypy strict** clean; full type annotations including the ML interfaces (no untyped `Any` escapes at module boundaries).
- ruff check + ruff format clean.
- Async correctness: if the filter sits in an async request/signal path, do not block the event loop with CPU-bound inference — isolate sync model calls
appropriately and keep model loading thread-safe and done once.
- Comprehensive error handling + structured logging at decision points (setup scored, passed, rejected, filter disabled, model load failure).
- Monetary values remain `Decimal` at any boundary; store UTC / display Asia/Bangkok; remain tz-aware end-to-end.
- Security/robustness: validate all feature inputs; never log secrets; the ML model artifact must not embed credentials; never commit any tvkit cookie or
secret; keep secrets in `.env` (gitignored).
- Backward compatibility: with the ML filter disabled, behavior and outputs are byte-for-byte equivalent to the prior phase. Default the toggle OFF.
- Performance: note and avoid obvious bottlenecks (re-loading the model per call, recomputing features redundantly); add a brief before/after or complexity
note in the plan/docs.
- Prefer the simplest design that satisfies the roadmap over a clever one.

## Step 4 — Tests & quality gate

Write and run the full test suite via `uv run`. Achieve ≥90% coverage on the touched `adapters/` and `risk/` modules. Before any push, run the project's
pre-push checklist in order: `ruff check`, `ruff format --check`, `mypy` (strict), `pytest`. If any post-format edit/sed occurs, re-run `ruff format --check`
before pushing. Do not push with a failing or skipped gate — report failures with their output rather than hiding them.

## Step 5 — Update knowledge / docs / memory where warranted

If anything you learned or decided is worth persisting, create or update the appropriate file(s):

- `strategies/tfex-s50-multi-tf-swing/CLAUDE.md` (e.g. new env vars, the ML filter toggle, how to retrain/load the model).
- `strategies/tfex-s50-multi-tf-swing/.claude/*` (knowledge notes / playbooks for the ML filter lifecycle: train, evaluate, version, deploy).
- `strategies/tfex-s50-multi-tf-swing/docs/plans/ROADMAP.md` — mark Phase 6 status accordingly.
- Umbrella `CLAUDE.md` and umbrella `.claude/*` — ONLY if the change is genuinely cross-cutting (e.g. it touches the ingestion contract,
`feature-tfex-integration` registry status, or the engine catalog). If it's strategy-local, keep it in the sub-repo and do not edit umbrella history for
sub-project concerns.

Keep each doc edit minimal, accurate, and consistent with the surrounding style; update any CHANGELOG/README the repo maintains when behavior changes.

## Step 6 — Commit & PR

When the work is complete and the gate is green:

- Commit inside `strategies/tfex-s50-multi-tf-swing/` with a conventional, descriptive message; end the commit message with the required `Co-Authored-By:
Claude Opus 4.8 <noreply@anthropic.com>` trailer.
- Push the branch and open a PR to the `tfex-s50-multi-tf-swing` GitHub repo using `gh`. PR body must summarize scope, the toggle/default-off behavior,
test/coverage results, and migration impact; end the PR body with the required Claude Code generation trailer.
- Do NOT commit or push any umbrella-repo changes to sub-project history, and do not touch the other sub-repos.
- After the commit/push/PR, report the result as an ASCII box-drawing table (not a markdown pipe table) with columns **Repo | Branch | Commit | GitHub**, one
row per repo touched (the strategy sub-repo, and the umbrella only if you committed cross-cutting docs there). Use box-drawing characters `┌ ─ ┬ ┐ │ ├ ┼ ┤ └ ┴
┘`; Repo shows `lumduan/<name>` plus a short role note in parens; GitHub shows `PR #N → <url>` or the push status.

## Deliverables checklist

1. New feature branch in the sub-repo.
2. `strategies/tfex-s50-multi-tf-swing/docs/plans/{phase_name}.md` plan (with this prompt embedded), authored before code, matching the
`strategies/csm-set/docs/plans/examples/phase1-sample.md` format.
3. Phase 6 ML probability filter implemented, default-off, backward compatible, type-strict, tested ≥90% on touched `adapters/`/`risk/`.
4. Docs/knowledge/playbook/roadmap updates in the correct repo scope.
5. Green pre-push gate, commit + PR, and the ASCII result table.

If, after reading the roadmap, you find a genuine blocker or an ambiguity that materially changes scope, stop and surface it with a concrete recommendation
rather than guessing.
````

---

## Scope

### In Scope (Phase 6)

| Component | Description | Status |
|---|---|---|
| `ml/errors.py` | `MLFilterError(TfexS50Error)` + `ModelLoadError` / `FeatureExtractionError` / `LabelError` | Planned |
| `ml/models.py` | `MLFilterConfig`, `ModelTarget`, `LabelType`, `TripleBarrierConfig`, `ModelCard`, `ProbabilityModel` (Protocol), `ModelBundle` | Planned |
| `ml/features.py` | `FEATURE_COLUMNS` + deterministic feature-matrix builder + categorical encoders | Planned |
| `ml/labels.py` | Triple-barrier labelling (TP / SL / time) for both targets, optional `data/labels/` persistence | Planned |
| `ml/training.py` | Anchored walk-forward LightGBM trainer + feature-importance audit + `ModelCard` emit | Planned |
| `ml/store.py` | Versioned model save/load + thread-safe cached `ModelBundle` loader | Planned |
| `ml/filter.py` | `filter_signals(...)` — per-strategy threshold gate, default-off/missing-model identity passthrough, structured logging | Planned |
| `backtest/per_strategy.py` | Optional `ml_filter` param (default `None`) applied to detect output | Planned |
| `config/settings.py` | Five `ml_*` fields + `ml_filter_config()` | Planned |
| `pyproject.toml` | `lightgbm` + `numpy` deps; `ml/` added to coverage gate | Planned |
| `scripts/ml_filter_demo.py` | Public-safe synthetic end-to-end demo | Planned |
| Tests | `tests/unit/ml/*` + `per_strategy` additions + integration, ≥ 90 % on `ml/` | Planned |

### Out of Scope (Phase 6 — explicit non-goals)

- Real trained-model artifacts and the out-of-sample A/B expectancy / profit-factor
  **magnitude** claim — **data-gated** on the 5-year backfill (same gate as Phases 1/3/4/5).
- Any FastAPI endpoint, live/runtime/paper wiring, or scheduler integration.
- The `risk/` package (Phase 7) and the 200 THB/pt sizing multiplier.
- Any `extended_data` / gateway ingestion-contract / DB-schema change.
- Deep Learning of any kind (forbidden by hard rule #7).
- A `4h` engine route change — orthogonal to this phase.
- `P(volatility_expansion)` sizing input (listed "optional" in `ml-filter.md`; deferred).

---

## Design Decisions

### 1. The filter is a pure, order-preserving subset function

`filter_signals` returns a **subset of the same `SetupSignal` instances** it received,
in their original order — it never mutates a field, re-sorts, or constructs new
signals. This makes the disabled / degraded path provably identity (the regression
test asserts object identity and order), which is the cleanest possible guarantee of
backward compatibility.

### 2. Default OFF, and "missing model" degrades — it does not raise

`MLFilterConfig.enabled` defaults to `False`. With an unset environment the filter is
a no-op. When `enabled=True` but the model directory is empty / unreadable, the filter
logs a single WARNING and passes signals through unchanged rather than raising — a
production strategy must not halt because an optional ML artifact is absent. A
genuinely **corrupt** artifact (present but unparseable) raises `ModelLoadError` at
load time, surfaced through `load_bundle`; the caller decides whether to treat that as
fatal. The demo and the default path never raise.

### 3. Hook at the backtest/detect layer, not in `signals/`

The `signals/` package is a leaf with a one-way dependency contract; injecting ML
there would couple setup detection to the model. Instead the filter composes one level
up, on the `list[SetupSignal]` between `detect(...)` and `simulate_signals(...)`. The
only production edit is an **optional, default-`None`** `ml_filter` parameter on
`run_per_strategy_backtest`; existing call sites are unchanged and unaffected.

### 4. LightGBM, not logistic regression

The ROADMAP §6.2 header is literally "LightGBM Models" and `.claude/knowledge/ml-filter.md`
prescribes trees (LightGBM/XGBoost/CatBoost) over DL for small, non-stationary TFEX
data with auditable feature importance. We follow the roadmap. `lightgbm` is imported
**lazily** inside `training.py` / `store.py` so the rest of the strategy never pays the
import cost unless ML is actually trained or loaded.

### 5. Features come only from the already-aligned frame

`ml/features.py` reads a fixed, ordered `FEATURE_COLUMNS` list from the aligned 5m
frame columns that `build_signal_inputs` already produces — all availability-shifted,
so using them at `signal.time` cannot leak the future. No raw OHLCV is used as a
feature (public-data-boundary rule). Categoricals (`structure`, `1h_structure`,
`1h_regime`, `4h_bias_direction`) are encoded with a fixed deterministic mapping; an
unseen category maps to a defined "unknown" bucket rather than failing.

### 6. Walk-forward only; thresholds are part of the artifact

Training uses anchored walk-forward windows (train `[t0,t1]`, evaluate OOS `[t1,t2]`,
advance) — never a random split (hard rule #6). The decision threshold ships **inside**
the `ModelCard` (defaulting from config) so that a model and the threshold it was
validated at travel together. A feature-importance audit asserts no single feature
exceeds a configurable share of total gain (leakage guard).

### 7. Model loaded once, thread-safe; inference is sync

`store.load_bundle` is a lock-guarded lazy cache keyed by model directory — the model
is parsed once, not per call. Inference is CPU-bound and synchronous. There is no async
path in Phase 6 (the backtest is sync); the future live/async path must call the filter
via `asyncio.to_thread` to avoid blocking the event loop — documented here and in
`CLAUDE.md`, not wired this phase.

### 8. Artifacts live under gitignored `data/`, never committed

Model binaries and `data/labels/` outputs derive from gitignored market data; they live
under `data/models/` and `data/labels/` (both already gitignored) and are **never
committed**. The `ModelCard` JSON records provenance (train window, ordered feature
list, threshold, OOS metrics, seed, git sha) but **no secrets / no credentials**.

---

## Filter Contract

**Signature**

```python
def filter_signals(
    signals: list[SetupSignal],
    inputs: pl.DataFrame,
    *,
    config: MLFilterConfig,
    bundle: ModelBundle | None,
) -> list[SetupSignal]: ...
```

**Consumes**

- `signals` — the already-fired `list[SetupSignal]` from a strategy's `to_signals`.
- `inputs` — the aligned 5m frame from `build_signal_inputs` (carries every
  `FEATURE_COLUMNS` value per `time`, availability-shifted / leakage-free).
- `config` — `MLFilterConfig` (enabled flag + per-target thresholds + seed + model dir).
- `bundle` — a loaded `ModelBundle` (the two per-target models + their cards), or `None`.

**Per signal**

1. If `config.enabled` is `False` or `bundle is None` → identity passthrough.
2. Locate the `inputs` row at `signal.time`; if absent → keep the signal (degrade, log).
3. Build the feature vector (`ml/features.build_feature_row`).
4. Select the model by `signal.strategy_id` (A/B → `trend_continuation`; C → `fake_breakout`).
5. Compute the probability; apply the gate:
   - A/B: keep iff `P(trend_continuation) ≥ τ_cont`.
   - C: keep iff `P(fake_breakout) ≤ τ_fake`.
6. Log the decision structurally (`scored` / `passed` / `rejected`).

**Emits** — a subset of the same `SetupSignal` instances (no mutation, original order).

**Degrades to identity** when disabled, no bundle, a missing per-target model, or a
feature row not found.

---

## ML Approach

### Targets & gating direction

| Target | Gates | Triple-barrier label = 1 when | Keep signal when |
|---|---|---|---|
| `trend_continuation` | A, B | TP hit before SL (continuation held) | `P ≥ τ_cont` (default 0.55) |
| `fake_breakout` | C | SL/reversal hit before TP (breakout faked) | `P ≤ τ_fake` (default 0.50) |

### Feature engineering (`ml/features.py`)

A fixed, ordered `FEATURE_COLUMNS`:

- **Numeric (5m):** `atr_ratio`, `bollinger_squeeze`, `volume_expansion`, `dist_from_vwap`.
- **Numeric (1H):** `1h_dist_from_vwap`, `1h_atr_ratio`, `1h_volume_expansion`.
- **Categorical (encoded):** `structure`, `1h_structure` (HH/HL/LH/LL → fixed ints,
  unknown bucket), `1h_regime` (five-regime fixed map), `4h_bias_direction`
  (long/short/neutral → fixed ints).
- **Session flags:** `liquidity_sweep_flag`, `lunch_zone_flag`.

`build_feature_row(row_mapping)` → ordered `list[float]`; `build_feature_frame(inputs, times)`
→ a `numpy` matrix aligned to a list of signal times (one row per signal). NaN / missing
values map to a defined sentinel; an absent column raises `FeatureExtractionError` at
build time (a fail-loud config error, distinct from the runtime degrade-on-missing-row).

### Label definition (`ml/labels.py`)

`label_triple_barrier(signals, bars, *, config)` walks forward over the 5m execution
bars from each signal's entry, applying ATR-scaled TP / SL barriers and a time barrier
(reusing the same next-bar-open / ATR conventions as `execution/`), and emits one label
row per signal keyed by `(strategy_id, time, target)`. Optional persistence to
`data/labels/` (gitignored) keyed by `(setup_id, label_type)` per ROADMAP §6.1.

### Walk-forward training (`ml/training.py`)

`walk_forward_train(features, labels, *, config)` builds anchored windows
(`train_span` / `test_span` / `step`), fits a deterministic LightGBM booster per window
(`seed`, `deterministic=True`, single thread), evaluates OOS, runs the feature-importance
audit (no feature > `max_importance_share` of total gain), and returns the per-window OOS
metrics + the final booster wrapped with its `ModelCard`. **No random split anywhere** —
a test asserts every train fold strictly precedes its test fold in time.

### Versioning, storage, loading (`ml/store.py`)

- `save_model(bundle, model_dir)` writes `{target}.txt` (LightGBM text dump) + `{target}.card.json`.
- `load_bundle(model_dir)` reads both targets if present, validates the cards, and returns
  a `ModelBundle`; **lock-guarded `lru`-style cache** keyed by resolved dir so the parse
  happens once. Missing dir / no files → `None` (degrade). Present-but-corrupt → `ModelLoadError`.
- `ModelCard`: `target`, `feature_columns` (ordered), `threshold`, `train_window`,
  `oos_metrics`, `seed`, `git_sha`, `created_at` (UTC). No secrets.

### Complexity / performance note

- Model is parsed **once** (cached) — not per call; the filter does O(#signals) row
  lookups against an index map, each O(1). Features are read from the already-built
  aligned frame — **no recompute**. Inference is a single batched `predict` per target.
- Before/after: with the filter **off** the path is identical to Phase 5 (zero added
  cost beyond a disabled-flag check). With it **on**, cost is one model load (amortised)
  + one batched predict per backtest run.

---

## Configuration Surface

`config/settings.py` (env prefix `TFEX_S50_MULTI_TF_SWING_`):

| Field | Env var | Default | Bounds / note |
|---|---|---|---|
| `ml_filter_enabled` | `..._ML_FILTER_ENABLED` | `False` | master toggle — OFF |
| `ml_model_dir` | `..._ML_MODEL_DIR` | `./data/models` | artifact dir (gitignored) |
| `ml_threshold_continuation` | `..._ML_THRESHOLD_CONTINUATION` | `0.55` | ∈ [0, 1] |
| `ml_threshold_fake_breakout` | `..._ML_THRESHOLD_FAKE_BREAKOUT` | `0.50` | ∈ [0, 1] |
| `ml_seed` | `..._ML_SEED` | `42` | ≥ 0, determinism |

`Settings.ml_filter_config()` builds a frozen, bounds-checked `MLFilterConfig` (lazy
import, mirroring `signal_config()` / `bias_config()`). Unset env ⇒ disabled ⇒ no-op.

---

## Implementation Steps

### Step 1: `ml/errors.py`

`MLFilterError(TfexS50Error)` root + `ModelLoadError`, `FeatureExtractionError`,
`LabelError` subclasses (module-local errors convention).

### Step 2: `ml/models.py`

`MLFilterConfig` (frozen, bounded), `ModelTarget` / `LabelType` literals,
`TripleBarrierConfig` (frozen, bounded), `ModelCard` (frozen), `ProbabilityModel`
(`Protocol` with `predict_proba`), `ModelBundle` (the two optional per-target models +
cards).

### Step 3: `ml/features.py`

`FEATURE_COLUMNS`, deterministic encoders, `build_feature_row`, `build_feature_frame`.

### Step 4: `ml/labels.py`

`label_triple_barrier` + optional `data/labels/` writer.

### Step 5: `ml/training.py`

`walk_forward_train`, lazy LightGBM fit, importance audit, `ModelCard` assembly.

### Step 6: `ml/store.py`

`save_model`, `load_bundle` (cached, thread-safe), card validation.

### Step 7: `ml/filter.py` + `ml/__init__.py`

`filter_signals` gate logic + structured logging; public re-exports.

### Step 8: Wire-in

`config/settings.py` (`ml_*` + `ml_filter_config()`); `backtest/per_strategy.py`
(optional `ml_filter`); `scripts/ml_filter_demo.py`.

### Step 9: Tests + coverage config

`tests/unit/ml/*`, `per_strategy` additions, integration + identity regression;
`pyproject.toml` `--cov` + `[tool.coverage.run] source` add `ml/`.

### Step 10: Docs

ROADMAP status, CLAUDE.md `ml/` subsection, `.claude/knowledge/ml-filter.md` impl
notes, optional `.claude/playbooks/ml-filter-lifecycle.md`.

---

## File Changes

| File | Action | Description |
|---|---|---|
| `src/tfex_s50_multi_tf_swing/ml/__init__.py` | CREATE | Public re-exports |
| `src/tfex_s50_multi_tf_swing/ml/errors.py` | CREATE | Error hierarchy |
| `src/tfex_s50_multi_tf_swing/ml/models.py` | CREATE | Config + data contracts |
| `src/tfex_s50_multi_tf_swing/ml/features.py` | CREATE | Feature extraction |
| `src/tfex_s50_multi_tf_swing/ml/labels.py` | CREATE | Triple-barrier labels |
| `src/tfex_s50_multi_tf_swing/ml/training.py` | CREATE | Walk-forward trainer |
| `src/tfex_s50_multi_tf_swing/ml/store.py` | CREATE | Versioned load/save (cached) |
| `src/tfex_s50_multi_tf_swing/ml/filter.py` | CREATE | Gating filter |
| `src/tfex_s50_multi_tf_swing/backtest/per_strategy.py` | MODIFY | Optional `ml_filter` param |
| `src/tfex_s50_multi_tf_swing/config/settings.py` | MODIFY | `ml_*` fields + builder |
| `pyproject.toml` | MODIFY | deps + coverage gate |
| `scripts/ml_filter_demo.py` | CREATE | Public-safe synthetic demo |
| `tests/unit/ml/conftest.py` | CREATE | Synthetic frame/signal builders |
| `tests/unit/ml/test_features.py` | CREATE | Feature extraction tests |
| `tests/unit/ml/test_labels.py` | CREATE | Triple-barrier tests |
| `tests/unit/ml/test_training.py` | CREATE | Walk-forward + audit tests |
| `tests/unit/ml/test_store.py` | CREATE | Save/load/cache tests |
| `tests/unit/ml/test_filter.py` | CREATE | Gate / passthrough / selection tests |
| `tests/unit/ml/test_models_errors.py` | CREATE | Config bounds + error tests |
| `tests/unit/ml/test_filter_integration.py` | CREATE | setup→filter→backtest e2e + identity regression |
| `tests/unit/backtest/test_per_strategy.py` | MODIFY | `ml_filter` param coverage |
| `docs/plans/ROADMAP.md` | MODIFY | Phase 6 status |
| `docs/plans/phase-6-ml-probability-filter.md` | CREATE | This plan |
| `CLAUDE.md` | MODIFY | `ml/` subsection + env vars |
| `.claude/knowledge/ml-filter.md` | MODIFY | Implementation notes |
| `.claude/playbooks/ml-filter-lifecycle.md` | CREATE | Train → audit → version → enable |

---

## Test Strategy

Coverage gate ≥ 90 % on the new `ml/` package (added to `pyproject.toml`).

- **features:** vector shape/order; deterministic categorical encoding incl. unknown
  bucket; NaN/missing → sentinel; absent column → `FeatureExtractionError`; no-leakage
  (only at/before-signal columns referenced).
- **labels:** TP-first / SL-first / time-exit branches; both target definitions;
  empty-input; UTC enforcement.
- **training:** walk-forward folds strictly time-ordered (assert no future bar in any
  train fold); importance-audit cap triggers; determinism (two fits → identical model
  dump) with fixed seed; class-imbalance path.
- **store:** save→load round-trips a tiny real booster in `tmp_path`; card integrity;
  cache returns the same object (no reload); missing dir → `None`; corrupt artifact →
  `ModelLoadError`.
- **filter:** per-target threshold keep/reject; disabled-flag identity (same instances,
  same order); `bundle=None` identity; missing per-target model passthrough;
  per-strategy model selection; missing-feature-row degrade; structured-log assertions.
  Gate logic uses a lightweight stub `ProbabilityModel` so it needs no real booster.
- **integration:** setup → `filter_signals` → `run_per_strategy_backtest(ml_filter=…)`
  end-to-end on synthetic data; **identity regression:** `ml_filter=None` reproduces the
  exact Phase-5 `BacktestMetrics`.

---

## Edge Cases

Insufficient history for a feature row; NaN / missing 5m bars at `signal.time`; a
feature row not found for `signal.time` (degrade, never crash); label class imbalance;
probability calibration (thresholds documented + walked forward, never tuned on the full
set); thread-safety of the lazy model cache (lock-guarded); determinism (`seed` +
`deterministic=True`, single thread); empty signal list; `enabled=True` with an empty
model dir; unseen categorical value (unknown bucket).

---

## Rollout / Cutover

- **Default OFF** (`ml_filter_enabled=False`) ⇒ zero behavioural change vs Phase 5;
  rollback = leave the env unset.
- **Enable** by training artifacts into `data/models/` (owner-side, data-gated) and
  setting `..._ML_FILTER_ENABLED=true` plus the two thresholds.
- **Migration impact: none.** No ingestion-contract / gateway-schema / DB change. Any
  future ML telemetry belongs in `extended_data` (deferred), never new gateway columns.
- The real trained models and the OOS A/B expectancy claim remain **data-gated** on the
  5-year backfill (recorded in the ROADMAP Phase 6 status).

---

## Success Criteria

- [ ] `ml/` package implemented: errors, models, features, labels, training, store, filter.
- [ ] Filter default-OFF; disabled / no-model paths are provably identity (regression test).
- [ ] A/B gated by `P(trend_continuation)`; C gated by `P(fake_breakout)`; thresholds configurable.
- [ ] Walk-forward training only; no-leakage + importance-audit tests pass.
- [ ] Model loaded once (cached, thread-safe); features not recomputed.
- [ ] `uv run ruff check .` / `ruff format --check .` clean.
- [ ] `uv run mypy src tests` strict-clean (no `Any` escapes at ML boundaries).
- [ ] `uv run pytest` green; ≥ 90 % coverage on `ml/`.
- [ ] `uv run python scripts/ml_filter_demo.py` runs end-to-end on synthetic data.
- [ ] No model binaries / secrets committed; `data/` stays gitignored.
- [ ] ROADMAP / CLAUDE / knowledge / playbook updated; PR opened with the result table.

---

## Completion Notes

### Summary

Phase 6 machinery shipped 2026-06-04. The `ml/` leaf package (errors, models, features,
labels, training, store, filter) is implemented default-OFF and wired only at the
backtest/detect layer via an optional `ml_filter` param on `run_per_strategy_backtest`.
`lightgbm` + `numpy` were added as dependencies and `ml/` joined the ≥ 90 % coverage gate;
the package reaches **100 %** line coverage (overall suite 97.6 %, 524 passed / 5 skipped),
mypy strict clean, ruff clean. The default-OFF / missing-model paths are provably the identity
function (regression test asserts `ml_filter=None` reproduces the Phase-5 `BacktestMetrics`
exactly). A public-safe synthetic demo (`scripts/ml_filter_demo.py`) exercises detect → label →
walk-forward train → save → load → filter → A/B backtest end-to-end. Real trained models and the
out-of-sample A/B expectancy/profit-factor magnitude claim remain **data-gated** on the 5-year
backfill, as confirmed with the requester.

### Issues Encountered

1. **NaN OOS metrics broke JSON round-trip.** When every walk-forward fold's test block was
   single-class, the aggregated AUC was `NaN`, which is not JSON-round-trippable and failed
   `ModelCard` re-validation on load. Fixed by **omitting** an all-NaN metric from the card's
   `oos_metrics` rather than storing `NaN`.
2. **Triple-barrier vs synthetic intrabar range.** The demo initially stopped out every trade on
   the entry bar because the synthetic bar's intrabar range exceeded the ATR-scaled barrier;
   shrinking the band below the barrier distance (and using a trend that dominates the noise)
   produced the intended *mixed* labels.
3. **mypy strict on tests.** `list` invariance required `Sequence`-typed helper params and a
   precise `list[datetime]` return; `MLFilterConfig(**dict)` was replaced with `model_validate`.

---

**Document Version:** 1.1
**Author:** AI Agent (Claude Opus 4.8)
**Status:** Complete (machinery; magnitude data-gated)
**Created:** 2026-06-04
**Completed:** 2026-06-04
