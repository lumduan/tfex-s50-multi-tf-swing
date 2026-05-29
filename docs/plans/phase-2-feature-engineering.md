# Phase 2 — Feature Engineering

**Feature:** TFEX S50 Multi-TF Swing — Phase 2: Feature Engineering
**Branch:** `feature/phase-2-feature-engineering`
**Created:** 2026-05-29
**Status:** In progress
**Depends On:** Phase 0 (Complete), Phase 1 — Data Infrastructure (Complete)

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Design Decisions](#design-decisions)
5. [Feature Catalog](#feature-catalog)
6. [Look-ahead-bias Discipline](#look-ahead-bias-discipline)
7. [Type Contracts](#type-contracts)
8. [Module Layout](#module-layout)
9. [Test Strategy](#test-strategy)
10. [Risks & Edge Cases](#risks--edge-cases)
11. [Verification Checklist](#verification-checklist)
12. [File Changes](#file-changes)
13. [Success Criteria](#success-criteria)
14. [Outcome / Notes](#outcome--notes)

---

## Overview

### Purpose

Phase 2 builds the **causal, multi-timeframe feature panel** (trend, volatility,
time-of-day, market-structure, regime) for SET50 Index Futures, consumed by every
downstream phase (regime detection, HTF bias, signals, ML filter). It consumes the Phase 1
back-adjusted continuous OHLCV (`5m / 1h / 4h`) and the Thai `SessionCalendar`, and emits
per-timeframe feature panels plus a causally-aligned multi-timeframe view.

The edge lives in the features and — critically — in their **look-ahead-free** construction.
No future bar may ever influence a past feature value.

### Parent plan reference

- `docs/plans/ROADMAP.md` §2 — Feature Engineering.
- Per-repo feature spec: `.claude/knowledge/feature-engineering.md`.

### Key deliverables

1. `src/tfex_s50_multi_tf_swing/features/` package — `errors`, `models`, `indicators`,
   `trend`, `volatility`, `time_of_day`, `structure`, `regime`, `align`, `pipeline`,
   `store`, `__init__`.
2. Per-timeframe feature panels materialised to `data/features/<timeframe>.parquet`, plus a
   causally-aligned `data/features/aligned_5m.parquet`.
3. `scripts/build_features.py` owner CLI (continuous parquet → `data/features/`).
4. `notebooks/02_feature_stability.ipynb` scaffold (Thai markdown / English code; full 5-yr
   visual review data-gated like Phase 1's backfill).
5. Unit tests under `tests/unit/features/` ≥ 90% coverage on `features/`, including a
   **look-ahead regression test** and a **multi-timeframe alignment test**.

---

## AI Prompt

The following prompt was used to generate this phase (verbatim):

```
You are a senior quant-platform engineer working inside the `quant-trading-system` umbrella repo. Execute the following end-to-end. Work methodically: understand context first,
  plan, get the plan written to disk, then implement, verify, document, and ship a PR.

  ## Step 0 — Absorb context before touching anything

  Read these docs in full and build a mental model of how the services connect (ingestion contract, Docker network, engine architecture, versioning):

  - `CLAUDE.md` (umbrella system map)
  - `quant-api-gateway/CLAUDE.md` (the gateway that ingests daily reports; note the `POST /api/v1/ingest/daily-report` schema and the `extended_data` escape hatch for TFEX-specific
  fields)
  - `quant-dashboard/CLAUDE.md` (deprecated UI — read only to understand downstream consumers)
  - `quant-infra-db/CLAUDE.md` (Postgres/TimescaleDB + Mongo; `quant-network` ownership)
  - `strategies/csm-set/CLAUDE.md` (the reference strategy — mirror its layering, adapter contract, and quality conventions where applicable)
  - `strategies/tfex-s50-multi-tf-swing/CLAUDE.md` and the entire `strategies/tfex-s50-multi-tf-swing/` tree (existing code from Phase 0/1 — data infrastructure)
  - `strategies/tfex-s50-multi-tf-swing/docs/plans/ROADMAP.md` — **read fully, then focus on the Phase 2 — Feature Engineering section.** Phase 2 is the authoritative scope; the
  ROADMAP defines the exact deliverables, indicators, and acceptance bar. Do not invent scope beyond what Phase 2 specifies, and do not start Phase 3 work.
  - Reuse-first: inventory what Phase 1 already built (data loaders, OHLCV models, settfex/tvkit access, timezone handling) so Phase 2 features consume existing data structures
  rather than re-fetching or duplicating them.

  ## Step 1 — Branch

  Create a new git branch off `main` inside the sub-repo using its existing naming convention (inspect recent branches/tags first; likely `feature/phase-2-feature-engineering` or
  the slug the ROADMAP/CLAUDE.md prescribes). All Phase 2 work lands on this branch.

  ## Step 2 — Plan before code

  Produce a written implementation plan and save it to `strategies/tfex-s50-multi-tf-swing/docs/plans/{phase_name}.md` (use the exact phase slug the ROADMAP uses, e.g.
  `phase-2-feature-engineering.md`). Match the structure of the reference example at `strategies/csm-set/docs/plans/examples/phase1-sample.md`, and **paste this entire prompt
  verbatim into a section of that plan file** (the reference example shows where the originating prompt goes).

  The plan must cover, at minimum:
  - Objective and exact Phase 2 deliverables, quoted/derived from the ROADMAP.
  - The multi-timeframe feature set to engineer (the swing-intraday indicators the ROADMAP names — e.g. trend/momentum/volatility/volume features across the relevant timeframes for
  SET50 futures). Enumerate every feature, its formula/library source, the timeframe(s) it applies to, and its output column/field name.
  - Module/package layout under the strategy repo (e.g. a `features/` package), how it consumes Phase 1 data models, and where the multi-timeframe alignment/resampling lives.
  - Look-ahead-bias prevention: features must be causal (no future leakage); document the windowing/shift discipline explicitly.
  - Type contracts (Pydantic/dataclass models or typed DataFrame schemas) for feature inputs and outputs.
  - Timezone discipline: store UTC, Asia/Bangkok for display; features must be tz-aware end-to-end like csm-set.
  - Test strategy: unit tests for each indicator (known-input/known-output fixtures), multi-timeframe alignment tests, and a look-ahead-bias regression test. Target ≥90% coverage
  on the new feature/`adapters`/`risk` modules per the strategy's quality gate.
  - Risks, edge cases (gaps, half-day sessions, insufficient lookback at series start, NaN handling), and how each is handled.
  - A short verification checklist mirroring the pre-push gate.

  Do not begin coding until the plan file exists on disk and is committed (or at least written) so the design is reviewable.

  ## Step 3 — Implement

  Implement Phase 2 strictly inside `strategies/tfex-s50-multi-tf-swing/` (never edit other sub-repos' history from the umbrella). Engineering bar:

  - **Type safety:** mypy **strict** clean (this service's gate). Full type hints on all public functions; typed feature input/output models.
  - **Async correctness:** if any feature path touches async data access, preserve correct async/await and avoid blocking the event loop with CPU-bound vectorized work where it
  matters; keep heavy numeric computation synchronous/vectorized and isolated.
  - **Numeric correctness:** vectorized pandas/numpy (or the libs Phase 1 already uses); no hidden look-ahead bias; deterministic outputs. Monetary values remain `Decimal` at any
  boundary that reaches the gateway — never `float` for money.
  - **Error handling & logging:** structured logging; validate inputs (sufficient lookback, monotonic timestamps, expected timeframes); fail loudly with actionable messages on
  malformed/insufficient data rather than silently emitting NaN-filled features.
  - **Security:** validate all external/config inputs; no secrets in code (use the sub-repo `.env`, gitignored).
  - **Backward compatibility:** do not break Phase 1 data contracts or the ingestion `extended_data` shape; if Phase 2 features will later feed `extended_data`, keep them additive.
  - **Performance:** prefer vectorized ops over Python loops; note any obvious bottleneck (e.g. recomputing resamples) and avoid redundant recomputation across timeframes.
  - **Tests:** unit + integration as scoped in the plan; meet the ≥90% coverage gate on the new modules. Include at least one explicit look-ahead-bias test and one multi-timeframe
  alignment test.
  - Prefer simple, readable, well-factored solutions over clever ones; match the surrounding code's idioms, naming, and structure (use csm-set as the style reference).

  ## Step 4 — Quality gate (run before any push)

  From inside `strategies/tfex-s50-multi-tf-swing/`, run the full gate exactly as CI does, using `uv run` (never bare `python`/`pip`):

  1. `uv run ruff check .`
  2. `uv run ruff format .` (then `uv run ruff format --check .` — any post-format edit/sed invalidates formatting and must be re-checked)
  3. `uv run mypy` (strict)
  4. `uv run pytest` with coverage, confirming the ≥90% target on the new modules

  All four must pass. If a test fails or a step is skipped, report it honestly with the output; do not claim green when it isn't.

  ## Step 5 — Documentation updates (in the sub-repo)

  When implementation is verified, update:
  - `strategies/tfex-s50-multi-tf-swing/docs/plans/ROADMAP.md` — check off the completed Phase 2 items; add dated notes (today is 2026-05-29) for anything notable, deviations, or
  problems hit during testing.
  - `strategies/tfex-s50-multi-tf-swing/README.md` — update only if behavior/usage changed (new feature module, how to compute/inspect features).
  - `strategies/tfex-s50-multi-tf-swing/CLAUDE.md` — update only if conventions, layout, or commands changed.
  - The plan file from Step 2 — append a brief "Outcome / Notes" section (date, what shipped, any test issues, coverage achieved).

  ## Step 6 — Cross-cutting knowledge (umbrella + repos)

  If Phase 2 produced anything cross-cutting or reusable, create/update it in the appropriate `.claude/*` location:
  - Umbrella `.claude/knowledge/feature-tfex-integration.md` — append Phase 2 feature-engineering decisions (feature catalog, alignment approach, bias-prevention rule) if they
  affect the cross-service picture.
  - Umbrella `.claude/playbooks/` — add/update a playbook only if a repeatable cross-repo workflow emerged.
  - Per-repo `.claude/` notes inside `strategies/tfex-s50-multi-tf-swing/` if strategy-local knowledge warrants it.
  Only write knowledge that is non-obvious and not already captured by code or existing docs.

  ## Step 7 — Commit & PR

  Commit the work on the Phase 2 branch with clear, conventional commit messages (e.g. `feat(tfex): phase 2 feature engineering`, plus separate docs commits if cleaner). Push the
  branch and open a PR against the `tfex-s50-multi-tf-swing` repo's `main` with a description that summarizes the feature set added, the look-ahead-bias guarantees, test/coverage
  results, and links the Phase 2 plan file. Do not merge — leave it for review.

  ## Constraints & reporting

  - Touch only `strategies/tfex-s50-multi-tf-swing/` for code; umbrella `.claude/*` and umbrella docs only for cross-cutting knowledge. Never rewrite other sub-repos' history.
  - Surface any ambiguity in the ROADMAP's Phase 2 scope before guessing; if a documented detail contradicts the existing code, flag it rather than silently working around it.
  - At the end, report: branch name, plan file path, list of files changed, the exact quality-gate output (pass/fail per step + coverage %), and the PR URL.
```

---

## Scope

### In scope (Phase 2, per ROADMAP §2.1–2.6)

| Component | ROADMAP | Status |
|---|---|---|
| Trend features (`ema_slope`, `structure`, `dist_from_vwap`) | §2.1 | — |
| Volatility features (`atr_ratio`, `bollinger_squeeze`, `realised_vol`) | §2.2 | — |
| Time-of-day features (`opening_range`, `lunch_zone_flag`, `close_auction_flag`, `session_phase`) | §2.3 | — |
| Market-structure features (`overnight_gap`, `dist_to_prev_high/low`, `initial_balance`, `liquidity_sweep_flag`) | §2.4 | — |
| Regime features (`rv_percentile`, `trend_persistence`, `range_compression`, `volume_expansion`) | §2.5 | — |
| Feature pipeline (combine → winsorise 1/99 → trailing z-score → panel) | §2.6 | — |
| Multi-timeframe causal as-of alignment utility + aligned panel | task req | — |
| `scripts/build_features.py`, stability notebook scaffold | derived | — |

### Out of scope (later phases)

- Regime *classification* (rule-based / LightGBM) — Phase 3.
- HTF bias engine — Phase 4. Signals / execution / risk — Phases 5+.
- The full 5-year stability visual review (data-gated on a real `TVKIT_AUTH_TOKEN`).

---

## Design Decisions

1. **Polars, not pandas.** Phase 1 is entirely Polars (`polars>=1.4`) + PyArrow. All feature
   math uses Polars expressions (`ewm_mean`, `rolling_*`, `over`, `join_asof`). The brief's
   generic "pandas/numpy" yields to "the libs Phase 1 already uses".
2. **Feature dtype = Float64.** Features are statistical (slopes, ratios, z-scores) and never
   cross the gateway boundary, so the `Decimal`-for-money rule does not apply. Flags are
   `Int8`, categoricals (`session_phase`, `structure`) are `Utf8`. This matches
   `continuous.py`'s established Decimal→Float64→… arithmetic idiom. Prices read from the
   store are cast Decimal→Float64 at the feature boundary.
3. **Input is the back-adjusted continuous series** (CLAUDE.md hard rule #3) so slopes/ratios
   never see rollover gaps.
4. **Reuse `SessionCalendar`** for all time-of-day/session logic — no re-derivation.
5. **Bars are open-labelled.** Confirmed in `data/fetcher.py::_bars_to_frame`
   (`time = datetime.fromtimestamp(bar.timestamp)`). An HTF bar `time=t` only *closes* at
   `t + TIMEFRAME_MINUTES[tf]`; alignment keys off that availability time.
6. **MTF alignment materialises an aligned 5m view** in addition to per-TF panels.

---

## Feature Catalog

Window defaults are configurable via `FeatureConfig`; representative values shown. All
output columns are Float64 unless marked. TFs: `5m / 1h / 4h` unless restricted.

### Trend (`trend.py`)

| Feature | Formula / source | TFs | Output column(s) |
|---|---|---|---|
| `ema_slope_{n}` | `(EMA_t − EMA_{t−n}) / n ÷ ATR_t`; `ewm_mean(span=n)` | all | `ema_slope_20`, `ema_slope_50` |
| `structure` | HH/HL/LH/LL from **confirmed** swing pivots (lookback `k`; label shifted `+k`) | all | `structure` (Utf8) |
| `dist_from_vwap` | `(close − session_VWAP) / ATR`; VWAP resets per Thai session | all | `dist_from_vwap` |

### Volatility (`volatility.py`)

| Feature | Formula / source | TFs | Output column(s) |
|---|---|---|---|
| `atr_ratio` | `ATR_short / ATR_long` (Wilder ATR, trailing) | all | `atr_ratio` |
| `bollinger_squeeze` | BB width `(2·k·σ)` ÷ Keltner width `(2·m·ATR)`; `<1` ⇒ squeeze | all | `bollinger_squeeze` |
| `realised_vol_{h}` | rolling std of log returns × √annualisation | all | `realised_vol_{h}` |

### Time-of-Day (`time_of_day.py`)

| Feature | Formula / source | TFs | Output column(s) |
|---|---|---|---|
| `opening_range_{w}` | high/low of first `w` min after session open | 5m,1h | `or_high_{w}`, `or_low_{w}` (w∈15,30,60) |
| `lunch_zone_flag` | `SessionCalendar.is_lunch_dead_zone` | all | `lunch_zone_flag` (Int8) |
| `close_auction_flag` | last 15m of afternoon session | all | `close_auction_flag` (Int8) |
| `session_phase` | `SessionCalendar.time_of_day_bucket` | all | `session_phase` (Utf8) |

### Market Structure (`structure.py`)

| Feature | Formula / source | TFs | Output column(s) |
|---|---|---|---|
| `overnight_gap` | `(session_open − prev_session_close) / ATR` | all | `overnight_gap` |
| `dist_to_prev_high/low` | `(close − prev_day_H/L) / ATR` (strictly prior session) | all | `dist_to_prev_high`, `dist_to_prev_low` |
| `initial_balance_high/low` | first-hour extremes | 5m,1h | `ib_high`, `ib_low` |
| `liquidity_sweep_flag` | pierce recent swing H/L then reverse within `k` bars; emitted at `t+k` | all | `liquidity_sweep_flag` (Int8) |

### Regime (`regime.py`)

| Feature | Formula / source | TFs | Output column(s) |
|---|---|---|---|
| `rv_percentile` | rolling N-day percentile rank of `realised_vol` (trailing) | all | `rv_percentile` |
| `trend_persistence` | rolling sign-agreement of returns | all | `trend_persistence` |
| `range_compression` | low `atr_ratio` ∧ low ADX flag | all | `range_compression` (Int8) |
| `volume_expansion` | volume z-score over trailing session window | all | `volume_expansion` |

---

## Look-ahead-bias Discipline

1. **Trailing windows only** — every `rolling_*` ends at the current row; never `center=True`.
   `ewm_mean` is causal by construction. Including the current bar in its own normalisation
   is causal (the bar is known at close).
2. **Confirmation lag is shifted forward** — features needing future bars to confirm
   (`structure` pivots, `liquidity_sweep_flag`) are emitted only at `t+k` via `.shift(k)`.
3. **Prev-session references are strictly prior** — `overnight_gap`, `dist_to_prev_*` use
   shifted session aggregates, never the still-forming current session.
4. **Normalisation is local & trailing** — winsorise (1/99) + z-score on a trailing window,
   never global.
5. **MTF alignment keys off availability time** — `available_at = time + duration`, then
   `join_asof(strategy="backward")`. No HTF bar leaks before it closes.
6. **Leading nulls are kept, not filled** — insufficient-lookback rows stay null; filling
   would inject look-ahead or fabricate data.

---

## Type Contracts

- `FeatureConfig(BaseModel, frozen=True)` — all window/period params with validated defaults.
- Feature-column **registry** in `features/models.py` — maps every output column → dtype →
  producing module → TF applicability; drives the Parquet schema and output validation.
- Input guard `_require_ohlcv(df)` — tz-aware UTC `time`, strictly monotonic, no duplicate
  timestamps, required columns present, `len ≥ max_window` else `InsufficientLookbackError`.
- Panel I/O through Polars frames validated against the registry before write.

---

## Module Layout

```
src/tfex_s50_multi_tf_swing/features/
  __init__.py     errors.py     models.py     indicators.py
  trend.py        volatility.py time_of_day.py structure.py
  regime.py       align.py      pipeline.py    store.py
```

One-way dependency `data/ → features/`; `features/` never imports `api/`. Tests mirror under
`tests/unit/features/`.

---

## Test Strategy

- `test_indicators.py` — primitives vs hand-computed fixtures.
- `test_trend.py` / `test_volatility.py` / `test_time_of_day.py` / `test_structure.py` /
  `test_regime.py` — known-input/known-output per feature.
- `test_align.py` — MTF alignment: 5m row at `t` sees only the most-recent *closed* HTF
  feature; no future leak.
- `test_pipeline.py` — panel assembly + winsor + trailing z-score; **look-ahead regression
  test**: features on the full series equal features on every truncated prefix for
  overlapping rows.
- `test_store.py` — feature parquet round-trip + schema enforcement.
- `test_errors.py` — insufficient lookback / malformed input raise correctly.

Coverage: add `--cov=src/tfex_s50_multi_tf_swing/features` to `pyproject.toml` (`addopts` +
`[tool.coverage.run].source`), keep `--cov-fail-under=90`.

---

## Risks & Edge Cases

| Risk / edge case | Handling |
|---|---|
| Session gaps / half-days / holidays | Session-anchored features key off `SessionCalendar`; short windows → leading nulls, not errors |
| Insufficient lookback at series start | Leading rows null until window fills; whole-frame-too-short raises `InsufficientLookbackError` |
| NaN discipline | Never fill; nulls explicit and tested |
| Rollover boundaries | Run on back-adjusted continuous so ratios/slopes see no roll gap; stability notebook eyeballs (data-gated) |
| Bar-label convention | Verified open-labelled in fetcher; alignment shift = full duration |
| Float determinism | Polars `ewm`/`rolling` deterministic; fixtures assert exact / `isclose` |

---

## Verification Checklist

1. `uv run ruff check .`
2. `uv run ruff format --check .`
3. `uv run mypy src tests`
4. `uv run pytest` — coverage ≥ 90% on `features/`
5. `uv run python scripts/build_features.py` writes `data/features/<tf>.parquet` +
   `aligned_5m.parquet` with no NaN-filled columns.
6. Look-ahead regression + MTF alignment tests pass.

---

## File Changes

| File | Action |
|---|---|
| `src/tfex_s50_multi_tf_swing/features/*.py` (12 modules) | CREATE |
| `tests/unit/features/*.py` | CREATE |
| `scripts/build_features.py` | CREATE |
| `notebooks/02_feature_stability.ipynb` | CREATE |
| `pyproject.toml` | MODIFY (coverage scope) |
| `docs/plans/ROADMAP.md` | MODIFY (tick-offs + notes) |
| `docs/plans/phase-2-feature-engineering.md` | CREATE (this doc) |
| `README.md` / `CLAUDE.md` | MODIFY if usage/layout changed |

---

## Success Criteria

- [ ] All ROADMAP §2.1–2.6 features implemented with unit tests.
- [ ] Per-TF panels + aligned 5m panel materialise under `data/features/`.
- [ ] Look-ahead regression test + MTF alignment test pass.
- [ ] `uv run mypy src tests` strict clean; ruff clean; ≥90% coverage on `features/`.
- [ ] Plan committed before code; PR opened (not merged).

---

## Outcome / Notes

_To be completed after implementation (date, what shipped, test issues, coverage achieved)._
