# Phase 5: Setup Detection & Signal Strategies

**Feature:** `feature-tfex-integration` — Execution Layer, Setup Detection & Signal Strategies
**Branch:** `feature/phase-5-setup-detection-signals`
**Created:** 2026-06-03
**Status:** Complete
**Completed:** 2026-06-03
**Depends On:** Phase 1 — Data Infrastructure (✓), Phase 2 — Feature Engineering (✓),
Phase 3 — Regime Detection (✓), Phase 4 — HTF Bias Engine (✓)

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Design Decisions](#design-decisions)
5. [Strategy Rules](#strategy-rules)
6. [Implementation Steps](#implementation-steps)
7. [File Changes](#file-changes)
8. [Test Plan](#test-plan)
9. [Success Criteria](#success-criteria)
10. [Risks](#risks)
11. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 5 builds the **Execution Layer's first half**: it turns the Phase 3 regime gating and the
Phase 4 HTF bias veto into actual **trade setups**. The ROADMAP scopes three rule-based
strategies — **A (pullback continuation, primary)**, **B (opening-range breakout)**,
**C (liquidity-sweep reversal)** — plus a **5m execution engine** that simulates a trade from a
setup signal, and a **per-strategy backtest** that reports expectancy / profit factor / max
drawdown / regime-stratified PnL.

Each strategy is **gated by the HTF bias** (`bias_direction`) and the **regime → strategy
policy** (`regime.policy.regime_to_strategies`). This is the first phase that *consumes* the
veto/gating contracts the prior phases produced; nothing is re-derived.

The three new packages — `signals/`, `execution/`, `backtest/` — are **pure offline Polars
library leaves**, mirroring the Phase 3 `regime/` and Phase 4 `bias/` patterns exactly:
`classify_frame` (vectorised) + `classify_row` (scalar) + `to_signals` entry points, frozen
Pydantic config/IO, look-ahead-free construction, no FastAPI endpoint, **no `risk/` wiring**,
**no gateway `extended_data` change** (those belong to Phases 7 and the later daily-pipeline
phase). They emit **sizing-ready** outputs (entry, structure-anchored stop, direction,
R-multiple) for the Phase 7 risk engine to consume.

### Parent Plan Reference

- `docs/plans/ROADMAP.md` → **Phase 5 — Setup Detection & Signal Strategies**
- `docs/plans/phase-4-htf-bias-engine.md` (the package shape this phase mirrors)
- `.claude/knowledge/strategy-design.md` (the A/B/C + execution specifications)

### Key Deliverables

1. **`signals/`** — `errors.py`, `models.py`, `inputs.py`, `strategy_a.py`, `strategy_b.py`,
   `strategy_c.py`, `__init__.py`. A/B/C detectors gated by bias + regime; `classify_frame` /
   `classify_row` / `to_signals` per strategy.
2. **`execution/`** — `errors.py`, `models.py`, `engine.py`, `__init__.py`. 5m trade simulation:
   next-bar fill, `k·ATR` structure-anchored stop, partial TP + trail, breakeven, time stop.
3. **`backtest/`** — `errors.py`, `models.py`, `metrics.py`, `per_strategy.py`, `__init__.py`.
   Expectancy / PF / max-DD / win-rate / regime-stratified over `Trade` lists; per-strategy runner.
4. **Config** — `signal_*` / `execution_*` fields on `Settings`
   (`TFEX_S50_MULTI_TF_SWING_SIGNAL_*` / `_EXECUTION_*`) + `signal_config()` / `execution_config()`
   accessors; `.env.example` updated; coverage gate extended to the three new packages.
5. **§5.5 demonstration** — `scripts/per_strategy_backtest_demo.py` (public-safe metric artifact).
6. **Tests** — `tests/unit/{signals,execution,backtest}/`, ≥ 90 % coverage on the new packages.

---

## AI Prompt

The following prompt initiated this phase. It is embedded verbatim so the plan is
self-contained.

```
# Task: Implement Phase 5 — Setup Detection & Signal Strategies (strategies/tfex-s50-multi-tf-swing)

You are working inside the umbrella repo `quant-trading-system`. The target service is the
independent git repo at `strategies/tfex-s50-multi-tf-swing/` (FastAPI / Python 3.11, `uv`,
host `:8200`, internal `:8000`). This is the first implementation of `feature-tfex-integration`
— a headless TFEX SET50 Futures multi-timeframe swing-intraday strategy.

## Objective
Implement **Phase 5 — Setup Detection & Signal Strategies** exactly as scoped in the
service's own roadmap. Produce a written implementation plan FIRST, get it on disk, then
implement to that plan. Do not improvise scope: Phase 5's deliverables are defined by the
roadmap — read it before deciding anything.

## Step 0 — Read before doing anything (do not skip, do not assume)
Read and internalise, in this order, and reconcile any conflicts (sub-repo docs win for
service-internal decisions; umbrella `CLAUDE.md` wins for cross-service contracts):
1. `CLAUDE.md` (umbrella — system map, ingestion contract, Docker network, cross-cutting rules)
2. `strategies/tfex-s50-multi-tf-swing/CLAUDE.md` (service quality gate: ruff, mypy **strict**,
   pytest ≥90% on `adapters/` + `risk/`; `uv run` only)
3. `strategies/tfex-s50-multi-tf-swing/docs/plans/ROADMAP.md` (THE authoritative Phase 5 scope —
   extract the exact Phase 5 goals, acceptance criteria, timeframe set, and any deferred items)
4. The existing service source tree under `strategies/tfex-s50-multi-tf-swing/` — map the
   current module layout (`adapters/`, `risk/`, `api/`, signal/setup modules, config, tests)
   so the new code matches established patterns, naming, and idioms rather than inventing new ones
5. `.claude/knowledge/feature-tfex-integration.md` (umbrella feature context)
6. Format reference for the plan doc: `strategies/csm-set/docs/plans/examples/phase1-sample.md`

If, after reading, Phase 5 scope or acceptance criteria are genuinely ambiguous (e.g. which
timeframes, which setup patterns, signal output schema), state the ambiguity explicitly in the
plan and choose the most roadmap-consistent default — do not silently guess.

## Step 1 — Branch
From inside `strategies/tfex-s50-multi-tf-swing/`, create a new feature branch off its default
branch (do NOT commit Phase 5 work to `main`). Use a descriptive name, e.g.
`feature/phase5-setup-detection-signals`. Never touch the other sub-repos' histories.

## Step 2 — Write the implementation plan FIRST (before any code)
Author a markdown plan at:
`strategies/tfex-s50-multi-tf-swing/docs/plans/{phase_name}.md`
where `{phase_name}` matches the roadmap's Phase 5 slug (e.g. `phase5-setup-detection-signals.md`).

The plan must follow the structure/style of
`strategies/csm-set/docs/plans/examples/phase1-sample.md` and must include:
- **Verbatim copy of this prompt** embedded in the plan (a "Prompt" section), as required.
- Phase 5 objective and explicit acceptance criteria pulled from the ROADMAP.
- Module-by-module design: setup-detection logic (multi-timeframe alignment — HTF bias / MTF
  setup / LTF trigger as defined in the roadmap), signal generation, and how signals feed the
  existing `risk/` sizing and the gateway ingestion contract (`extended_data` is the escape
  hatch for TFEX-specific fields — margin/contracts; never add strategy-specific columns to
  gateway tables).
- Data sourcing note: OHLCV comes via the service's existing reader behind
  `TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE` (`mirror | engine`, default `mirror`). Do NOT call
  tvkit directly — the marketdata-engine is the sole cookie owner. Respect the deferred-`4h`
  client-side decline if relevant.
- Test plan to meet ≥90% coverage on `adapters/` + `risk/` (and any new signal/setup module),
  including the edge cases below.
- File-by-file change list with project-relative paths, sequencing, and rollback/flag strategy
  if behavior changes for existing consumers.
- Backward-compatibility & migration impact (config/env additions documented; defaults preserve
  current behavior).

Keep the plan concrete — no "TBD" placeholders.

## Step 3 — Implement to the plan
Implement Phase 5 strictly per the plan and the roadmap. Engineering bar (mandatory):
- **Type safety:** full type hints; passes `uv run mypy` in **strict** mode.
- **Determinism & correctness:** multi-timeframe setup detection must be tz-aware end-to-end
  (store UTC, display Asia/Bangkok); monetary values `Decimal` at any boundary, never `float`.
  No look-ahead bias in setup/signal evaluation across timeframes — assert candle-close
  alignment.
- **Async correctness:** any I/O (OHLCV reads, gateway posts) is properly `async`; no blocking
  calls in the event loop; correct concurrency when fanning out across timeframes/contracts.
- **Error handling & logging:** structured logging; explicit handling of missing/short OHLCV
  windows, unavailable timeframe (e.g. `4h` decline), reader-source failures, and partial data.
- **Security:** validate all inputs; honor `X-API-Key`/`INTERNAL_API_KEY` for gateway calls;
  never log or commit secrets or the tvkit cookie; no secrets in fixtures.
- **Performance:** avoid recomputing indicators per-candle where a vectorized/rolling approach
  fits the existing pattern; flag any obvious O(n²) scans over candle history.
- **Simplicity:** prefer a clear, elegant solution that matches existing module idioms over a
  clever one.

## Step 4 — Tests
Add unit tests (setup-detection truth tables, signal generation, timeframe-alignment edge
cases) and integration tests (reader → setup → signal → risk sizing → ingestion payload shape).
Cover edge cases: insufficient history, conflicting HTF/LTF bias, flat/no-setup days, timezone
boundary candles (Asia/Bangkok session edges), reader returning `engine` vs `mirror`, and the
deferred `4h` path. Hit the ≥90% coverage gate on `adapters/` + `risk/` (+ new modules).

## Step 5 — Quality gate (run all, must pass)
From `strategies/tfex-s50-multi-tf-swing/`, run via `uv run` (never bare python/pip):
- `uv run ruff check` and `uv run ruff format` (then re-verify `ruff format --check` — any
  post-format edit invalidates formatting)
- `uv run mypy` (strict)
- `uv run pytest` with coverage, confirming the ≥90% target on the gated paths
Report actual results; if anything fails, fix and re-run — do not push red.

## Step 6 — Docs / knowledge / memory updates
Update wherever Phase 5 changes the truth (only where relevant):
- `strategies/tfex-s50-multi-tf-swing/CLAUDE.md` — new modules, config/env vars, Phase 5 status,
  how setup/signal layers fit the architecture.
- `strategies/tfex-s50-multi-tf-swing/.claude/*` — any service-scoped knowledge/playbook for
  setup-detection logic or signal semantics.
- `strategies/tfex-s50-multi-tf-swing/docs/plans/ROADMAP.md` — mark Phase 5 progress/status.
- Umbrella `CLAUDE.md` and `.claude/*` — only if a cross-cutting contract changed (e.g.
  ingestion `extended_data` shape, feature-registry status line for `feature-tfex-integration`).
  Keep service-internal detail out of the umbrella.

## Step 7 — Commit & PR
Run the pre-push checklist (ruff check + format + mypy + pytest, matching CI) one final time.
Commit on the feature branch and open a PR to the service repo's default branch with a clear
title and a body summarizing scope, design, tests, coverage numbers, config/env additions, and
backward-compat impact. End the PR body with:
`🤖 Generated with [Claude Code](https://claude.com/claude-code)`
End the commit message with:
`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

After the commit/push/PR, report results as an ASCII box-drawing table (not a markdown pipe
table) with columns **Repo | Branch | Commit | GitHub**, one row per repo touched. Use
`owner/name (role)` for Repo, short SHA for Commit, and `PR #N → <url>` for GitHub.

## Guardrails
- Only modify the `strategies/tfex-s50-multi-tf-swing/` repo (plus umbrella docs if a cross-cut
  contract genuinely changed). Do not edit other sub-repos.
- Plan on disk BEFORE code. No tvkit direct calls. No secrets committed. No scope beyond the
  roadmap's Phase 5 — note any deferred items explicitly rather than over-building.

## Expected deliverables
1. New feature branch in `strategies/tfex-s50-multi-tf-swing/`.
2. `strategies/tfex-s50-multi-tf-swing/docs/plans/{phase_name}.md` (plan + embedded prompt, in
   the csm-set sample format).
3. Phase 5 setup-detection + signal-strategy implementation, fully typed, async-correct.
4. Unit + integration tests passing at ≥90% coverage on gated paths.
5. Green ruff/mypy(strict)/pytest.
6. Updated CLAUDE.md / .claude knowledge as needed.
7. Commit + PR to the service repo, followed by the ASCII git-result table.
```

---

## Scope

### In Scope (Phase 5 — §5.1 + §5.2 + §5.3 + §5.4 + a §5.5 harness/demo)

| Component | Description | Status |
|---|---|---|
| `SignalError` hierarchy | Module-local exceptions under `TfexS50Error` | Planned |
| `StrategyId` / `SetupDirection` Literals | `A`/`B`/`C`; `long`/`short` | Planned |
| `SetupSignal` | Frozen Pydantic: `strategy_id`, `time` (UTC), `direction`, `trigger_price`/`stop_reference` (**Decimal**), `reasons` | Planned |
| `SignalConfig` | Frozen Pydantic, bounded thresholds; env-overridable | Planned |
| `build_signal_inputs()` | Aligned 5m frame (`1h_*`/`4h_*`/`bias_direction`/`regime`), source-agnostic | Planned |
| Strategy A / B / C | `classify_frame` + `classify_row` + `to_signals` each | Planned |
| `ExecutionConfig` / `Trade` / `ExitReason` | Frozen Pydantic execution contracts | Planned |
| `simulate_trade()` / `simulate_signals()` | 5m trade simulation (next-bar fill, stop/TP/BE/time-stop) | Planned |
| `BacktestMetrics` / `metrics.py` / `per_strategy.py` | Expectancy / PF / max-DD / win-rate / regime-stratified | Planned |
| Settings + `.env.example` | `TFEX_S50_MULTI_TF_SWING_SIGNAL_*` / `_EXECUTION_*` + accessors | Planned |
| §5.5 demonstration | `scripts/per_strategy_backtest_demo.py` (public-safe artifact) | Planned |
| Test suite | `tests/unit/{signals,execution,backtest}/`, ≥ 90 % coverage | Planned |

### Out of Scope (deferred to later phases — noted, not built)

- **`risk/` position sizing** (Phase 7) — including the **200-THB/point** S50 multiplier and
  contract sizing. Signals/execution emit *sizing-ready* outputs (entry, structure stop,
  direction, R-multiple); Phase 7 consumes them. See D8.
- **Gateway `extended_data` (margin/contracts) + daily-report wiring** — the daily-pipeline
  phase. Phase 5 makes **no** gateway-contract change, exactly as Phase 3 / 4 did. See D9.
- **ML `P(fake_breakout)` / `P(continuation)` filters** (Phase 6) — Strategy C ships a
  documented hook; the filter is not implemented. See D6.
- **THB PnL + cost model** — Phase 5 metrics are in **points + R-multiples** only; the THB
  multiplier (Phase 7) and the cost model + Sharpe/Sortino + walk-forward harness (Phase 8) are
  out of scope. See D7.
- **Real-data positive-expectancy magnitude claim** (ROADMAP §5 exit criterion) — data-gated on
  the 5-year backfill (blocked on a TVKIT token / engine TFEX data), exactly like Phase 1's
  backfill and Phase 4 §4.3. Ships as a harness + synthetic tests + demonstration. See D10.
- **`4h` on the `engine` source** — `4h` stays **mirror-only** (engine declines it before any
  I/O, no local rollup); the unblocker is an engine `4h` route (a `quant-marketdata-engine`
  change). `signals/` is source-agnostic. See D11.

---

## Design Decisions

### D1 — `signals/` / `execution/` / `backtest/` are leaves fed by the un-normalised panel + bias + regime

The data flow (`CLAUDE.md`) is `data/ → features/ → regime/ → bias/ → signals/ → execution/ →
backtest/`. The new packages import from `features/`, `regime/`, `bias/` (and `signals/` from
`execution/`/`backtest/` direction only downstream), never from `api/`. Detection consumes a
panel built with **`FeatureConfig(normalise=False)`** — exactly like `regime/` and `bias/` —
because z-scored `ema_slope_*` / `dist_from_vwap` destroy the absolute signs the gates need.

### D2 — Multi-timeframe is resolved on the **5m aligned panel** (the look-ahead-critical part)

Setups span 4H (HTF bias) → 1H (MTF setup) → 5m (LTF trigger). Rather than join frames ad-hoc,
`signals/inputs.py:build_signal_inputs` reuses the Phase 2 causal aligner
(`features.pipeline.build_aligned` / `features.align.align_timeframes`) to widen the **5m**
panel with `1h_*` and `4h_*` feature columns, then causally aligns the per-4H **`bias_direction`**
and **`regime`** onto 5m via the same availability-shift (`time + TIMEFRAME_MINUTES[tf]`,
backward as-of join). Every HTF column on a 5m row therefore reflects only an HTF bar that had
**already closed** — no look-ahead. Detection then reads at/before the 5m bar; **entry fills the
next bar** (handled in `execution/`). A `test_inputs.py` causality test asserts no future
HTF/bias value can appear on a 5m row.

### D3 — Strategies mirror the `bias/` conservative-unanimity shape

Each strategy provides `classify_frame(df, *, config)` (vectorised Polars, appends
`{strat}_signal` direction Utf8 + `{strat}_reasons` `List[Utf8]`), `classify_row(features,
config)` (scalar, returns a `SetupSignal | None`), and `to_signals(frame)` (materialises the
emitted `SetupSignal`s). Like `bias/`, a setup fires only on **full agreement** of its gates;
any disagreement / null / insufficient lookback yields **no signal** (never a guess). A
frame-vs-row parity test asserts identical output for identical inputs, as the bias suite does.

### D4 — Gating reuses Phase 3 / Phase 4 contracts (nothing re-derived)

Each strategy consults `regime.policy.regime_to_strategies(regime)` (does this regime allow A /
B / C?) and `regime.policy.is_no_trade(regime, lunch_zone=...)`, and reads the aligned
`bias_direction` column as the HTF veto. The regime label and bias come pre-computed on the
aligned panel; the strategies never re-classify them.

### D5 — `SetupSignal` carries Decimal prices; feature scalars stay float

Prices are money (`OhlcvBar` uses `Decimal`), so `SetupSignal.trigger_price` /
`stop_reference` and every `Trade` price/PnL field are **`Decimal`**, cast Float64→Decimal at
the model boundary (the detection frame works in Float64). Internal feature-derived scalars
(ATR multiples, z-scores, deadbands) remain `float` — internal statistical quantities that never
cross a boundary (consistent with Phases 2–4).

### D6 — Strategy C's ML filter is a Phase-6 hook, not built

ROADMAP §5.3 says the `P(fake_breakout)` check is "Optional ML probability check (Phase 6)".
Strategy C ships the rule-based sweep + reversal + structure-shift detection and a documented
extension point; the ML filter itself is **Phase 6** and is not implemented here (the `ml/`
package does not exist). This mirrors the Phase 3 / 4 deferral honesty.

### D7 — PnL in points + R-multiples (no THB, no costs) this phase

The execution engine reports per-trade PnL as **points** and **R-multiples** (`r_multiple =
pnl_points / risk_points`, `risk_points = |entry − stop|`). It does **not** convert to THB
(needs the 200-THB/point multiplier, which hard-rule #1 says lives in `risk/sizing.py` — Phase 7)
and does **not** apply a cost model (Phase 8). Backtest metrics (expectancy, PF, max-DD) are
computed on the R / points series. This keeps the multiplier out of `execution/` (honouring the
hard rule) and avoids pre-building Phase 8's cost model.

### D8 — No `risk/` wiring; signals/execution are sizing-ready (ROADMAP-pure)

The task prompt references "how signals feed the existing `risk/` sizing", but `risk/` is
**Phase 7** per the ROADMAP and does not exist (the service `CLAUDE.md` states `risk/` joins the
coverage gate "once it lands (Phase 7)"). Resolving the conflict per the prompt's own rule
("sub-repo docs win for service-internal decisions" + "no scope beyond the roadmap's Phase 5"):
Phase 5 stays **ROADMAP-pure** — it builds no `risk/` and computes no position size. Instead,
`SetupSignal` (direction + entry + structure-anchored stop) and `Trade` (R-multiple) are exactly
the **sizing-ready inputs** the Phase 7 risk engine will consume. This matches how Phase 3 / 4
"stayed ROADMAP-pure" with no `risk/` wiring. *(Confirmed with the user as the chosen scope.)*

### D9 — No gateway `extended_data` / ingestion change this phase

The prompt also references the gateway ingestion contract / `extended_data`. Phase 5 makes **no**
change to `POST /api/v1/ingest/daily-report` or to any gateway table — identical to Phase 3 / 4.
Wiring daily signals into a daily-report payload (with TFEX `extended_data.report.contracts_*` /
`margin_usage`) is the later **daily-pipeline** phase, after `risk/` (Phase 7) provides sizing /
margin. The Phase 0 adapters carry forward unchanged. *(Confirmed with the user.)*

### D10 — §5.5 backtest: harness + synthetic tests + demonstration (data-gated exit deferred)

The ROADMAP §5 exit criterion ("positive expectancy after costs … stable across ≥ 2 regimes")
needs the 5-year backfill (data-gated, blocked on a TVKIT token / engine TFEX data) and a cost
model (Phase 8). Rather than fake it, Phase 5 ships the **per-strategy backtest harness**
(`backtest/metrics.py` + `per_strategy.py`), unit-tested on **synthetic** `Trade` sequences with
known expectancy / PF / max-DD, plus `scripts/per_strategy_backtest_demo.py` that runs the
strategies on a naive/synthetic proxy and writes a **public-safe** artifact (signal / trade
counts + R metrics only — **no raw OHLCV**) to `results/static/signals/`. The real-data
*magnitude* claim is **deferred → data-gated**, with an explicit ROADMAP note — mirroring
Phase 1's backfill gate and Phase 4 §4.3. *(Confirmed with the user.)*

### D11 — `signals/` is source-agnostic; `4h` stays mirror-only

`signals/` consumes already-loaded panels + the bias frame; it never calls tvkit / the engine /
a fetcher and owns no cookie. On the `engine` OHLCV source, `4h` is declined before any I/O
(`EngineTimeframeUnavailableError`, no local rollup — Decision D10 of the data layer), so the 4H
panel/bias is **absent**. `build_signal_inputs` handles a missing 4H panel gracefully (the
`4h_*` / `bias_direction` columns are filled neutral/null), so **A and B emit no signals** when
the HTF bias is unavailable (documented safe degrade), while **C** (best in `range_high_vol`,
not strictly HTF-bias-dependent) can still run. The unblocker is an engine `4h` route → a
one-line `_TF_TO_ENGINE` edit (a `quant-marketdata-engine` change, out of scope here). Tested on
both 4h-present (mirror) and 4h-absent (engine) paths.

### D12 — Execution engine is source-agnostic; raw-contract series for honest roll costs

`simulate_trade` accepts any 5m OHLCV frame. Phase 5 tests / the demo feed the continuous
(back-adjusted) series for simplicity; the docstring documents that the live / Phase-8 path
passes the **raw per-contract** series so roll costs stay honest (hard-rule #3 — back-adjusted
prices for *signals*, raw per-contract for *execution simulation*). The per-trade loop is
**bounded by `time_stop_bars`**, so the scan is O(N) per trade, never O(n²).

### D13 — Thresholds live in frozen config objects, env-overridable

`SignalConfig` and `ExecutionConfig` (frozen Pydantic, every field bounded) hold all tunables.
They are surfaced on `Settings` via `TFEX_S50_MULTI_TF_SWING_SIGNAL_*` / `_EXECUTION_*` and
`signal_config()` / `execution_config()` accessors (lazy import, mirroring `bias_config()` /
`regime_thresholds()`). No threshold is hard-coded at a call site. Defaults reproduce the
documented strategy-design behaviour, so an unset env = current behaviour.

### D14 — Strategy-design knowledge stays in `strategy-design.md`

The A/B/C + execution specifications already live in `.claude/knowledge/strategy-design.md`. This
phase adds an implementation-notes addendum there (gate thresholds → `SignalConfig`, the
sizing-ready contract, the deferred ML hook) rather than creating a new knowledge file — the
single source of truth for the strategy rules.

### D15 — Umbrella repo: only the feature-status line

Phase 5 changes no cross-cutting contract (ingestion untouched). The umbrella `CLAUDE.md`
feature-registry status line for `feature-tfex-integration` and the
`.claude/knowledge/feature-tfex-integration.md` status snapshot get a Phase 5 progress note;
nothing else cross-cutting changes.

---

## Strategy Rules

Encoded in `signals/`; thresholds from `SignalConfig` (defaults shown). All gates evaluated on
the **5m aligned panel** (HTF columns availability-shifted). `long` shown; `short` is the mirror.

### Strategy A — Pullback Continuation ⭐ (primary)

| Step | TF | Gate (long) |
|---|---|---|
| 1 | 4H | `bias_direction == "long"` **and** regime allows `A` (`"A" ∈ regime_to_strategies`) |
| 2 | 1H | pullback: `abs(1h_dist_from_vwap) ≤ pullback_band` **and** `1h_structure ∈ {HH,HL}` **and** `1h_atr_ratio ≤ atr_contraction_max` **and** `1h_volume_expansion ≤ volume_contraction_max` |
| 3 | 5m | compression: `bollinger_squeeze ≤ squeeze_max` **or** `atr_ratio ≤ atr_compression_max` |
| 4 | 5m | trigger: `close > or_high_{trigger_window}` (compression breakout) **and** `dist_from_vwap > 0` (VWAP reclaim) **and** `volume_expansion ≥ volume_expansion_min` |

`trigger_price` = the 5m breakout close; `stop_reference` = the most recent 5m swing low
(invalidation), refined by `execution/` to `entry − k·ATR` clamped to that level.

### Strategy B — Opening-Range Breakout

`close > or_high_{or_window}` (long) / `< or_low_{or_window}` (short), `or_window` default 15;
**and** `volume_expansion ≥ volume_expansion_min`; **and** `bias_direction` aligned; **and**
`lunch_zone_flag == 0`; **and** regime not `range_low_vol` and allows `B`. `trigger_price` = the
breakout close; `stop_reference` = the opposite opening-range extreme.

### Strategy C — Liquidity-Sweep Reversal

`liquidity_sweep_flag == 1` **and** a reversal confirmation: structure shift back through the
swept level (`dist_from_vwap` sign flips toward the reversal direction). Best in
`range_high_vol` (regime allows `C`); tolerated in trend regimes only on counter-trend retests.
Direction = the reversal direction (opposite the sweep). **ML `P(fake_breakout)` filter is a
Phase-6 hook** (a documented no-op extension point). `stop_reference` = beyond the swept extreme.

### Execution (5m) — `execution/engine.py`

- **Entry**: next-bar **open** after the trigger bar (no same-bar fill); reject if
  bar spread > `max_spread_mult × median spread`.
- **Stop**: `SL = entry − k_atr_stop · ATR` (long), clamped to `signal.stop_reference` (the
  nearest invalidation) so the stop sits where "the idea is wrong".
- **Take profit (hybrid)**: close `partial_fraction` (50 %) at `+partial_tp_r` (1R); trail the
  remainder behind structure (EMA20 / last swing proxy).
- **Breakeven**: move stop to entry `+ breakeven_buffer` once `+breakeven_at_r` (1R) is reached.
- **Time stop**: exit after `time_stop_bars` with no target; else `end_of_data` at frame end.
- Never widen a stop, never average down (hard rules).

---

## Implementation Steps

### Step 1: `signals/errors.py`
`SignalError(TfexS50Error)` root + `SignalInputError(SignalError)`. Import `TfexS50Error` from
`..adapters.errors`. `__all__`.

### Step 2: `signals/models.py`
`StrategyId` (`A`/`B`/`C`), `SetupDirection` (`long`/`short`) Literals + `get_args` tuples;
`SetupSignal` (frozen, Decimal prices, UTC `time` validator mirroring `RegimeClassification`);
`SignalConfig` (frozen, bounded thresholds per D13); `SetupFeatures` (frozen scalar inputs for
`classify_row`).

### Step 3: `signals/inputs.py`
`build_signal_inputs(panels, *, bias_frame, base_timeframe="5m", config)` — reuse `build_aligned`
to widen 5m with `1h_*`/`4h_*`, align `bias_direction` + `regime` causally, handle missing 4H
(engine source) by filling neutral. Returns the aligned 5m frame.

### Step 4: `signals/strategy_a.py`, `strategy_b.py`, `strategy_c.py`
Each: `REQUIRED_COLUMNS`, `classify_frame` (vectorised when/then gates → `{strat}_signal` +
`{strat}_reasons`), `classify_row` (scalar mirror → `SetupSignal | None`), `to_signals`
(materialise emitted signals). Gating via `regime.policy` + `bias_direction`. Helpers keep
public functions ≤ ~50 lines.

### Step 5: `signals/__init__.py`
Public re-exports.

### Step 6: `execution/errors.py`, `models.py`, `engine.py`, `__init__.py`
`ExecutionError`/`ExecutionInputError`; `ExitReason`, `Trade`, `ExecutionConfig`;
`simulate_trade` + `simulate_signals`; re-exports.

### Step 7: `backtest/errors.py`, `models.py`, `metrics.py`, `per_strategy.py`, `__init__.py`
`BacktestError`; `RegimeMetrics`/`BacktestMetrics`; pure metric functions (empty-safe) +
`regime_stratified`; `run_per_strategy_backtest`; re-exports.

### Step 8: Config + `.env.example`
Add `signal_*` / `execution_*` bounded `Field`s + `signal_config()` / `execution_config()`
accessors to `Settings`. Document the new vars in `.env.example`.

### Step 9: `pyproject.toml`
Extend `--cov` / `[tool.coverage.run] source` to `signals/`, `execution/`, `backtest/`.

### Step 10: §5.5 demonstration
`scripts/per_strategy_backtest_demo.py` — naive proxy → per-strategy metrics JSON to
`results/static/signals/` (public-safe).

### Step 11: Tests (`tests/unit/{signals,execution,backtest}/`)
Per-branch synthetic fixtures + factories; truth-table, parity, edge-case, and end-to-end tests.

---

## File Changes

| File | Action | Description |
|---|---|---|
| `src/tfex_s50_multi_tf_swing/signals/__init__.py` | CREATE | Public re-exports |
| `src/tfex_s50_multi_tf_swing/signals/errors.py` | CREATE | `SignalError` hierarchy |
| `src/tfex_s50_multi_tf_swing/signals/models.py` | CREATE | `StrategyId`, `SetupDirection`, `SetupSignal`, `SignalConfig`, `SetupFeatures` |
| `src/tfex_s50_multi_tf_swing/signals/inputs.py` | CREATE | `build_signal_inputs` (aligned 5m + bias + regime) |
| `src/tfex_s50_multi_tf_swing/signals/strategy_a.py` | CREATE | Pullback continuation (§5.1) |
| `src/tfex_s50_multi_tf_swing/signals/strategy_b.py` | CREATE | Opening-range breakout (§5.2) |
| `src/tfex_s50_multi_tf_swing/signals/strategy_c.py` | CREATE | Liquidity-sweep reversal (§5.3) |
| `src/tfex_s50_multi_tf_swing/execution/__init__.py` | CREATE | Public re-exports |
| `src/tfex_s50_multi_tf_swing/execution/errors.py` | CREATE | `ExecutionError` hierarchy |
| `src/tfex_s50_multi_tf_swing/execution/models.py` | CREATE | `ExitReason`, `Trade`, `ExecutionConfig` |
| `src/tfex_s50_multi_tf_swing/execution/engine.py` | CREATE | `simulate_trade` + `simulate_signals` (§5.4) |
| `src/tfex_s50_multi_tf_swing/backtest/__init__.py` | CREATE | Public re-exports |
| `src/tfex_s50_multi_tf_swing/backtest/errors.py` | CREATE | `BacktestError` |
| `src/tfex_s50_multi_tf_swing/backtest/models.py` | CREATE | `RegimeMetrics`, `BacktestMetrics` |
| `src/tfex_s50_multi_tf_swing/backtest/metrics.py` | CREATE | Expectancy / PF / max-DD / regime-stratified |
| `src/tfex_s50_multi_tf_swing/backtest/per_strategy.py` | CREATE | `run_per_strategy_backtest` (§5.5) |
| `src/tfex_s50_multi_tf_swing/config/settings.py` | MODIFY | `signal_*` / `execution_*` fields + accessors |
| `.env.example` | MODIFY | Document `TFEX_S50_MULTI_TF_SWING_SIGNAL_*` / `_EXECUTION_*` |
| `pyproject.toml` | MODIFY | Add `signals/`, `execution/`, `backtest/` to coverage scope |
| `scripts/per_strategy_backtest_demo.py` | CREATE | §5.5 public-safe per-strategy metric demo |
| `tests/unit/signals/conftest.py` | CREATE | Synthetic per-branch fixtures + factories |
| `tests/unit/signals/test_models_errors.py` | CREATE | Model / error tests |
| `tests/unit/signals/test_inputs.py` | CREATE | Alignment causality + missing-4H paths |
| `tests/unit/signals/test_strategy_a.py` | CREATE | A truth table (entry/no-entry/false-trigger) |
| `tests/unit/signals/test_strategy_b.py` | CREATE | B truth table + lunch/range_low_vol suppress |
| `tests/unit/signals/test_strategy_c.py` | CREATE | C sweep/reversal truth table |
| `tests/unit/signals/test_end_to_end.py` | CREATE | panels → inputs → detect → simulate → metrics |
| `tests/unit/execution/test_models_errors.py` | CREATE | Execution model / error tests |
| `tests/unit/execution/test_engine.py` | CREATE | TP/SL/BE/time-stop/next-bar-fill/spread-reject |
| `tests/unit/backtest/test_metrics.py` | CREATE | Known-value metrics + regime stratification + empty |
| `tests/unit/backtest/test_per_strategy.py` | CREATE | Per-strategy runner wiring |
| `docs/plans/phase-5-setup-detection-signals.md` | CREATE | This plan |
| `docs/plans/ROADMAP.md` | MODIFY | Tick §5.1–5.4; §5.5 harness/demo; defer exit metric; dated Notes |
| `CLAUDE.md` | MODIFY | signals/execution/backtest layer sections; env vars; coverage scope |
| `README.md` | MODIFY | New modules + env vars (if present) |
| `.claude/knowledge/strategy-design.md` | MODIFY | Implementation-notes addendum |

---

## Test Plan

Deterministic, fixture-driven, no network. Mirrors source layout under `tests/unit/`.

- **`signals/conftest.py`** — builders producing an aligned 5m frame deterministically classified
  into each branch per strategy (clean A long/short entry, A no-entry on each failed gate, A
  false-trigger; B breakout + suppress on lunch / range_low_vol; C sweep+reversal vs no-confirm),
  plus `SetupFeatures` factories. Because `structure` is frequently null on sparse synthetic
  pivots, classifier tests build input frames per-branch directly (one row per gate), as Phase
  3 / 4 did; one end-to-end test exercises `build_signal_inputs`.
- **`signals/test_inputs.py`** — alignment **causality** (no future `1h_*`/`4h_*`/`bias_direction`
  value leaks onto an earlier 5m row); 4h-present (mirror) vs 4h-absent (engine) → A/B emit no
  signals when bias absent, C still runs; missing-column → `SignalInputError`; empty/short frame.
- **`signals/test_strategy_{a,b,c}.py`** — per-strategy truth tables; bias veto; regime gating;
  lunch-zone + range_low_vol suppression (B); `classify_row` agrees with `classify_frame`
  row-for-row; `to_signals` emits exactly the fired setups; conflicting HTF/LTF bias → no signal.
- **`execution/test_engine.py`** — long & short TP hit, SL hit, breakeven-then-stop, time-stop,
  partial-TP + trail, **next-bar-open fill** (assert no same-bar look-ahead), spread reject,
  `end_of_data`; `r_multiple` / `pnl_points` correctness; tz-aware UTC entry/exit times.
- **`backtest/test_metrics.py`** — hand-built `Trade` lists with known expectancy / PF / max-DD /
  win-rate; regime stratification; **empty trades** safe (zero/None, no divide-by-zero).
- **`backtest/test_per_strategy.py`** — `run_per_strategy_backtest` wires detect → simulate →
  metrics and returns a well-formed `BacktestMetrics`.
- **`signals/test_end_to_end.py`** — reader-style panels → `build_signal_inputs` →
  `strategy_a.to_signals` → `simulate_signals` → `backtest.metrics` produces a valid
  `BacktestMetrics` (the integration path the prompt asks for, minus the deferred risk/ingestion).

Coverage gate: `--cov-fail-under=90` now also covers `signals/`, `execution/`, `backtest/`
(target ≥ 90 % on each; existing gated paths stay green).

---

## Success Criteria

- [ ] `build_signal_inputs` produces an aligned 5m frame with `1h_*`/`4h_*`/`bias_direction`/
      `regime`; causality test proves no future HTF leak.
- [ ] Each strategy's `classify_frame` emits only `long`/`short`/no-signal; `classify_row` agrees
      row-for-row; `to_signals` count == fired-setup count.
- [ ] Bias veto + regime policy gate every strategy; B suppressed in lunch zone / `range_low_vol`.
- [ ] When the `engine` source omits `4h`, A/B emit no signals (safe degrade); C still runs.
- [ ] `simulate_trade` fills next bar (no look-ahead), honours `k·ATR` structure stop, partial
      TP + trail, breakeven, time stop; `Trade` carries Decimal prices + R-multiple.
- [ ] `backtest.metrics` returns expectancy / PF / max-DD / win-rate / per-regime; empty-safe.
- [ ] Thresholds read from `Settings` / `SignalConfig` / `ExecutionConfig`; none hard-coded.
- [ ] `signals/`/`execution/`/`backtest/` import nothing from `api/`, build no `risk/`, change no
      gateway contract, and never fetch tvkit.
- [ ] §5.5 demo artifact is public-safe (no raw OHLCV); real-data exit metric deferred.
- [ ] `uv run ruff check . && uv run ruff format --check .` clean.
- [ ] `uv run mypy src tests` clean (strict).
- [ ] `uv run pytest` green with ≥ 90 % coverage including the three new packages.
- [ ] Ingestion contract + Phase 0–4 behaviour unchanged (additive only).

---

## Risks

1. **Multi-TF look-ahead.** The single most dangerous trap. Mitigation: reuse the proven
   `align_timeframes` availability-shift; a dedicated causality test asserts no future HTF/bias
   value reaches an earlier 5m row.
2. **Synthetic fixtures may not cleanly separate setups.** Mitigation: build each fixture to
   satisfy exactly one branch; assert against thresholds, not magic numbers; reuse the per-branch
   frame approach (`structure` null on sparse pivots).
3. **Execution loop performance.** Mitigation: bound the per-trade forward scan by
   `time_stop_bars` → O(N); fan-out across signals is a simple comprehension, no nested rescans.
4. **Scope creep into Phase 7/8.** Mitigation: D7/D8/D9 fix the boundary — points+R only, no
   `risk/`, no gateway change; deferrals noted in the ROADMAP.
5. **§5.5 magnitude over-claim.** Mitigation: harness + synthetic tests + demo only; the
   positive-expectancy figure is explicitly data-gated/deferred in the ROADMAP.

---

## Completion Notes

### Summary

Shipped ROADMAP §5.1–§5.4 as three new leaf packages and a §5.5 harness, all pure offline Polars
library code (one-way `features/ + regime/ + bias/ → signals/ → execution/ → backtest/`):

- **`signals/`** — `errors`, `models`, `inputs` (`build_signal_inputs`), `base` (shared
  gate/reason/materialiser helpers), and `strategy_a/b/c`. Each strategy mirrors the bias shape
  (`classify_frame` / `classify_row` / `to_signals`), gated by the Phase-4 `bias_direction` veto
  and the Phase-3 `regime_to_strategies` policy on a causally aligned 5m frame.
- **`execution/`** — `Trade` / `ExecutionConfig` / `ExitReason` + `simulate_trade` /
  `simulate_signals`: next-bar-open fill, `k·ATR` structure-clamped stop, full-TP or partial-TP +
  trailing remainder, breakeven, time stop, end-of-data; PnL in points + R only.
- **`backtest/`** — `metrics` (expectancy / profit factor / max-DD / win-rate / regime-stratified,
  all empty-safe) + `per_strategy.run_per_strategy_backtest` wiring detect → simulate → metrics.
- **Config** — `signal_*` / `execution_*` fields + `signal_config()` / `execution_config()` on
  `Settings`, `.env.example` documented; coverage gate extended to the three packages.
- **§5.5 demo** — `scripts/per_strategy_backtest_demo.py` writes a public-safe metrics JSON
  (counts + R only, no OHLCV) to `results/static/signals/`.

Stayed ROADMAP-pure (Design Decisions D8/D9): no `risk/`, no gateway `extended_data` change, no
FastAPI endpoint, no ML filter (Phase 6 hook in C). The real-data positive-expectancy magnitude
claim is deferred → data-gated (D10).

### Issues Encountered

1. **`STRATEGY_ID = "A"` inferred as `str`** under mypy strict; annotated as `StrategyId` (and the
   `classify_row` `direction` local as `SetupDirection`) to satisfy the Literal contracts.
2. **Full take-profit was unreachable** because the hybrid policy banks a partial then trails — the
   terminal reason is `trailing_stop`. Added a `take_profit` exit when `partial_fraction >= 1.0`
   (full close at target) so the literal is both reachable and semantically honest.
3. **`take_profit`/`trailing_stop`** distinction documented: a 50 %-partial run never reports
   `take_profit`; that reason only appears with `partial_fraction = 1.0`.

### Quality-gate output (2026-06-03)

- `ruff check .` — All checks passed.
- `ruff format --check .` — 128 files already formatted.
- `mypy src tests` — Success: no issues found in 120 source files.
- `pytest` — 440 passed, 5 skipped; total coverage **97.17 %** (`signals/` 96–100 %, `execution/`
  98–100 %, `backtest/` 100 %); ≥ 90 % gate met.
- `bandit -r src` — 0 issues.  `pip-audit` — no known vulnerabilities.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Opus 4.8)
**Status:** Complete
**Completed:** 2026-06-03
