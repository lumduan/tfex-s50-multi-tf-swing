# Phase 8 — Walk-Forward Backtest

**Feature:** Walk-Forward Backtest — anchored windows + realistic cost model driving the risk engine
**Branch:** `feature/phase-8-walk-forward-backtest`
**Created:** 2026-06-04
**Status:** Complete
**Completed:** 2026-06-04
**Depends On:** Phase 5 (Setup Detection & Signals) ✓, Phase 6 (ML Probability Filter) ✓, Phase 7 (Risk Engine) ✓

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Design Decisions](#design-decisions)
5. [Implementation Steps](#implementation-steps)
6. [File Changes](#file-changes)
7. [Success Criteria](#success-criteria)
8. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phases 0–7 shipped the full computation stack (data → features → regime → HTF bias →
signals/execution/backtest → ML filter → risk) as one-way leaf packages. The Phase-7 risk engine
(`risk/decision.evaluate_entry`) is **code-complete but never driven** — every prior phase stayed
ROADMAP-pure (no FastAPI endpoint, no `live/` wiring, no walk-forward). Phase 8 is the validation
harness that finally wires Phase-5 signals/execution + Phase-7 risk + the Phase-6 ML gate over
**anchored walk-forward windows** with a **realistic cost model**, proving the system survives
across regimes *after costs* — the gate before paper trading (Phase 9). It is the first place
`evaluate_entry` is actually driven per trade.

### The data gate (honesty up front)

There is **no 5-year TFEX backfill**, the Market Data Engine has **no TFEX data**, and `4h` is
mirror-only (the `engine` source raises `EngineTimeframeUnavailableError`). So — exactly as Phases
1/4/5/6 did — Phase 8 ships **machinery + a synthetic / public-safe demonstration**. The numeric
exit-criteria *magnitudes* (positive expectancy after costs, max drawdown within budget, regime
stability evidenced) are marked **deferred → data-gated**; we do not fake a backtest or a magnitude
claim. The harness, cost model, metrics, and reporting are real and tested; the numbers they will
one day produce on real data are not asserted here.

### Parent Plan Reference

- `docs/plans/ROADMAP.md` — **Phase 8 — Walk-Forward Backtest** (§8.1 Walk-Forward Harness,
  §8.2 Metrics, §8.3 Reporting) + the "Market data source" section + the Dependency Map
  (Phase 5/6/7 → Phase 8).
- `.claude/knowledge/backtest-protocol.md` — the cardinal rules: anchored walk-forward only, cost
  realism, the success-metric table, reporting expectations, the public-data boundary.

### Key Deliverables

1. `src/tfex_s50_multi_tf_swing/backtest/costs.py` — `CostModel` + `apply_costs` → `CostedTrade`.
2. `src/tfex_s50_multi_tf_swing/backtest/walk_forward.py` — anchored window generation +
   risk-driven harness.
3. `src/tfex_s50_multi_tf_swing/backtest/data_source.py` — source-agnostic frame loader (engine /
   Parquet snapshot, never tvkit) raising a typed `WalkForwardDataError`.
4. Extended `backtest/metrics.py` (Sharpe / Sortino / drawdown profile / regime concentration) +
   `backtest/models.py` (result models) + `backtest/errors.py`.
5. `WalkForwardConfig` + `CostModel` on `Settings` (`TFEX_S50_MULTI_TF_SWING_WALK_FORWARD_*` /
   `_COST_*`, `walk_forward_config()` / `cost_model()`).
6. `scripts/run_walk_forward.py` + `notebooks/08_walk_forward.ipynb` → public-safe
   `results/static/backtest/` artifacts.
7. `tests/unit/backtest/` ≥ 90 % on the new modules; public-data-boundary test extended.
8. Updated ROADMAP, `CLAUDE.md`, `backtest-protocol.md`, a walk-forward playbook, the memory pointer.

---

## AI Prompt

The following prompt was used to generate this phase (verbatim):

```
🎯 OBJECTIVE
Implement Phase 8 — Walk-Forward Backtest of the tfex-s50-multi-tf-swing strategy, the final
validation harness that drives the Phase-7 risk engine over Phase-5 signals/execution across
anchored walk-forward windows with a realistic cost model. This is the "prove the system survives
across regimes, with realistic costs — no random splits ever" phase. You are working inside the
sub-repo strategies/tfex-s50-multi-tf-swing/ (its own independent git remote
github.com/lumduan/tfex-s50-multi-tf-swing); do NOT touch the umbrella repo's history except for
the explicitly-listed umbrella doc edits below. You MUST plan before you code, write the plan to
disk, get the gates green, then commit and PR.

REQUIRED READING (read first, in this order — do not skip)
1. CLAUDE.md (umbrella root) — system map, ingestion contract, hard rules.
2. strategies/tfex-s50-multi-tf-swing/CLAUDE.md — service architecture, layering, hard rules
   (TFEX-specific #1–#8 and inherited #1–#8), coding conventions, coverage gate.
3. strategies/tfex-s50-multi-tf-swing/docs/plans/ROADMAP.md — the canonical source of truth. Phase
   8 spec is §8.1–§8.3 plus the "Market data source" section and the Dependency Map.
4. strategies/tfex-s50-multi-tf-swing/.claude/knowledge/backtest-protocol.md — the cardinal rules.
5. Existing Phase-5 backtest code you will extend, NOT duplicate: src/.../backtest/ (errors.py,
   models.py, metrics.py, per_strategy.py), plus signals/, execution/, risk/ (esp.
   risk/decision.py:evaluate_entry and risk/sizing.py:S50_MULTIPLIER), regime/, ml/.
6. Plan-format reference: strategies/csm-set/docs/plans/examples/phase1-sample.md.
7. The existing per-phase plans (phase-5-…, phase-6-…, phase-7-risk-engine.md).

STEP 1 — BRANCH: feature/phase-8-walk-forward-backtest (clean tree first).
STEP 2 — WRITE THE PLAN BEFORE ANY CODE: docs/plans/phase-8-walk-forward-backtest.md, following
the phase1-sample.md structure, embedding this prompt verbatim, enumerating Design Decisions with
IDs, listing every file, and defining Success Criteria mapping 1:1 to ROADMAP §8.

STEP 3 — IMPLEMENT (ROADMAP §8.1–§8.3) as a cohesive extension of the existing backtest/ package.
Keep it a leaf library: importing signals/ + execution/ + risk/ + regime/ + ml/, importing nothing
from api/. No FastAPI endpoint, no gateway extended_data change, no live/ wiring.
§8.1 — Walk-Forward Harness — backtest/walk_forward.py: anchored train/test windows only (never a
random / k-fold split — TFEX hard rule #6; assert in tests). Window boundaries tz-aware
Asia/Bangkok. Per window: optionally re-fit the ML model on the train slice (reuse
ml.training.walk_forward_train; respect the default-OFF TFEX_S50_MULTI_TF_SWING_ML_FILTER_ENABLED
gate so an unset env reproduces Phase-5 behaviour byte-for-byte), then run detection + execution on
the test slice, sizing every trade through risk.decision.evaluate_entry. Drive the raw
per-contract series into execution/ for fills/roll cost (hard rule #3); use the back-adjusted
continuous for signal generation only. Configurable cost model as its own typed component
(backtest/costs.py): commission (per-contract fee + clearing fee), slippage (ATR-scaled, worse on
illiquid sessions — night/around-lunch, reuse data/session.py), spread (tick-based), and
margin/financing where applicable. Monetary outputs are Decimal (S50 multiplier =
risk.sizing.S50_MULTIPLIER, never re-typed inline); statistical ratios stay float. Market data
source rule (non-negotiable): walk-forward reads OHLCV from the Market Data Engine (engine source
via the gateway proxy) or the engine's offline Parquet snapshot — never a per-strategy tvkit fetch,
never the tvkit cookie. Surface a typed error (extend backtest/errors.py) when the engine/gateway
is unavailable and fall back to the local Parquet snapshot. Honour that 4h is engine-declined
(EngineTimeframeUnavailableError) — A/B degrade to neutral bias, C still runs.
§8.2 — Metrics — extend backtest/metrics.py (reuse, don't fork): expectancy, max drawdown (depth,
time underwater, recovery), profit factor, regime-stratified expectancy/win-rate (fails loudly if
one regime carries everything), and Sharpe/Sortino per period. Return typed Pydantic result models.
§8.3 — Reporting — notebooks/08_walk_forward.ipynb + a public-safe owner script
(scripts/run_walk_forward.py): concatenated per-window equity curve (NAV indexed to 100,
benchmarked vs S50 buy-and-hold), drawdown chart with regime overlay, per-strategy and combined
results, and a sensitivity sweep on the 2–3 most influential thresholds (ATR multiplier, ML
thresholds). Artifacts saved under results/backtest/ — public-safe, counts/metrics only, NEVER raw
OHLCV (add/extend a test enforcing it).

QUALITY BAR: from __future__ import annotations atop every src/ module; mypy strict clean; Pydantic
at all boundaries; httpx.AsyncClient for HTTP (requests forbidden in src/); CPU-bound ML inference
from an async caller via asyncio.to_thread; module-local exceptions in backtest/errors.py inheriting
TfexS50Error; logger = logging.getLogger(__name__) with %-formatting (never print in src/);
determinism (anchored windows + fixed seeds; no wall-clock; inject dates; assert no-look-ahead and
no-random-split); unit + integration tests mirroring tests/unit/<subpkg>/; extend the coverage gate
to the new backtest/ modules and meet ≥ 90 %; synthetic/public-safe fixtures (no real OHLCV);
@pytest.mark.infra_db / @pytest.mark.gateway self-skip; secrets via pydantic-settings with the
TFEX_S50_MULTI_TF_SWING_* prefix (frozen WalkForwardConfig / cost-model config; unset env reproduces
defaults); no model binaries / raw data committed; Polars-native vectorised computation; stream
windows rather than materialising the full cartesian history; default-OFF / unset-env leaves
Phase-5/6/7 behaviour byte-for-byte unchanged; file ≤ 400 lines, functions ≤ ~50 lines. Edge cases:
empty/short windows; a window with zero qualifying trades; kill-switch engaged mid-window;
session-limit halt inside a window; engine/gateway unavailable; 4h unavailable; a regime that never
appears in a test window; back-adjusted-vs-raw price divergence at roll boundaries.

STEP 4 — DOCS / KNOWLEDGE / MEMORY UPDATES. Sub-repo: ROADMAP.md (tick §8.1–§8.3 honestly, Notes
block, Current Status → Phase 9, plan index link); CLAUDE.md (Phase 8 architecture subsection,
coverage-gate module list, Where-to-look-next pointer); .claude/knowledge/backtest-protocol.md
(extend if new conventions); .claude/playbooks/* (running the walk-forward backtest). Umbrella:
update CLAUDE.md and .claude/* only where a cross-cutting fact genuinely changed (likely a light
touch or none). Persistent agent memory: update project-tfex-s50-strategy.md + its MEMORY.md
pointer.

STEP 5 — VERIFY, COMMIT, PR. Run the full combined gate and paste the real output
(uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest).
Conventional-commit; push; open a PR; report every commit/push/PR as a single ASCII box-drawing
table (Repo | Branch | Commit | GitHub).

HARD CONSTRAINTS: tfex NEVER fetches tvkit and NEVER owns the TradingView cookie; anchored
walk-forward only — never random/k-fold splits; execution simulation uses the raw per-contract
series; money is Decimal, S50 multiplier is the single named S50_MULTIPLIER constant; raw OHLCV
must NEVER appear in results/backtest/; stay ROADMAP-pure; be honest about the data gate; docs/plans/
is git-tracked.
```

---

## Scope

### In Scope (Phase 8)

| Component | Description | Status |
|---|---|---|
| `backtest/costs.py` | `CostModel` (frozen), `CostedTrade`, `apply_costs`, illiquid-session detector | Complete |
| `backtest/walk_forward.py` | `generate_windows`, `drive_costed_trades`, per-window run, `run_walk_forward` | Complete |
| `backtest/data_source.py` | source-agnostic frame loader (Parquet snapshot / engine), `WalkForwardDataError` | Complete |
| `backtest/metrics.py` | + `sharpe`, `sortino`, `drawdown_profile`, `regime_concentration` (existing fns intact) | Complete |
| `backtest/models.py` | + window / result / ratio / drawdown / concentration Pydantic models + configs | Complete |
| `backtest/errors.py` | + `WalkForwardDataError(BacktestError)` | Complete |
| `WalkForwardConfig` / `CostModel` on `Settings` | `TFEX_S50_MULTI_TF_SWING_WALK_FORWARD_*` / `_COST_*` + accessors | Complete |
| `scripts/run_walk_forward.py` | public-safe JSON → `results/static/backtest/` | Complete |
| `notebooks/08_walk_forward.ipynb` | equity curve, drawdown+regime overlay, per-strategy+combined, sweep | Complete |
| `tests/unit/backtest/` | ≥ 90 % on new modules incl. the no-look-ahead / non-random asserts | Complete |
| Public-data-boundary test | extended to cover `results/static/backtest/` | Complete |
| Docs / knowledge / playbook / memory | ROADMAP, CLAUDE.md, backtest-protocol, playbook, memory | Complete |

### Out of Scope / Deferred (Phase 8)

- **Real-data exit-criteria magnitudes** — positive expectancy after costs, drawdown within budget,
  regime stability evidenced are **deferred → data-gated** on the (non-existent) 5-year TFEX
  backfill + engine TFEX data. The harness + a synthetic demonstration ship now.
- **`4h` on the engine source** — declined (`EngineTimeframeUnavailableError`); A/B degrade to
  `neutral` bias and emit nothing, C still runs (matches Phase 4/5 behaviour).
- **rv-percentile-driven size halving inside the backtest** — `execution.Trade` does not carry the
  Phase-2 `rv_percentile`; backtest sizing uses the **regime cap** (`panic`/`range_low_vol` → 0).
  Threading the percentile through is a documented, non-faked enhancement (D7).
- **Live / paper wiring, broker financing, intraday margin calls** — Phase 9/10. The cost model
  has a margin/financing hook but the live evidence is data-gated.
- **FastAPI endpoint / gateway `extended_data` / `live/`** — ROADMAP-pure, like Phases 3–7.

---

## Design Decisions

### D1 — Anchored-expanding windows are the default; assert the invariant, never random
`generate_windows` defaults to `mode="anchored"` (train start fixed at data start, train window
expands each step; test = the next `test_span` block) — consistent with
`ml.training.walk_forward_train`'s expand-from-start behaviour, so per-window ML re-fits use the
same train shape. `mode="rolling"` (fixed-width train start rolling forward, the literal
ROADMAP/backtest-protocol example) is the configurable alternative. Both are deterministic and
time-ordered; tests assert **`train_end ≤ test_start` for every window** and that windows are
reproducible (no RNG, no `datetime.now()` — span boundaries are derived from injected `start`/`end`
in tz-aware `Asia/Bangkok`). This is TFEX hard rule #6 made executable.

### D2 — Cost model is a typed, frozen component; costs fold into points-per-contract
`CostModel` (frozen Pydantic, bounded) carries `commission_per_contract` + `clearing_fee_per_contract`
(`Decimal`), `slippage_atr_mult` + `illiquid_session_mult` (float), `tick_size` (`Decimal`) +
`spread_ticks` (float). `apply_costs(trade, *, atr_at_entry, session_name, config)` converts every
cost to **points per contract** so net R stays contract-agnostic and directly comparable to the
gross R:
`cost_points = slippage_points + spread_points + (commission + clearing) / S50_MULTIPLIER`, where
`slippage_points = slippage_atr_mult · atr · (illiquid_session_mult if illiquid else 1.0)` and
`spread_points = spread_ticks · tick_size`. Net `pnl_points` / `r_multiple` are recomputed off the
trade's own risk distance. The fee→points conversion is the single use of `S50_MULTIPLIER` here,
imported from `risk.sizing` (never re-typed). A backtest without costs is a marketing exercise
(backtest-protocol) — so costs are mandatory, not optional.

### D3 — Illiquid sessions reuse `data/session.py`
"Worse on illiquid sessions" = the **night** session and the **lunch** dead-zone edge, resolved via
`SessionCalendar.session_of` / `is_lunch_dead_zone` on the trade's entry time — never a re-implemented
clock. `illiquid_session_mult` (default > 1.0) uplifts slippage there.

### D4 — Money is `Decimal`, ratios are `float`
Commission, clearing, tick size, equity, the THB equity curve, and `S50_MULTIPLIER` are `Decimal`
end-to-end; slippage/spread multipliers, Sharpe, Sortino, win-rate fractions, and regime-share are
`float` (statistical quantities that never cross the gateway), exactly as Phases 2/3/7 established.

### D5 — `evaluate_entry` is driven per trade with one shared daily session in the combined run
This is the first place the Phase-7 engine is driven. `drive_costed_trades` walks costed trades in
`entry_time` order; on each new BKK trading date it `start_session`s a fresh `SessionRiskState`; per
candidate it builds a `PositionSizeRequest` and calls `evaluate_entry`, **skipping** the trade when
`allow_entry` is `False` or `contracts == 0` (kill switch / session halt / no-trade regime). A taken
trade folds its **net** R into the session via `register_outcome` (so daily-loss / streak / count
limits react to *post-cost* outcomes). The **combined** A+B+C run uses **one shared session per day**
across all strategies (daily limits apply portfolio-wide — a single live account); the **per-strategy**
runs each use their own daily session (the isolated-edge view). Equity carries across windows.

### D6 — `CostedTrade.net_trade` reuses the existing metrics over net values
`CostedTrade` exposes `net_trade: Trade` (the gross `Trade` with `pnl_points` / `r_multiple` replaced
by net values). Every Phase-5 metric (`expectancy`, `profit_factor`, `max_drawdown`, `win_rate`,
`regime_stratified`, `compute_metrics`) and the new `drawdown_profile` therefore run **unchanged**
over the net trades — we reuse, never fork (the requirement).

### D7 — Backtest sizing uses the regime cap; rv-percentile threading is a documented enhancement
`execution.Trade` carries `regime` but not the Phase-2 `rv_percentile`, so the `PositionSizeRequest`
passes `rv_percentile=None`. Volatility scaling then relies on the **regime cap**
(`regime.policy.regime_to_size_multiplier`: `panic` → 0 with `panic_no_trade`, `range_low_vol` → 0)
— which already encodes the high-vol gates. The percentile-based *halving* is a live-path refinement;
threading the feature onto the Trade is a clean future change, called out here rather than faked.

### D8 — Per-window ML re-fit honours the default-OFF gate
When `WalkForwardConfig.refit_ml` **and** `MLFilterConfig.enabled` are both true, each window calls
`ml.training.walk_forward_train` on the **train** slice, builds a bundle, and binds
`functools.partial(filter_signals, …)` for the **test** slice. With the default (`ml_filter_enabled`
unset → `False`) **no refit happens and the result is byte-for-byte the Phase-5 behaviour**. The
real trained models + the out-of-sample A/B magnitude claim stay **data-gated** (Phase 6's deferral).
ML inference is CPU-bound; there is no async caller here, but a future one must use `asyncio.to_thread`.

### D9 — Raw per-contract series for execution, back-adjusted continuous for signals
The harness takes two frames: `inputs` (the aligned 5m signal-input frame built off the **back-adjusted
continuous** — signals only) and `raw_bars` (the **raw per-contract** 5m series with `atr` — execution
fills + roll cost). This honours TFEX hard rule #3 structurally. The synthetic demonstration passes a
single continuous series for both (documented), since no raw multi-contract TFEX history exists yet.

### D10 — Market data via the engine / Parquet snapshot, never tvkit; typed error + fallback
`data_source.load_walk_forward_frames` reads continuous frames from the engine's offline **Parquet
snapshot** (`ParquetStore`, the heavy-scan path the ROADMAP prefers — usable even when infra-db /
the gateway is down) and raises `WalkForwardDataError` when a required frame is missing/empty. The
live `engine` source is the existing `EngineOhlcvFetcher` used by the refresh pipeline (so the
snapshot is engine-sourced); tfex holds **no tvkit cookie** on any Phase-8 path. `4h` declined →
A/B degrade to `neutral`, C runs (D, ROADMAP §8 + the OHLCV-source section).

### D11 — Metrics extend, never fork; regime concentration fails loudly
`drawdown_profile` extends `max_drawdown` with **time-underwater** (trades below the running peak)
and **recovery** (trades from the max trough back to peak, `None` if never recovered).
`sharpe` / `sortino` are pure functions over a per-period (daily-summed net-R) return series.
`regime_concentration` flags when one regime's share of the total absolute expectancy contribution
exceeds a configurable threshold — "fails loudly if one regime carries everything" surfaces as a
prominent boolean + share on the result and is asserted in tests.

### D12 — Public-data boundary: counts/metrics only, never raw OHLCV
`results/static/backtest/` artifacts carry trade counts, R-multiple metrics, ratios, and NAV index
only — **never** `open`/`high`/`low`/`close`/`volume` nor any raw price series. The equity curve is
NOT serialised to the public JSON (it would trip the >400-numeric-array heuristic and is rebuildable
in the notebook). The existing `test_public_data_boundary_files.py` is extended to scan the new dir.

### D13 — `WalkForwardConfig` / `CostModel` surfaced on `Settings`
`Settings` gains `TFEX_S50_MULTI_TF_SWING_WALK_FORWARD_*` + `_COST_*` bounded fields and lazy-import
`walk_forward_config()` / `cost_model()` accessors mirroring `risk_config()`. `Decimal` fields parse
from env strings. An unset env reproduces the documented defaults (Phase-5/6/7 byte-for-byte).

### D14 — ROADMAP-pure
No gateway `extended_data` change, no FastAPI endpoint, no `live/` wiring. The harness is a leaf that
imports `signals/ + execution/ + risk/ + regime/ + ml/ + data/` and nothing from `api/`.

---

## Implementation Steps

1. `backtest/errors.py` — add `WalkForwardDataError(BacktestError)`.
2. `backtest/costs.py` — `CostModel`, `CostedTrade` (+ `net_trade`), `apply_costs`, `is_illiquid_session`.
3. `backtest/models.py` — add `WalkForwardConfig`, `WalkForwardWindow`, `DrawdownProfile`,
   `PeriodRatios`, `RegimeConcentration`, `WindowResult`, `WalkForwardResult`, `WalkForwardReport`.
4. `backtest/metrics.py` — add `sharpe`, `sortino`, `drawdown_profile`, `regime_concentration`.
5. `backtest/walk_forward.py` — `generate_windows`, `_costed_trades_for_window`,
   `drive_costed_trades`, `run_walk_forward`.
6. `backtest/data_source.py` — `load_walk_forward_frames` (Parquet snapshot / engine, typed error).
7. `config/settings.py` + `.env.example` — `WalkForwardConfig` / `CostModel` fields + accessors.
8. `scripts/run_walk_forward.py` + `notebooks/08_walk_forward.ipynb`.
9. `tests/unit/backtest/` (costs, walk_forward, metrics) + extend the public-boundary test.
10. Docs / knowledge / playbook / memory.

---

## File Changes

| File | Action | Description |
|---|---|---|
| `docs/plans/phase-8-walk-forward-backtest.md` | CREATE | This plan |
| `src/tfex_s50_multi_tf_swing/backtest/costs.py` | CREATE | Cost model + `CostedTrade` + `apply_costs` |
| `src/tfex_s50_multi_tf_swing/backtest/walk_forward.py` | CREATE | Anchored windows + risk-driven harness |
| `src/tfex_s50_multi_tf_swing/backtest/data_source.py` | CREATE | Source-agnostic frame loader |
| `src/tfex_s50_multi_tf_swing/backtest/metrics.py` | MODIFY | + Sharpe / Sortino / drawdown profile / concentration |
| `src/tfex_s50_multi_tf_swing/backtest/models.py` | MODIFY | + config + window/result models |
| `src/tfex_s50_multi_tf_swing/backtest/errors.py` | MODIFY | + `WalkForwardDataError` |
| `src/tfex_s50_multi_tf_swing/backtest/__init__.py` | MODIFY | Public re-exports |
| `src/tfex_s50_multi_tf_swing/config/settings.py` | MODIFY | `WalkForwardConfig` / `CostModel` fields + accessors |
| `.env.example` | MODIFY | Phase 8 walk-forward + cost vars |
| `scripts/run_walk_forward.py` | CREATE | Public-safe demonstration script |
| `notebooks/08_walk_forward.ipynb` | CREATE | Reporting notebook |
| `tests/unit/backtest/test_costs.py` | CREATE | Cost-model tests |
| `tests/unit/backtest/test_walk_forward.py` | CREATE | Harness tests (no-look-ahead / non-random / risk-driven / edge cases) |
| `tests/unit/backtest/test_metrics_phase8.py` | CREATE | Sharpe / Sortino / drawdown / concentration tests |
| `tests/integration/test_public_data_boundary_files.py` | MODIFY | Scan `results/static/backtest/` |
| `docs/plans/ROADMAP.md` | MODIFY | Tick §8.1–§8.3, Notes, Current Status → Phase 9 |
| `CLAUDE.md` | MODIFY | Phase 8 architecture subsection + Where-to-look-next |
| `.claude/knowledge/backtest-protocol.md` | MODIFY | Cost-model structure + artifact contract |
| `.claude/playbooks/walk-forward-backtest.md` | CREATE | Owner runbook |

---

## Success Criteria

- [x] **§8.1** Anchored walk-forward harness + configurable cost model (commission + ATR/illiquid
  slippage + tick spread); per-window ML re-fit machinery respecting the default-OFF gate; engine /
  Parquet data source (never tvkit); raw-series execution. Tests assert `train_end ≤ test_start`
  and windows are deterministic / non-random. ✓ machinery.
- [x] **§8.2** Expectancy, max-drawdown profile (depth + time-underwater + recovery), profit factor,
  regime-stratified metrics (loud on concentration), Sharpe/Sortino per period — typed Pydantic
  results; existing metric signatures unchanged. ✓ machinery.
- [x] **§8.3** `08_walk_forward.ipynb` + `run_walk_forward.py` → public-safe `results/static/backtest/`
  artifacts (no raw OHLCV); public-boundary test green.
- [x] `evaluate_entry` driven per trade; shared daily session in combined run; kill-switch /
  session-halt mid-window skip trades; default-OFF ML = Phase-5 identity; engine-down →
  `WalkForwardDataError`; empty/short window and zero-trade window handled.
- [x] Exit-criteria **magnitudes** marked **deferred → data-gated**; demonstrated on synthetic data.
- [x] `Settings().walk_forward_config()` / `cost_model()` with no env reproduce documented defaults.
- [x] New `backtest/` modules **100 %** coverage; `uv run mypy src tests` clean; full gate green.

---

## Completion Notes

**Shipped 2026-06-04** on `feature/phase-8-walk-forward-backtest`. Full gate green: `ruff check` +
`ruff format --check` + `mypy src tests` clean; pytest **623 passed, 5 skipped**, total coverage
**98 %** with **100 %** on every new module (`costs.py`, `walk_forward.py`, `data_source.py`, and the
`metrics.py` / `models.py` additions).

What shipped (machinery):

- `backtest/costs.py` — `CostModel` + `CostedTrade` (`.net_trade`) + `apply_costs` +
  `is_illiquid_session`. Costs fold to points-per-contract; commission via `S50_MULTIPLIER`.
- `backtest/walk_forward.py` — `generate_windows` (anchored default, asserted no-look-ahead /
  non-random), `drive_costed_trades` (the first driver of `evaluate_entry`, shared daily session +
  `ladder_evidence`), `run_walk_forward` (combined + per-strategy tracks, equity compounding).
- `backtest/data_source.py` — `load_continuous_frames` (Parquet snapshot, `WalkForwardDataError`) +
  `build_execution_bars`.
- Extended `metrics.py` (`drawdown_profile`, `sharpe`, `sortino`, `period_ratios`,
  `regime_concentration`) + `models.py` (config + window/result models) + `errors.py`.
- `WalkForwardConfig` / `CostModel` on `Settings` + `.env.example`; `scripts/run_walk_forward.py` +
  `notebooks/08_walk_forward.ipynb`; public-data-boundary test extended for the report shape.

Honestly deferred:

- **Exit-criteria magnitudes** (positive expectancy after costs / drawdown within budget / regime
  stability) → **data-gated** on the 5-year TFEX backfill + engine TFEX data. The harness produces
  them the moment that data lands; the synthetic demonstration proves the machinery, not the edge.
- **Backtest deployment stage:** the capital ladder caps `paper` to 0 contracts, so a backtest runs
  at `micro_live`+ (the script evaluates scaled capacity with full evidence; live stays ladder-gated).
- **rv-percentile size-halving** is not threaded onto the execution `Trade` (D7) — backtest sizing
  uses the regime cap; threading the feature through is a documented, non-faked enhancement.
- **True per-window ML training** is the injectable `ml_filter_factory` hook (tested with a fake
  factory); the concrete training pipeline is data-gated, so the owner script binds a pre-loaded
  bundle when ML is enabled.

Stayed ROADMAP-pure: no FastAPI endpoint, no gateway `extended_data` change, no `live/` wiring.
</content>
</invoke>
