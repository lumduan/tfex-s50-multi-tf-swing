# Phase 3: Regime Detection — Rule-Based Baseline + Strategy Policy

**Feature:** `feature-tfex-integration` — Intelligence Layer, Regime Detection
**Branch:** `feature/phase-3-regime-detection`
**Created:** 2026-05-29
**Status:** Complete
**Completed:** 2026-05-29
**Depends On:** Phase 2 — Feature Engineering (Complete)

---

## Table of Contents

1. [Overview](#overview)
2. [Originating Prompt](#originating-prompt)
3. [Scope](#scope)
4. [Design Decisions](#design-decisions)
5. [Regime Rules](#regime-rules)
6. [Implementation Steps](#implementation-steps)
7. [File Changes](#file-changes)
8. [Test Plan](#test-plan)
9. [Success Criteria](#success-criteria)
10. [Risks](#risks)
11. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 3 adds the **Intelligence Layer's regime detector**: a deterministic, rule-based
classifier that labels every bar as one of five regimes, plus a regime → strategy/size
**policy** table. Regime awareness is documented as "the single largest source of edge"
(`.claude/knowledge/regime-detection.md`) and gates trading for every downstream phase
(bias engine, setup detection, risk).

This phase ships ROADMAP **§3.1 (rule-based baseline)** and **§3.4 (regime-to-strategy
mapping)** only. The classifier consumes the Phase 2 feature panel; it is a pure offline
library module — **no FastAPI endpoint, no gateway `extended_data` change, no `risk/`
wiring** (those packages do not exist yet and belong to Phases 5 / 7).

### Parent Plan Reference

- `docs/plans/ROADMAP.md` → **Phase 3 — Regime Detection**
- `.claude/knowledge/regime-detection.md` (taxonomy, rule sketches, policy table)

### Key Deliverables

1. **`src/tfex_s50_multi_tf_swing/regime/errors.py`** — `RegimeError` hierarchy under the
   shared `TfexS50Error` root.
2. **`src/tfex_s50_multi_tf_swing/regime/models.py`** — `Regime` Literal + `REGIMES`,
   `RegimeFeatures`, `RegimeThresholds`, `RegimeClassification`, `RegimePolicy` (Pydantic v2).
3. **`src/tfex_s50_multi_tf_swing/regime/rules.py`** — `classify_frame()` (vectorised, Polars)
   and `classify_row()` (scalar).
4. **`src/tfex_s50_multi_tf_swing/regime/policy.py`** — `regime_to_strategies()`,
   `regime_to_size_multiplier()`, `regime_policy()`, `is_no_trade()`.
5. **`src/tfex_s50_multi_tf_swing/regime/__init__.py`** — public re-exports.
6. **Config** — regime thresholds on `Settings` (`TFEX_S50_MULTI_TF_SWING_REGIME_*`),
   `.env.example` updated.
7. **Tests** — `tests/unit/regime/` ≥ 90 % coverage on `regime/`.

---

## Originating Prompt

The following prompt initiated this phase. It is embedded verbatim so the plan is
self-contained.

```
You are working in the `quant-trading-system` umbrella repo. The active work is in the
independent sub-repo `strategies/tfex-s50-multi-tf-swing/` (FastAPI / Python 3.11, `uv`,
mypy strict, pytest ≥90% on `adapters/` + `risk/`). Treat each sub-directory as its
own git repository with its own remote — do NOT edit other sub-projects' git history.

## STEP 0 — Read and absorb context BEFORE touching anything
Read these in order and build a mental model of how the services connect (ingestion
contract, Docker network, engine catalog, data flow). Quote the parts that constrain
Phase 3 back to yourself before planning:
- `CLAUDE.md` (umbrella system map + cross-cutting rules)
- `quant-api-gateway/CLAUDE.md` (ingestion contract `/api/v1/ingest/daily-report`, `extended_data` escape hatch, engine surface `/api/v2/engines/*`)
- `quant-dashboard/CLAUDE.md` (deprecated React UI — note it, don't build for it)
- `quant-infra-db/CLAUDE.md` (PostgreSQL/TimescaleDB + MongoDB provisioning, init-scripts, hypertables)
- `strategies/csm-set/CLAUDE.md` (reference strategy — mirror its adapter/api conventions and test layout)
- `strategies/csm-set/docs/plans/examples/phase1-sample.md` (REQUIRED — the exact plan-file format you must follow)
- The entire `strategies/tfex-s50-multi-tf-swing/` tree (existing Phase 0–2 code: adapters/, risk/, api/, models, config, tests) so Phase 3 extends real interfaces, not invented ones
- `strategies/tfex-s50-multi-tf-swing/docs/plans/ROADMAP.md` — read fully, then focus on Phase 3 — Regime Detection. Phase 3's scope, deliverables, and acceptance criteria as written there are the source of truth; if anything below conflicts with the ROADMAP, the ROADMAP wins and you must flag the conflict.

## STEP 1 — Branch
From inside `strategies/tfex-s50-multi-tf-swing/`, create a new branch off the current
default branch named `feature/phase-3-regime-detection` (adjust to match the repo's
existing branch-naming convention if it differs). Do all work there.

## STEP 2 — Plan first, then write the plan file (no code yet)
Design the Phase 3 regime-detection module before implementing. At minimum decide:
- Regime model: the regime taxonomy (e.g. trend-up / trend-down / range / high-vol)
  and the concrete signals driving classification (e.g. ADX/DI, ATR-based volatility
  bands, moving-average slope/structure, multi-timeframe agreement) — anchored to
  exactly what the ROADMAP's Phase 3 specifies, not added scope.
- Where it lives: module placement consistent with the existing one-way flow
  (`data → core → api`), Pydantic v2 models at boundaries, module-local `errors.py`.
- Inputs: which OHLCV / timeframe sources it consumes (settfex/tvkit via Market Data
  engine or local fixtures), how it gets multi-timeframe bars.
- Outputs / contract: regime classification surfaced via FastAPI endpoint(s) and, if
  the ROADMAP calls for it, threaded into the strategy's `extended_data` on the daily
  report — never as new gateway columns.
- How regime gates the strategy: how detected regime modulates signal/risk (e.g.
  suppress entries in unfavorable regimes), wired to the existing `risk/` layer.
- Persistence (only if ROADMAP requires it): any schema/migration touches go in the
  appropriate repo; if `quant-infra-db` init-scripts need a new idempotent numbered
  script, prepare it in that repo's own change set, not from tfex.
- Test strategy: unit tests for the classifier (deterministic, fixture-driven, no
  network) hitting ≥90% on the new module, plus integration tests for the endpoint.

Then write the plan to:
`strategies/tfex-s50-multi-tf-swing/docs/plans/phase-3-regime-detection.md`
Follow the structure of `strategies/csm-set/docs/plans/examples/phase1-sample.md`
exactly (objective, scope, deliverables, file-by-file changes, test plan, acceptance
criteria, risks). Embed this full prompt verbatim inside that plan file (in a clearly
labeled "Originating prompt" section) so the plan is self-contained.

## STEP 3 — Implement (only after the plan file exists)
Build Phase 3 to the plan. Enforce the repo's hard rules throughout:
- Type safety: full annotations, mypy strict clean; no bare `Any` without justification.
- Async correctness: all HTTP via `httpx.AsyncClient`; `requests` is forbidden; don't block the event loop.
- Pydantic v2 at every module/process boundary — no raw dicts crossing boundaries.
- Errors: module-local exceptions in `errors.py` inheriting a single root; never `raise Exception(...)`, never `except Exception: pass`.
- Logging: `logger = logging.getLogger(__name__)`, `%`-style deferred formatting, no `print`, never log secrets or full bodies.
- Config via env vars through `pydantic-settings`; no hard-coded paths/thresholds — regime thresholds come from a single `Settings`/config object. UTC stored, Asia/Bangkok displayed; tz-aware end-to-end.
- Monetary values as `Decimal` at the gateway boundary, never `float`.
- Security: validate all inputs, OWASP awareness on any new endpoint, secrets only via `.env` (gitignored), update `.env.example` if new vars are introduced.
- Backward compatibility: do not break the existing ingestion payload shape or Phase 0–2 endpoints; additive only. Note any migration impact in the plan.
- Performance: regime computation runs per-bar/per-request — avoid recomputing full history each call; flag any obvious bottleneck.
- Keep files ≤500 lines, functions ≤~50 lines; imports grouped stdlib→third-party→local; tests mirror source paths.

## STEP 4 — Quality gate (must pass before any commit)
Run locally and paste results; mirror CI exactly:
uv sync --all-groups
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest
uv run bandit -r src && uv run pip-audit
Coverage must meet the repo's enforced threshold (≥90% on `adapters/` + `risk/`, plus the
new regime module). If any check fails, fix and re-run — do not commit red.

## STEP 5 — Update docs (reflect reality, including dates and gotchas)
- `strategies/tfex-s50-multi-tf-swing/docs/plans/ROADMAP.md` — check off the Phase 3 items; add a dated note (today's date) and any problems hit during testing.
- `strategies/tfex-s50-multi-tf-swing/README.md` — update if behavior/endpoints/setup changed (new env vars, new endpoint, regime usage).
- `strategies/tfex-s50-multi-tf-swing/CLAUDE.md` — update if module layout, conventions, or quality-gate scope changed.
- If the regime contract touches the gateway's `extended_data` shape, document the new
  fields where the contract is described (do not silently change the schema).

## STEP 6 — Cross-cutting knowledge / memory / playbooks
If anything learned here is durable and cross-cutting, create/update:
- Umbrella `.claude/knowledge/feature-tfex-integration.md` (and the optional-features registry note) with the regime-detection design decision.
- Any relevant umbrella `.claude/playbooks/` step if the bring-up or verification flow changed.
- The tfex sub-repo's own `.claude/` knowledge if a strategy-local convention emerged.
Keep umbrella-scoped notes in the umbrella repo and service-scoped notes in the service repo — don't cross-write history.

## STEP 7 — Commit & PR
Use Conventional Commits (`feat: …` for the feature, `docs: …` for doc-only follow-ups).
Commit the tfex sub-repo changes on the feature branch, push to its own remote
(`github.com/lumduan/tfex-s50-multi-tf-swing`), and open a PR with a description that
summarizes scope, links the plan file, lists the quality-gate results, and calls out any
contract/migration impact. If umbrella `.claude/*` docs changed, commit those separately
in the umbrella repo (its own remote) — never mix the two repos in one commit. End commit
messages with the required `Co-Authored-By` trailer and PR bodies with the Claude Code
generation footer.

## CONSTRAINTS / DEFINITION OF DONE
- Stay within Phase 3 scope as defined in the ROADMAP; if you discover the ROADMAP is
  ambiguous or under-specifies the regime taxonomy, STOP and ask before inventing scope.
- Prefer the simplest correct design over clever abstractions.
- Done = plan file written (with embedded prompt), code implemented to the hard rules,
  full quality gate green with coverage met, all four docs updated with dated notes,
  cross-cutting `.claude/*` updated where warranted, and PR(s) opened on the correct
  remote(s).
```

---

## Scope

### In Scope (Phase 3 — §3.1 + §3.4)

| Component | Description | Status |
|---|---|---|
| `RegimeError` hierarchy | Module-local exceptions under `TfexS50Error` | Planned |
| `Regime` / `REGIMES` | 5-label taxonomy as `Literal` + tuple | Planned |
| `RegimeFeatures` | Pydantic scalar inputs for single-bar classification | Planned |
| `RegimeThresholds` | Frozen Pydantic cutoffs, env-overridable defaults | Planned |
| `RegimeClassification` | Pydantic `(time, timeframe, regime)` result | Planned |
| `RegimePolicy` | Pydantic regime → allowed strategies + size + direction | Planned |
| `classify_frame()` | Vectorised Polars classifier over a feature panel | Planned |
| `classify_row()` | Scalar classifier from `RegimeFeatures` | Planned |
| `regime_to_strategies()` / `regime_to_size_multiplier()` / `regime_policy()` / `is_no_trade()` | §3.4 policy table | Planned |
| Settings + `.env.example` | `TFEX_S50_MULTI_TF_SWING_REGIME_*` thresholds | Planned |
| Test suite | `tests/unit/regime/`, ≥ 90 % coverage | Planned |

### Out of Scope (deferred to later phases)

- **§3.2 Clustering notebook** (`notebooks/03_regime_clustering.ipynb`) — explicitly
  "optional intermediate"; deferred.
- **§3.3 LightGBM classifier** (`regime/model.py`) — its exit criterion (> 70 % agreement
  vs hand-labelled regimes on a held-out year) requires a hand-labelled dataset that does
  not exist yet. `regime-detection.md` says "do not skip steps"; the rule baseline (step 1)
  is the supervision target for the future model. Deferred to a follow-up PR.
- **FastAPI regime endpoint** — the `api/` package does not exist; the signals API
  (`/api/v1/signals/current`) is ROADMAP Phase 5.
- **Gateway `extended_data` threading** — daily-report assembly is Phase 7/9; the ingestion
  contract is unchanged this phase.
- **`risk/` wiring** — the `risk/` package is ROADMAP Phase 7. `policy.py` is the gating
  contract that Phase 7 will consume.

> **Flagged deviation from the originating prompt:** STEP 2/3 asked for a FastAPI endpoint,
> `extended_data` threading, and `risk/`-layer wiring. The ROADMAP places all three in later
> phases and the `api/` + `risk/` packages do not yet exist. Per the prompt's own rule
> ("the ROADMAP wins and you must flag the conflict"), this phase stays ROADMAP-pure and
> defers that work. Confirmed with the user before planning.

---

## Design Decisions

### 1. New leaf package `regime/`, fed by the un-normalised feature panel

`regime/` sits at `data/ → features/ → regime/ → bias/ → …` (the data flow in `CLAUDE.md`).
It imports from `features/` and `data/` but nothing downstream. The classifier consumes a
per-timeframe panel built with **`FeatureConfig(normalise=False)`**, because the normalised
panel z-scores `ema_slope_*`, `dist_from_vwap`, and `atr_ratio` against a trailing window —
which destroys the absolute signs and levels the rules depend on. The raw panel already
exposes the regime inputs un-normalised: `rv_percentile` (0–1), `trend_persistence` (−1..1),
`volume_expansion` (z-score), `range_compression` (Int8 = `atr_ratio<thr AND adx<thr`),
`structure` (HH/HL/LH/LL), `dist_from_vwap`, `ema_slope_{n}`.

### 2. EMA20-vs-EMA50 level derived in `rules.py`, reusing `indicators.ema`

The trend rule references "4H EMA20 > EMA50" (a *level* comparison), which is not a panel
column. Rather than add a feature, `classify_frame` derives `ema_fast - ema_slow` directly
from `close` using the existing causal `features.indicators.ema()` primitive. No new feature
column, no duplicated math.

### 3. Two entry points: vectorised frame + scalar row

- `classify_frame(panel, *, thresholds, timeframe)` is the primary API — one vectorised
  Polars pass that appends a `regime` Utf8 column. Computed once per panel build, never
  per-bar in a loop (performance rule).
- `classify_row(features, thresholds)` classifies a single bar from a `RegimeFeatures`
  model, for callers (Phase 4+) holding already-computed feature scalars. It does **not**
  recompute rolling history — rolling features (e.g. `rv_percentile`) must be supplied.

### 4. `panic` is evaluated first (dominates)

`panic` is the highest-priority label: `rv_percentile > panic_rv` OR
`volume_expansion > panic_volume_z`. Evaluated before trend/range so a volatility blow-off
in an otherwise "trending" tape is still flagged `panic`. Remaining order: trend_up →
trend_down → range_low_vol → range_high_vol, with `range_high_vol` the residual default when
no other rule fires (a defensive choice: an unclassified bar is treated as untradeable
high-vol rather than silently tradeable).

### 5. Thresholds live in one frozen config object, env-overridable

`RegimeThresholds` (frozen Pydantic) holds every cutoff with `Field` bounds and defaults
matching `.claude/knowledge/regime-detection.md`. `Settings` exposes the same values via the
`TFEX_S50_MULTI_TF_SWING_REGIME_*` prefix and a `regime_thresholds()` accessor, so no
threshold is hard-coded at a call site.

### 6. Lunch dead-zone handled in policy, not the regime label

The 12:00–14:00 lunch dead-zone is a *no-trade* condition layered on top of the regime, not
a sixth regime. `is_no_trade(regime, *, lunch_zone=False)` returns `True` for
`range_low_vol`, for `panic` (unless a caller opts into half-size), and whenever
`lunch_zone` is set. This keeps the 5-label taxonomy intact while honouring the
`regime-detection.md` policy table.

### 7. Features are `float`, not `Decimal`

Regime inputs are internal statistical quantities that never cross the gateway boundary, so
the Decimal-for-money rule does not apply (consistent with the Phase 2 feature layer).

---

## Regime Rules

Encoded in `rules.py`; thresholds from `RegimeThresholds` (defaults shown).

| Regime | Rule (all on the chosen timeframe, typically 4H) | Default thresholds |
|---|---|---|
| `panic` | `rv_percentile > panic_rv` **or** `volume_expansion > panic_volume_z` | `panic_rv=0.95`, `panic_volume_z=3.0` |
| `trend_up` | `ema_fast > ema_slow` **and** `ema_slope_fast > 0` **and** `structure ∈ {HH, HL}` **and** `dist_from_vwap > 0` **and** not panic | — |
| `trend_down` | mirror: `ema_fast < ema_slow` **and** `ema_slope_fast < 0` **and** `structure ∈ {LH, LL}` **and** `dist_from_vwap < 0` | — |
| `range_low_vol` | `rv_percentile < range_low_rv` **and** `range_compression == 1` | `range_low_rv=0.30` |
| `range_high_vol` | `rv_percentile > range_high_rv` **and** `|trend_persistence| < trend_persist_min`; also the residual default | `range_high_rv=0.70`, `trend_persist_min=0.30` |

`ema_fast`/`ema_slow` use `FeatureConfig.ema_spans` (default 20/50). `ema_slope_fast` is the
ATR-normalised slope of the fast EMA (panel column `ema_slope_{spans[0]}`).

---

## Implementation Steps

### Step 1: `regime/errors.py`

`RegimeError(TfexS50Error)` root + `RegimeInputError`, `RegimePolicyError`,
`UnknownRegimeError`. Import `TfexS50Error` from `..adapters.errors`. `__all__` export list.

### Step 2: `regime/models.py`

`Regime` Literal + `REGIMES` tuple; `RegimeFeatures` (frozen, scalar inputs);
`RegimeThresholds` (frozen, bounded `Field`s, defaults from the rules table);
`RegimeClassification` (frozen: `time: datetime` UTC-validated, `timeframe`, `regime`);
`RegimePolicy` (frozen: `regime`, `allowed_strategies: frozenset[str]`,
`size_multiplier: float`, `direction: Literal["long","short","both","none"]`).

### Step 3: `regime/rules.py`

`classify_frame(panel, *, thresholds, timeframe)` — validate required columns
(`RegimeInputError` if missing), derive `ema_fast - ema_slow` via `indicators.ema`, append a
vectorised `regime` Utf8 column (panic-first `when/then` chain). `classify_row(features,
thresholds)` — scalar mirror returning a `Regime`. Helper `_regime_expr(...)` keeps the
public functions ≤ ~50 lines.

### Step 4: `regime/policy.py`

`_POLICY: dict[Regime, RegimePolicy]` built from the `regime-detection.md` table.
`regime_to_strategies`, `regime_to_size_multiplier`, `regime_policy`, `is_no_trade`. Unknown
input → `UnknownRegimeError`.

### Step 5: `regime/__init__.py`

Re-export the public surface.

### Step 6: Config + `.env.example`

Add regime threshold fields to `Settings` (prefix-scoped) and a `regime_thresholds()`
method returning a `RegimeThresholds`. Document the new vars in `.env.example`.

### Step 7: `pyproject.toml`

Add `--cov=src/tfex_s50_multi_tf_swing/regime` to `addopts` and the path to
`[tool.coverage.run] source`.

### Step 8: Tests (`tests/unit/regime/`)

`conftest.py` synthetic per-regime builders; `test_rules.py`, `test_policy.py`,
`test_models_errors.py`.

---

## File Changes

| File | Action | Description |
|---|---|---|
| `src/tfex_s50_multi_tf_swing/regime/__init__.py` | CREATE | Public re-exports |
| `src/tfex_s50_multi_tf_swing/regime/errors.py` | CREATE | `RegimeError` hierarchy |
| `src/tfex_s50_multi_tf_swing/regime/models.py` | CREATE | Pydantic v2 models + `Regime` Literal |
| `src/tfex_s50_multi_tf_swing/regime/rules.py` | CREATE | `classify_frame` + `classify_row` |
| `src/tfex_s50_multi_tf_swing/regime/policy.py` | CREATE | §3.4 policy functions |
| `src/tfex_s50_multi_tf_swing/config/settings.py` | MODIFY | Regime threshold fields + accessor |
| `.env.example` | MODIFY | Document `TFEX_S50_MULTI_TF_SWING_REGIME_*` |
| `pyproject.toml` | MODIFY | Add `regime/` to coverage scope |
| `tests/unit/regime/conftest.py` | CREATE | Synthetic per-regime fixtures |
| `tests/unit/regime/test_rules.py` | CREATE | Classifier tests |
| `tests/unit/regime/test_policy.py` | CREATE | Policy-table tests |
| `tests/unit/regime/test_models_errors.py` | CREATE | Model/error tests |
| `docs/plans/phase-3-regime-detection.md` | CREATE | This plan |
| `docs/plans/ROADMAP.md` | MODIFY | Check off §3.1/§3.4; note §3.2/§3.3 deferred |
| `README.md` | MODIFY | Regime module + new env vars |
| `CLAUDE.md` | MODIFY | Coverage scope incl. `regime/`; thresholds in Settings |
| `.claude/knowledge/regime-detection.md` | MODIFY | Mark rules implemented; record thresholds + input contract |

---

## Test Plan

Deterministic, fixture-driven, no network. Mirrors source layout under `tests/unit/regime/`.

- **`conftest.py`** — builders that produce a panel deterministically classified into each
  regime: a clean uptrend (`trend_up`), downtrend (`trend_down`), compressed low-vol range
  (`range_low_vol`), choppy high-vol range (`range_high_vol`), and a volatility blow-off
  (`panic`). Reuses the `features` conftest style and `build_panel(normalise=False)`.
- **`test_rules.py`** — each fixture classifies to its expected label; panic dominance over
  trend; threshold-boundary behaviour; missing columns / wrong dtype → `RegimeInputError`;
  `classify_row` agrees with `classify_frame` on the same inputs.
- **`test_policy.py`** — parametrised over `REGIMES`: every regime returns a complete
  `RegimePolicy`; size multipliers (`range_low_vol`→0, `panic`→≤0.5, trend/high-vol→1.0);
  `is_no_trade` for no-trade regimes and the lunch zone; unknown regime → `UnknownRegimeError`.
- **`test_models_errors.py`** — `RegimeThresholds` bound validation; `RegimeClassification`
  rejects tz-naive `time`; error classes inherit `TfexS50Error`.

Coverage gate: `--cov-fail-under=90` now also covers `regime/`.

---

## Success Criteria

- [x] `classify_frame` labels a fixture panel using only the 5 regimes, no nulls.
- [x] A low-vol fixture row → `range_low_vol`; a blow-off fixture → `panic`.
- [x] `classify_row` agrees with `classify_frame` row-for-row on shared inputs.
- [x] `regime_policy(r)` is defined for every `r in REGIMES`; unknown raises `UnknownRegimeError`.
- [x] `is_no_trade` is `True` for `range_low_vol`, `panic`, and any lunch-zone bar.
- [x] Thresholds are read from `Settings` / `RegimeThresholds`; none hard-coded at call sites.
- [x] `uv run ruff check . && uv run ruff format --check .` clean.
- [x] `uv run mypy src tests` clean (strict).
- [x] `uv run pytest` green with ≥ 90 % coverage including `regime/`.
- [x] `uv run bandit -r src` and `uv run pip-audit` clean.
- [x] Ingestion contract + Phase 0–2 behaviour unchanged (additive only).

---

## Risks

1. **Synthetic fixtures may not cleanly separate regimes.** Mitigation: construct each
   fixture to satisfy exactly one rule branch and assert thresholds, not magic numbers;
   keep windows small via a test `RegimeThresholds`/`FeatureConfig`.
2. **`rv_percentile` rolling cost** on long 5m series (already flagged in Phase 2). Mitigation:
   `classify_frame` adds no extra rolling pass — it reads the precomputed panel column.
3. **Residual-default choice** (`range_high_vol`) could mislabel sparse early bars where
   features are null. Mitigation: treat null feature rows explicitly (no trade), covered by a
   test.
4. **Threshold drift vs the future LightGBM model.** Mitigation: thresholds are config, and
   the rule labels are documented as the weak-supervision target — refinement is a §3.3 task.

---

## Completion Notes

### Summary

Shipped ROADMAP §3.1 (rule baseline) and §3.4 (policy) as the new leaf package
`src/tfex_s50_multi_tf_swing/regime/` (`errors.py`, `models.py`, `rules.py`, `policy.py`,
`__init__.py`). The classifier consumes the un-normalised Phase 2 feature panel via
`build_regime_inputs`, derives the EMA-level diff with the shared `indicators.ema`, and
labels bars with a panic-first vectorised `when/then` chain. Thresholds live in
`RegimeThresholds`, surfaced on `Settings` (`TFEX_S50_MULTI_TF_SWING_REGIME_*`). Coverage
scope extended to `regime/` in `pyproject.toml`.

### Issues Encountered

1. **`structure` is frequently null** on synthetic series with sparse swing pivots, so the
   full pipeline can't be relied on to emit a specific HH/HL label. Deterministic
   classifier tests build the regime-input frame directly (one row per rule branch); a
   single end-to-end test exercises the `build_regime_inputs` bridge and asserts valid
   labels + multiple regimes, not a specific one.
2. **Null core inputs** (insufficient lookback) are classified `range_low_vol` (the
   no-trade bucket) so trading is never enabled on undefined features.
3. **Pre-existing transitive `pip-audit` advisories** (`idna`, `urllib3`) were cleared with
   a targeted `uv lock --upgrade-package` bump (not introduced by this phase).

### Quality-gate output (2026-05-29)

- `ruff check .` — All checks passed.
- `ruff format --check .` — clean.
- `mypy src tests` — Success: no issues found in 73 source files.
- `pytest` — 251 passed, 5 skipped; total coverage 95.94% (`regime/` 100%); ≥90% gate met.
- `bandit -r src` — 0 issues.
- `pip-audit` — no known vulnerabilities.

---

**Document Version:** 1.1
**Author:** AI Agent (Claude Opus 4.8)
**Status:** Complete
**Completed:** 2026-05-29
