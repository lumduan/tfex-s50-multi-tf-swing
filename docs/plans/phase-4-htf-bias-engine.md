# Phase 4: Higher-Timeframe Bias Engine (4H)

**Feature:** `feature-tfex-integration` — Intelligence Layer, Higher-Timeframe Bias
**Branch:** `feature/phase-4-htf-bias-engine`
**Created:** 2026-06-03
**Status:** Complete
**Completed:** 2026-06-03
**Depends On:** Phase 1 — Data Infrastructure (✓), Phase 2 — Feature Engineering (✓),
Phase 3 — Regime Detection (✓)

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Design Decisions](#design-decisions)
5. [Bias Rules](#bias-rules)
6. [Implementation Steps](#implementation-steps)
7. [File Changes](#file-changes)
8. [Test Plan](#test-plan)
9. [Success Criteria](#success-criteria)
10. [Risks](#risks)
11. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 4 adds the **Intelligence Layer's higher-timeframe bias engine**: a deterministic,
rule-based filter that materialises **one directional bias** — `long` / `short` / `neutral` —
**per 4H bar**. Its sole job is to **veto counter-trend trades** before any setup is
considered downstream. The bias engine **only filters; it never generates trades** (a hard
rule from the ROADMAP — "The bias engine *vetoes* trades; it does not generate them.").

This phase ships ROADMAP **§4.1 (4H trend filter)** and **§4.2 (bias output + visualisation)**.
**§4.3 (before/after backtest)** is delivered as a self-contained demonstration and the full
end-to-end exit metric is deferred to Phase 5 (the signal layer it depends on does not exist
yet) — see Design Decision D9.

The new package `bias/` is a pure offline library leaf — **no FastAPI endpoint, no gateway
`extended_data` change, no `risk/` wiring** (those packages belong to Phases 5 / 7). It mirrors
the Phase 3 `regime/` package patterns exactly.

### Parent Plan Reference

- `docs/plans/ROADMAP.md` → **Phase 4 — Higher-Timeframe Bias Engine (4H)**
- `docs/plans/phase-3-regime-detection.md` (the package shape this phase mirrors)
- `.claude/knowledge/strategy-design.md` / `.claude/knowledge/regime-detection.md`

### Key Deliverables

1. **`src/tfex_s50_multi_tf_swing/bias/errors.py`** — `BiasError` hierarchy under
   `TfexS50Error`.
2. **`src/tfex_s50_multi_tf_swing/bias/models.py`** — `BiasDirection` Literal, `BiasSignal`,
   `BiasConfig`, `BiasFeatures` (Pydantic v2, frozen).
3. **`src/tfex_s50_multi_tf_swing/bias/htf.py`** — `build_bias_inputs()`, `classify_frame()`
   (vectorised), `classify_row()` (scalar), `to_signals()`.
4. **`src/tfex_s50_multi_tf_swing/bias/__init__.py`** — public re-exports.
5. **Config** — bias deadbands on `Settings` (`TFEX_S50_MULTI_TF_SWING_BIAS_*`),
   `.env.example` updated; coverage gate extended to `bias/`.
6. **§4.2 visualisation + §4.3 demonstration** — `scripts/visualise_bias.py`,
   `scripts/bias_counter_trend_demo.py`, `notebooks/04_htf_bias.ipynb` (public-safe artifacts).
7. **Tests** — `tests/unit/bias/`, ≥ 90 % coverage on `bias/` (target 100 %).

---

## AI Prompt

The following prompt initiated this phase. It is embedded verbatim so the plan is
self-contained.

```
🎯 OBJECTIVE
Implement Phase 4 — Higher-Timeframe Bias Engine (4H) of the
strategies/tfex-s50-multi-tf-swing quant strategy. Build a new leaf package
src/tfex_s50_multi_tf_swing/bias/ that materialises a per-4H-bar directional
bias (long / short / neutral) used to veto counter-trend trades. The bias
engine ONLY filters — it never generates trades. Plan first, then code, then
docs, then a PR.

You are Claude Code working inside the umbrella repo at
/home/batt/docker/quant-trading-system, but ALL code changes for this task live
in the independent sub-repo strategies/tfex-s50-multi-tf-swing/ (its own git
remote github.com/lumduan/tfex-s50-multi-tf-swing). cd into that sub-repo for
all git operations; never edit sub-repo history from the umbrella.

STEP 0 — READ BEFORE TOUCHING ANYTHING (do not skip)
Read and internalise, in this order:
1. CLAUDE.md (umbrella system map).
2. strategies/tfex-s50-multi-tf-swing/CLAUDE.md (the strategy's hard rules,
   layering, coding conventions, market-data-source rule).
3. strategies/tfex-s50-multi-tf-swing/docs/plans/ROADMAP.md — read the whole
   "Market data source — the Market Data Engine" section AND "## Phase 4 —
   Higher-Timeframe Bias Engine (4H)" verbatim; this is the canonical spec.
4. strategies/tfex-s50-multi-tf-swing/docs/plans/phase-3-regime-detection.md
   and the existing src/tfex_s50_multi_tf_swing/regime/ package
   (errors.py, models.py, rules.py, policy.py, __init__.py) — Phase 4
   consumes regime output and MUST follow the exact same patterns.
5. strategies/tfex-s50-multi-tf-swing/src/tfex_s50_multi_tf_swing/features/
   (esp. trend.py for ema_slope_* / structure, volatility.py, the
   panel builder and FeatureConfig) — bias consumes the un-normalised
   feature panel exactly as the regime layer does (FeatureConfig(normalise=False)),
   because z-scored ema_slope_* / dist_from_vwap destroy the absolute signs
   the bias rules need.
6. strategies/tfex-s50-multi-tf-swing/.claude/knowledge/regime-detection.md,
   strategy-design.md, strategy-overview.md, feature-engineering.md.
7. Plan-file FORMAT reference (mirror its section structure exactly):
   strategies/csm-set/docs/plans/examples/phase1-sample.md.

Recon, don't assume: confirm the real public API of regime/ and features/
(function names, RegimeThresholds, the five regime literals, the
shared TfexS50Error base + per-subpackage errors.py pattern) before you
design bias/. Match the surrounding code's idiom, naming, comment density,
and file/function size limits (≤400 lines/file, ≤~50 lines/function).

STEP 1 — BRANCH
In strategies/tfex-s50-multi-tf-swing/, create and switch to a new branch off
the current default branch:
    feature/phase-4-htf-bias-engine

STEP 2 — WRITE THE PLAN FIRST (before any implementation code)
Author the phase plan at:
    strategies/tfex-s50-multi-tf-swing/docs/plans/phase-4-htf-bias-engine.md

Follow the section layout of strategies/csm-set/docs/plans/examples/phase1-sample.md
(Overview, AI Prompt, Scope [in/out], Design Decisions, Implementation Steps,
File Changes, Success Criteria, Completion Notes). Requirements for the plan doc:
- Header block: Feature, Branch (feature/phase-4-htf-bias-engine), Created date
  (today, 2026-06-03), Status, Depends On (Phase 1 ✓, Phase 2 ✓, Phase 3 ✓).
- An "AI Prompt" section containing THIS prompt verbatim (the whole text you
  are reading), inside a fenced block — per the user's instruction.
- Design Decisions must explicitly resolve the open questions below (D-items).
- docs/plans/ is git-tracked — never gitignore it; the roadmap is product.

STEP 3 — IMPLEMENT (per ROADMAP §4.1–4.3)
New package src/tfex_s50_multi_tf_swing/bias/ (leaf, one-way dependency
features/ + regime/ → bias/; bias MUST NOT import from api/, signals/,
execution/, risk/, or backtest/). Create at minimum:
  - bias/errors.py — BiasError (or analogous) inheriting the shared
    TfexS50Error base; module-local exceptions only. Never raise Exception,
    never except Exception: pass.
  - bias/models.py — the BiasSignal Pydantic model (frozen), with
    direction: Literal["long", "short", "neutral"] and reasons: list[str]
    (human-auditable reason strings, one per failed/passed gate). Add any
    config model (frozen Pydantic, e.g. BiasConfig) for tunable thresholds;
    thresholds live ONLY in config (overridable via TFEX_S50_MULTI_TF_SWING_*
    env + Settings), never hard-coded at a call site — mirror how
    regime/ does RegimeThresholds.
  - bias/htf.py — the 4H trend filter implementing ROADMAP §4.1:
      • ema20_above_ema50 → long lean / ema20_below_ema50 → short lean
      • positive vs negative EMA slope agreement
      • HH/HL (long) vs LH/LL (short) market-structure check
      • price relative to HTF VWAP (dist_from_vwap sign)
      • volatility-healthy gate: bias is neutral when the 4H regime is panic
        or range_low_vol (the no-trade regimes) — reuse regime/ classification,
        do NOT re-derive regime logic.
    Provide a vectorised classify_frame-style entry point that emits one
    BiasSignal per 4H bar (Polars-native, look-ahead-free: trailing-only
    windows, confirmation lag preserved, no center windows, prices cast
    Decimal→Float64 at the feature boundary) AND a scalar/per-row helper,
    matching the classify_frame() / classify_row() shape in regime/.
  - bias/__init__.py — public re-exports (the BiasSignal, the entry points,
    the config/errors), matching the regime package's __init__.py style.
- ROADMAP §4.2 "CLI/notebook to visualise bias overlaid on 4H chart": add a
  thin script (e.g. scripts/visualise_bias.py) and/or a notebook under
  notebooks/ that overlays bias direction on the 4H continuous series. Keep
  plotting/IO out of src/ (library core stays pure).

STEP 4 — THE 4H DATA-SOURCE CONSTRAINT (read carefully — this is the crux)
The bias engine consumes 4h bars. Per the ROADMAP and CLAUDE.md:
- The canonical engine OHLCV source (quant-marketdata-engine via the
  gateway proxy) serves only 1d | 1h | 5m (cagg_ohlcv_4h is unrouted; no local
  rollup — Decision D10).
- 4h is therefore available only on the mirror source today. This is the
  one place tfex is blocked from running fully on the engine source.
You MUST:
  - Make bias/ SOURCE-AGNOSTIC: it consumes already-loaded 4H OHLCV / feature
    / regime frames (offline Parquet data/continuous/4h.parquet + the Phase 2
    panel). It must NOT call tvkit, must NOT own a cookie, and must NOT itself
    pick a fetcher — that selection stays in data/sources.py. tfex NEVER fetches
    tvkit and NEVER owns the TradingView cookie (the engine is the sole owner).
  - Where any caller-facing path could request 4h from the engine source,
    surface the existing typed EngineTimeframeUnavailableError cleanly with a
    pointer that 4h is mirror-only until the engine ships a 4h route — DO NOT
    silently roll up 4h locally and DO NOT fall back to tvkit.
  - Document, in both the plan and the ROADMAP/CLAUDE.md update, that the engine
    4h route is the unblocker (then a one-line change to
    data/engine_fetcher.py:_TF_TO_ENGINE) — but implementing that engine route
    is OUT OF SCOPE for this strategy PR (it's a quant-marketdata-engine change).

STEP 5 — §4.3 BACKTEST OF BIAS FILTER (scope honestly)
ROADMAP §4.3 wants a before/after comparison and the exit criterion is
"≥ 30% reduction in counter-trend entries vs the unfiltered baseline." But the
signals/, execution/, risk/, and backtest/ packages do not exist yet
(later phases). Stay ROADMAP-pure, exactly as Phase 3 did:
- Implement a self-contained demonstration that does NOT require the unbuilt
  layers: e.g. a notebook/script that takes the 4H bias series + a naive
  rule-based candidate-entry proxy on the existing feature panel, and produces
  the counter-trend-reduction histogram / metric, saved to a tracked,
  public-safe artifact (no raw OHLCV columns leaked — respect the public data
  boundary; data/ is gitignored, proprietary feature vectors never land in
  results/static/ or API responses).
- If a faithful end-to-end backtest genuinely cannot be done until the signal
  layer lands, mark §4.3 as a deferred sub-task in the ROADMAP with an explicit
  "blocked-on Phase N" note and completion-note rationale (mirror the Phase 3
  deferral style). Decide and justify in the plan's Design Decisions; do not
  fake a backtest.

QUALITY BAR (non-negotiable — matches CI)
- Strict typing: from __future__ import annotations at the top of every src/
  module; mypy strict clean (uv run mypy src tests). Pydantic at all
  boundaries; no raw dicts crossing module/external boundaries.
- Async-first I/O if any HTTP is touched (httpx.AsyncClient; requests
  forbidden in src/). Bias is pure compute, so likely no I/O — keep it that way.
- Structured logging: logger = logging.getLogger(__name__), %-formatting,
  never print in src/.
- Look-ahead-free by construction (trailing-only windows, confirmation lag,
  strictly-prior session refs). Timezone: store UTC / display Asia/Bangkok,
  tz-aware end-to-end; never mix tz-naive and tz-aware in one frame.
- Tests mirror source layout (tests/unit/bias/ ↔ src/.../bias/). Unit tests
  on hand-labelled synthetic 4H series asserting each gate (EMA cross, slope,
  structure, VWAP side, panic/range_low_vol → neutral) and the composed
  BiasSignal.direction + reasons. Handle the known gotcha that structure
  (HH/HL/LH/LL) is frequently null on sparse-pivot synthetic series — build bias
  input frames per-branch deterministically where needed, and define the
  neutral-on-null-core-input behaviour (insufficient lookback ⇒ neutral, never
  a directional bias).
- Coverage ≥ 90% enforced; extend the coverage gate to include bias/
  (regime/ shipped at 100% on the new module — aim for the same). Edge cases:
  empty/short frames, all-null features, exactly-equal EMAs (tie → neutral),
  conflicting gates (slope vs structure disagree → neutral with reasons).
- Conventional Commits (feat(bias): …, docs(bias): …, test(bias): …).
- Run the full combined gate BEFORE every push (and re-run after ANY post-format
  edit/sed, since that invalidates formatting):
    uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest
  Everything via uv run — never bare python/pip.

STEP 6 — DOCS, KNOWLEDGE & CONTEXT UPDATES
Update only what is genuinely affected; keep single-source-of-truth:
- docs/plans/ROADMAP.md: tick §4.1/§4.2/§4.3 checkboxes for what shipped, mark
  deferrals, and add a dated "Notes (2026-06-03)" block in the Phase 4 section.
- CLAUDE.md: add a concise "Phase 4 — bias layer" subsection under Architecture
  (the one-way features/ + regime/ → bias/ dependency, that bias VETOES and
  never generates, the un-normalised-panel requirement, and the 4h mirror-only
  constraint). Update "Where to look next" and the coverage-gate module list.
- .claude/knowledge/: add a new bias-engine.md OR fold into strategy-design.md
  — pick one and justify in the plan.
- Umbrella CLAUDE.md and .claude/*: update ONLY if something cross-cutting
  changed. The strategy's own Phase 4 is distinct from feature-market-data-engine
  Phase 4 — do not conflate them.
- Honour the persistent memory conventions for this workspace.

STEP 7 — COMMIT & PR
- Commit in strategies/tfex-s50-multi-tf-swing/ with Conventional Commit
  messages, ending the commit message with:
      Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
- Push the branch and open a PR via gh against the sub-repo's default branch.
  PR body ends with:
      🤖 Generated with [Claude Code](https://claude.com/claude-code)
- After the push/PR, report the result as an ASCII box-drawing table, one row
  per repo, with columns: Repo | Branch | Commit | GitHub.

DEFINITION OF DONE
1. bias/ package implemented per §4.1–4.2, BiasSignal contract live, one
   BiasSignal materialised per 4H bar.
2. 4h-source constraint handled exactly as specified (mirror-only, engine
   declines cleanly, no local rollup, no tvkit).
3. §4.3 demonstrated within current scope or explicitly deferred with rationale.
4. uv run ruff check . && uv run ruff format --check . && uv run mypy src tests
   && uv run pytest all green; bias/ coverage ≥ 90% (target 100%), coverage gate
   extended to bias/.
5. Plan file authored (with this prompt embedded), ROADMAP + CLAUDE.md +
   knowledge updated; umbrella touched only if cross-cutting.
6. Branch committed, pushed, PR opened, result reported as the ASCII box table.
```

---

## Scope

### In Scope (Phase 4 — §4.1 + §4.2 + a §4.3 demonstration)

| Component | Description | Status |
|---|---|---|
| `BiasError` hierarchy | Module-local exceptions under `TfexS50Error` | Complete |
| `BiasDirection` Literal | `long` / `short` / `neutral` | Complete |
| `BiasSignal` | Frozen Pydantic `(direction, reasons)` | Complete |
| `BiasConfig` | Frozen Pydantic deadbands + `neutral_regimes`, env-overridable | Complete |
| `BiasFeatures` | Frozen Pydantic scalar inputs for single-bar classification | Complete |
| `build_bias_inputs()` | Bridge: continuous OHLCV → bias-input frame (reuses `regime/`) | Complete |
| `classify_frame()` | Vectorised Polars classifier; appends `bias_direction` + `bias_reasons` | Complete |
| `classify_row()` | Scalar classifier from `BiasFeatures` → `BiasSignal` | Complete |
| `to_signals()` | One `BiasSignal` per 4H bar from a classified frame | Complete |
| Settings + `.env.example` | `TFEX_S50_MULTI_TF_SWING_BIAS_*` deadbands + `bias_config()` | Complete |
| §4.2 visualisation | `scripts/visualise_bias.py` + `notebooks/04_htf_bias.ipynb` | Complete |
| §4.3 demonstration | `scripts/bias_counter_trend_demo.py` (public-safe metric) | Complete |
| Test suite | `tests/unit/bias/`, ≥ 90 % coverage | Complete |

### Out of Scope (deferred to later phases)

- **§4.3 end-to-end exit metric** (≥ 30 % counter-trend reduction vs the *real* unfiltered
  strategy, full trade histogram) — requires `signals/` + `execution/` + `backtest/`
  (Phases 5 / 8), which do not exist. Shipped as a self-contained **demonstration** on a naive
  candidate-entry proxy; the full metric is **deferred → blocked-on Phase 5**. See D9.
- **Engine `4h` route** — a `quant-marketdata-engine` change. Bias documents it as the
  unblocker (one-line `_TF_TO_ENGINE` edit) but does not implement it. See D8.
- **FastAPI endpoint / gateway `extended_data` threading / `risk/` wiring** — the `api/`,
  `signals/`, and `risk/` packages do not exist; they belong to Phases 5 / 7. `bias/` is the
  veto contract those phases will consume.

---

## Design Decisions

### D1 — `bias/` is a leaf fed by the un-normalised panel + regime output

`bias/` sits at `data/ → features/ → regime/ → bias/` (the data flow in `CLAUDE.md`). It
imports from `features/` and `regime/` but nothing downstream (`api/`, `signals/`,
`execution/`, `risk/`, `backtest/`). The classifier consumes a per-timeframe panel built with
**`FeatureConfig(normalise=False)`** — exactly like `regime/` — because the normalised panel
z-scores `ema_slope_*` and `dist_from_vwap` against a trailing window, destroying the absolute
signs the gates depend on. It **reuses** `regime.build_regime_inputs` + `regime.classify_frame`
for the volatility-healthy gate rather than re-deriving regime logic.

### D2 — Composition is conservative unanimity (mirrors regime's `trend_up` AND-rule)

A **long** bias requires ALL of: `ema_fast > ema_slow` AND `ema_slope_fast > slope_deadband`
AND `structure ∈ {HH, HL}` AND `dist_from_vwap > vwap_deadband` AND `regime ∉ neutral_regimes`.
**short** is the exact mirror (all `<`, `structure ∈ {LH, LL}`). Anything else → **neutral**.
This keeps the engine "boring, conservative, engineered to survive" (a hard design rule) and
means any gate disagreement yields neutral-with-reasons rather than a directional guess.

### D3 — Neutral on null / tie (never a directional guess)

Null `structure` (insufficient swing pivots / lookback), a tie EMA (`ema_fast == ema_slow`),
or a slope/VWAP magnitude inside the deadband fail their gate → unanimity breaks → `neutral`.
Insufficient lookback ⇒ `neutral`, never a directional bias. Explicitly tested. This mirrors
the regime layer's "null core inputs ⇒ no-trade bucket" discipline.

### D4 — Volatility-healthy gate reuses `regime/`

When the 4H regime is `panic` or `range_low_vol` (the two no-trade regimes), bias is forced
`neutral` regardless of the trend gates, with reason `"regime=<r> → veto"`. `neutral_regimes`
defaults to `("panic", "range_low_vol")` on `BiasConfig`. Regime is computed once via
`regime.classify_frame`, never re-derived.

### D5 — Thresholds live in one frozen config object, env-overridable

`BiasConfig` (frozen Pydantic) holds `slope_deadband: float = 0.0 (ge=0)`,
`vwap_deadband: float = 0.0 (ge=0)`, and `neutral_regimes: tuple[Regime, ...] =
("panic", "range_low_vol")`. The two numeric deadbands are surfaced on `Settings` via
`TFEX_S50_MULTI_TF_SWING_BIAS_SLOPE_DEADBAND` / `_BIAS_VWAP_DEADBAND` and a `bias_config()`
accessor (lazy import, mirroring `regime_thresholds()`). No threshold is hard-coded at a call
site. The deadbands default to `0.0` so the baseline rule is a strict sign test; a non-zero
deadband adds a noise band before a gate votes directionally.

### D6 — Two entry points + per-bar `BiasSignal` (mirrors regime)

`classify_frame(df, *, config)` is the primary API — one vectorised, look-ahead-free Polars
pass that appends a `bias_direction` (Utf8) column and a `bias_reasons` (`List[Utf8]`) column.
It reuses already-causal panel/regime columns (no new rolling window, no `center` window).
`classify_row(features, config)` classifies a single bar from a `BiasFeatures` model and
returns a `BiasSignal`. `to_signals(frame)` materialises one `BiasSignal` per 4H bar from a
classified frame.

### D7 — `BiasSignal` is exactly `direction` + `reasons` (per spec), frozen

`BiasSignal` carries only `direction: BiasDirection` and `reasons: list[str]`, per the ROADMAP
§4.2 contract. `reasons` records one human-auditable string per gate
(e.g. `"ema_fast>ema_slow → long"`, `"structure=HH → long"`, `"slope +0.80>0 → long"`,
`"price>vwap → long"`, or on a veto `"regime=panic → veto"`), so a human can read exactly why a
bar got its label. Per-bar `time` lives on the classified *frame* (the `time` column), not on
the scalar signal — matching how `regime.classify_frame` appends a column while the scalar API
returns a label.

### D8 — Bias is source-agnostic; the 4H decline stays in the data layer

`bias/` never calls tvkit / the engine / a fetcher and owns no cookie. The existing
`data/engine_fetcher.py:engine_timeframe()` already raises `EngineTimeframeUnavailableError`
for `4h` **before any I/O** (`_TF_TO_ENGINE = {"5m": "5m", "1h": "1h"}`, Decision D10 forbids a
local rollup). Bias relies on that typed decline and adds **no fallback and no local rollup**.
Offline inputs come from `data/continuous/4h.parquet` (mirror source) + the Phase 2 panel.
**The unblocker is an engine `4h` route** → then a one-line change to `_TF_TO_ENGINE`. That
engine route is a `quant-marketdata-engine` change and is **OUT OF SCOPE** for this strategy PR.
Until then, `4h` is **mirror-only** — the one place tfex's roadmap is blocked from running fully
on the canonical engine source.

### D9 — §4.3 backtest: deferred-with-demonstration (mirrors Phase 3's deferral honesty)

A faithful before/after counter-trend backtest needs the `signals/`, `execution/`, and
`backtest/` packages, none of which exist (Phases 5 / 8). Rather than fake a backtest, this
phase ships a **self-contained demonstration**: `scripts/bias_counter_trend_demo.py` derives a
**naive rule-based candidate-entry proxy** from the existing feature panel (e.g. EMA-slope-sign
entries), applies the bias veto, and computes the **counter-trend-entry reduction %**. It saves
a **public-safe** artifact (direction / veto / candidate counts only — **NO raw OHLCV
columns**) to `results/static/bias/`. The full ROADMAP §4.3 exit metric (histogram, ≥ 30 %
reduction vs the *real* unfiltered strategy) is **deferred → blocked-on Phase 5** with an
explicit ROADMAP note. The demonstration shows the *mechanism* works (the veto removes the
counter-trend slice); the *magnitude* claim awaits real signals.

### D10 — Bias docs get their own `.claude/knowledge/bias-engine.md`

A new `bias-engine.md` (not folded into `strategy-design.md`) mirrors how the regime layer got
its own `regime-detection.md`. It is the single-source-of-truth for gate definitions,
thresholds, the `BiasSignal` contract, and the 4h mirror-only caveat — discoverable from the
"Where to look next" list in `CLAUDE.md`.

### D11 — Umbrella repo untouched

This strategy's Phase 4 (HTF Bias Engine) is distinct from `feature-market-data-engine` Phase 4
(the reader cutover). Nothing cross-cutting changed, so the umbrella `CLAUDE.md` / `.claude/*`
and the workspace auto-memory are left as-is. The pre-push checklist, "re-format after any
edit/sed", and host-port memories already cover this work.

### D12 — Features are `float`, not `Decimal`

Bias inputs are internal statistical quantities that never cross the gateway boundary, so the
Decimal-for-money rule does not apply (consistent with the Phase 2 / Phase 3 layers). Prices
read from the store are cast Decimal→Float64 at the feature boundary by the reused
`build_regime_inputs` bridge.

---

## Bias Rules

Encoded in `htf.py`; thresholds from `BiasConfig` (defaults shown).

| Direction | Rule (all on the 4H timeframe) | Default thresholds |
|---|---|---|
| `long`  | `ema_fast > ema_slow` **and** `ema_slope_fast > slope_deadband` **and** `structure ∈ {HH, HL}` **and** `dist_from_vwap > vwap_deadband` **and** `regime ∉ neutral_regimes` | `slope_deadband=0.0`, `vwap_deadband=0.0` |
| `short` | mirror: `ema_fast < ema_slow` **and** `ema_slope_fast < -slope_deadband` **and** `structure ∈ {LH, LL}` **and** `dist_from_vwap < -vwap_deadband` **and** `regime ∉ neutral_regimes` | — |
| `neutral` | `regime ∈ {panic, range_low_vol}`; **or** any gate fails / ties; **or** `structure` null; **or** insufficient lookback | `neutral_regimes=("panic","range_low_vol")` |

`ema_fast`/`ema_slow` use `FeatureConfig.ema_spans` (default 20 / 50) via the reused
`build_regime_inputs` bridge (`ema_fast_minus_slow` column). `ema_slope_fast` is the
ATR-normalised slope of the fast EMA (panel column `ema_slope_{spans[0]}`). `structure` and
`dist_from_vwap` are the Phase 2 trend features.

---

## Implementation Steps

### Step 1: `bias/errors.py`

`BiasError(TfexS50Error)` root + `BiasInputError(BiasError)`. Import `TfexS50Error` from
`..adapters.errors`. `__all__` export list.

### Step 2: `bias/models.py`

`BiasDirection` Literal (`long`/`short`/`neutral`); `BiasSignal` (frozen: `direction`,
`reasons`); `BiasConfig` (frozen: bounded `slope_deadband`, `vwap_deadband`, `neutral_regimes`);
`BiasFeatures` (frozen: `ema_fast_minus_slow`, `ema_slope_fast`, `structure: str | None`,
`dist_from_vwap`, `regime: Regime`). Reuse `Regime` + `BULLISH_STRUCTURE` / `BEARISH_STRUCTURE`
from `regime.models`.

### Step 3: `bias/htf.py`

`REQUIRED_COLUMNS` (the regime-input columns + `regime`); `build_bias_inputs(df, timeframe,
config)` — bridge: `regime.build_regime_inputs` → `regime.classify_frame` → select bias inputs +
`regime`; `classify_frame(df, *, config)` — validate columns (`BiasInputError` if missing),
append `bias_direction` (when/then) + `bias_reasons` (`pl.concat_list` of per-gate reason
exprs, drop nulls); `classify_row(features, config)` — scalar mirror returning a `BiasSignal`;
`to_signals(frame)` — `list[BiasSignal]` from the classified frame. Helpers `_direction_expr` /
`_reasons_expr` keep public functions ≤ ~50 lines.

### Step 4: `bias/__init__.py`

Re-export the public surface.

### Step 5: Config + `.env.example`

Add `bias_slope_deadband`, `bias_vwap_deadband` (bounded `Field`s) to `Settings` and a
`bias_config()` accessor (lazy import). Document the new vars in `.env.example`.

### Step 6: `pyproject.toml`

Add `--cov=src/tfex_s50_multi_tf_swing/bias` to `addopts` and the path to
`[tool.coverage.run] source`.

### Step 7: §4.2 visualisation + §4.3 demonstration

`scripts/visualise_bias.py` (overlay summary → `results/static/bias/`),
`scripts/bias_counter_trend_demo.py` (counter-trend-reduction metric JSON),
`notebooks/04_htf_bias.ipynb` (scaffolded visual, data-gated). Plotting/IO stays out of `src/`.

### Step 8: Tests (`tests/unit/bias/`)

`conftest.py` per-branch hand-built input frames + a `BiasFeatures` factory; `test_htf.py`,
`test_models_errors.py`.

---

## File Changes

| File | Action | Description |
|---|---|---|
| `src/tfex_s50_multi_tf_swing/bias/__init__.py` | CREATE | Public re-exports |
| `src/tfex_s50_multi_tf_swing/bias/errors.py` | CREATE | `BiasError` hierarchy |
| `src/tfex_s50_multi_tf_swing/bias/models.py` | CREATE | `BiasDirection`, `BiasSignal`, `BiasConfig`, `BiasFeatures` |
| `src/tfex_s50_multi_tf_swing/bias/htf.py` | CREATE | `build_bias_inputs` + `classify_frame` + `classify_row` + `to_signals` |
| `src/tfex_s50_multi_tf_swing/config/settings.py` | MODIFY | Bias deadband fields + `bias_config()` |
| `.env.example` | MODIFY | Document `TFEX_S50_MULTI_TF_SWING_BIAS_*` |
| `pyproject.toml` | MODIFY | Add `bias/` to coverage scope |
| `scripts/visualise_bias.py` | CREATE | §4.2 public-safe overlay artifact |
| `scripts/bias_counter_trend_demo.py` | CREATE | §4.3 counter-trend-reduction demonstration |
| `notebooks/04_htf_bias.ipynb` | CREATE | §4.2 visual overlay (data-gated) |
| `tests/unit/bias/conftest.py` | CREATE | Synthetic per-branch fixtures |
| `tests/unit/bias/test_htf.py` | CREATE | Classifier / gate tests |
| `tests/unit/bias/test_models_errors.py` | CREATE | Model / error tests |
| `docs/plans/phase-4-htf-bias-engine.md` | CREATE | This plan |
| `docs/plans/ROADMAP.md` | MODIFY | Tick §4.1/§4.2; defer §4.3; dated Notes |
| `CLAUDE.md` | MODIFY | Bias-layer subsection; coverage scope incl. `bias/` |
| `README.md` | MODIFY | Bias module + new env vars |
| `.claude/knowledge/bias-engine.md` | CREATE | Gate defs, thresholds, contract, 4h caveat |

---

## Test Plan

Deterministic, fixture-driven, no network. Mirrors source layout under `tests/unit/bias/`.

- **`conftest.py`** — builders producing a bias-input frame deterministically classified into
  each direction (clean long, clean short, each single-gate failure → neutral, panic veto,
  range_low_vol veto, null structure), plus a `BiasFeatures` factory. Because `structure` is
  frequently null on sparse synthetic pivots, classifier tests build the bias-input frame
  directly (one row per branch) rather than relying on the full pipeline to emit a specific
  label; a single end-to-end test exercises the `build_bias_inputs` bridge.
- **`test_htf.py`** — each gate asserted independently (EMA cross, slope vs deadband, structure
  side, VWAP side, regime veto); unanimity composition; tie EMAs → neutral; conflicting gates
  (slope vs structure) → neutral + reasons; null structure → neutral; `classify_row` agrees
  with `classify_frame` row-for-row; `to_signals` count == bar count; missing columns →
  `BiasInputError`; empty / short frame handled; the `build_bias_inputs` bridge produces
  valid signals with ≥ 2 distinct directions.
- **`test_models_errors.py`** — `BiasSignal` frozen + `reasons` populated; `BiasConfig` bound
  validation (negative deadband rejected); error classes inherit `TfexS50Error`.

Coverage gate: `--cov-fail-under=90` now also covers `bias/` (target 100 % on the new module).

---

## Success Criteria

- [x] `classify_frame` labels a fixture frame using only `long`/`short`/`neutral`, no nulls in
      `bias_direction`.
- [x] A clean-uptrend fixture row → `long`; a clean-downtrend → `short`; a panic /
      range_low_vol row → `neutral` (veto).
- [x] Tie EMAs / null structure / in-deadband slope → `neutral` (never directional).
- [x] `classify_row` agrees with `classify_frame` row-for-row on shared inputs.
- [x] `to_signals` materialises exactly one `BiasSignal` per 4H bar.
- [x] Deadbands read from `Settings` / `BiasConfig`; none hard-coded at call sites.
- [x] `bias/` imports nothing from `api/` / `signals/` / `execution/` / `risk/` / `backtest/`
      and never fetches tvkit; the `4h` engine decline stays in `data/engine_fetcher.py`.
- [x] §4.3 demonstration artifact is public-safe (no raw OHLCV columns); full metric deferred.
- [x] `uv run ruff check . && uv run ruff format --check .` clean.
- [x] `uv run mypy src tests` clean (strict).
- [x] `uv run pytest` green with ≥ 90 % coverage including `bias/`.
- [x] `uv run bandit -r src` and `uv run pip-audit` clean.
- [x] Ingestion contract + Phase 0–3 behaviour unchanged (additive only).

---

## Risks

1. **Synthetic fixtures may not cleanly separate directions.** Mitigation: build each fixture
   to satisfy exactly one rule branch; assert thresholds, not magic numbers; reuse the
   Phase 3 per-branch-frame approach (`structure` null on sparse pivots).
2. **`bias_reasons` as a `List[Utf8]` Polars column** is fiddly to build vectorised.
   Mitigation: compose with `pl.concat_list` of per-gate `when/then` string exprs and
   `list.drop_nulls`; assert against `classify_row` for parity.
3. **§4.3 magnitude over-claim.** Mitigation: explicitly deferred; the demonstration proves the
   mechanism, not the ≥ 30 % figure, and the ROADMAP note says so.
4. **4h availability.** Mitigation: bias stays source-agnostic; the typed engine decline is
   unchanged and documented as mirror-only with a one-line unblocker.

---

## Completion Notes

### Summary

Shipped ROADMAP §4.1 (4H trend filter) + §4.2 (`BiasSignal` output + visualisation) as the new
leaf package `src/tfex_s50_multi_tf_swing/bias/` (`errors.py`, `models.py`, `htf.py`,
`__init__.py`). The classifier consumes the un-normalised Phase 2 panel + the Phase 3 regime
label via `build_bias_inputs` (reusing `regime/`), and composes a conservative-unanimity bias
with a panic / range_low_vol veto. `BiasSignal` carries `direction` + one auditable `reasons`
string per gate. Deadbands live in `BiasConfig`, surfaced on `Settings`
(`TFEX_S50_MULTI_TF_SWING_BIAS_*`). Coverage scope extended to `bias/` in `pyproject.toml`.
§4.3 is a self-contained demonstration; the ≥ 30% exit metric is deferred to Phase 5. The
umbrella repo was left untouched (D11 — nothing cross-cutting changed).

### Issues Encountered

1. **`structure` frequently null** on synthetic series with sparse swing pivots, so classifier
   tests build the bias-input frame directly (one row per branch); a single end-to-end test
   exercises the `build_bias_inputs` bridge and asserts valid labels, not a specific one.
2. **Null core inputs / tie EMAs / in-deadband magnitudes** classify `neutral` (never
   directional) — trading is never enabled on undefined features.

### Quality-gate output (2026-06-03)

- `ruff check .` — All checks passed.
- `ruff format --check .` — 96 files already formatted.
- `mypy src tests` — Success: no issues found in 89 source files.
- `pytest` — 343 passed, 5 skipped; total coverage 96.57% (`bias/` 100%); ≥90% gate met.
- `bandit -r src` — 0 issues.
- `pip-audit` — no known vulnerabilities.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Opus 4.8)
**Status:** Complete
**Completed:** 2026-06-03
