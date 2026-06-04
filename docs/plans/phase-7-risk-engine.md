# Phase 7 — Risk Engine

**Feature:** Risk Engine — contract sizing + risk guards for the S50 swing strategy
**Branch:** `feature/phase-7-risk-engine`
**Created:** 2026-06-04
**Status:** Complete
**Completed:** 2026-06-04
**Depends On:** Phase 5 (Setup Detection & Signals) ✓, Phase 6 (ML Probability Filter) ✓

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

Every layer shipped so far (Phases 0–6: data → features → regime → HTF bias →
signals/execution/backtest → ML filter) emits **sizing-ready** outputs in *points + R-multiples*
— no THB, no contracts, no risk guards. Phase 7 adds the `risk/` leaf package that turns those
outputs into **contract-sized, risk-guarded trade decisions**.

Per the project's own hard rule, **the Risk Engine is more important than any signal** — a great
signal with bad risk dies within a year; an average signal with great risk survives a decade. The
engine must survive every regime. This is the last code phase before Phase 8 (walk-forward
backtest), which will *drive* the risk engine; Phase 7 ships the building blocks + a pure
orchestrator, wired into nothing downstream.

### Parent Plan Reference

- `docs/plans/ROADMAP.md` — **Phase 7 — Risk Engine** (§7.1 Position Sizing, §7.2 Daily & Streak
  Limits, §7.3 Volatility Scaling, §7.4 Kill Switch, §7.5 Capital Deployment Ladder).
- `.claude/knowledge/risk-engine.md` — the authoritative spec (sizing formula, the
  100k/1%/5pt → 1-contract worked example, hard-stop table, volatility scaling, kill-switch
  triggers, capital ladder, "what NOT to do").

### Key Deliverables

1. `src/tfex_s50_multi_tf_swing/risk/` — `errors.py`, `models.py`, `sizing.py`, `limits.py`,
   `killswitch.py`, `ladder.py`, `decision.py`, `__init__.py`.
2. `RiskConfig` on `Settings` (`TFEX_S50_MULTI_TF_SWING_RISK_*`, `risk_config()`).
3. `tests/unit/risk/` ≥ 90 % coverage incl. the worked-example sizing test and the kill-switch
   fault-injection test; `risk/` joined to the enforced coverage set.
4. Updated ROADMAP status, `CLAUDE.md`, `risk-engine.md` knowledge, a kill-switch / capital-ladder
   playbook, and the memory pointer.

---

## AI Prompt

The following prompt was used to generate this phase (verbatim):

```
🎯 OBJECTIVE
Implement Phase 7 — Risk Engine for the strategies/tfex-s50-multi-tf-swing repo (a sub-repo of
the quant-trading-system umbrella, with its own git remote github.com/lumduan/tfex-s50-multi-tf-swing).
This phase adds a new leaf package src/tfex_s50_multi_tf_swing/risk/ that turns the sizing-ready
outputs of the Phase-5 signals/ + execution/ layers into contract-sized, risk-guarded trade
decisions. Per the ROADMAP and the project's own hard rule, the Risk Engine is more important
than any signal — it must survive every regime.

Work cd strategies/tfex-s50-multi-tf-swing and treat that as the project root for all relative
paths below. Do NOT edit any sibling sub-repo's history.

0. READ FIRST (do not skip — these are the source of truth)
- ../../CLAUDE.md (umbrella system map + ingestion contract + roadmap status table)
- CLAUDE.md (this repo's agent guide — note the "Hard rules — TFEX-specific" and the risk/
  references already seeded in the layering diagram and coverage list)
- docs/plans/ROADMAP.md — Phase 7 — Risk Engine (§7.1 Position Sizing, §7.2 Daily & Streak
  Limits, §7.3 Volatility Scaling, §7.4 Kill Switch, §7.5 Capital Deployment Ladder) and the
  Dependency Map (Phase 5 → Phase 7 → Phase 8)
- .claude/knowledge/risk-engine.md — the authoritative spec: position-sizing formula, the
  100k/1%/5pt → 1 contract worked example, hard-stop table, volatility scaling, kill-switch
  triggers, capital-deployment ladder, "what NOT to do"
- .claude/knowledge/strategy-design.md and the existing Phase-5 packages
  src/tfex_s50_multi_tf_swing/signals/, src/tfex_s50_multi_tf_swing/execution/,
  src/tfex_s50_multi_tf_swing/backtest/ — understand the exact shape of SetupSignal / execution
  outputs the risk engine must consume (stop distance in points, R-multiples, raw vs
  back-adjusted series), and mirror their package idiom (errors.py / models.py / config-driven
  thresholds / classify_frame-style vectorised + scalar entry points)
- src/tfex_s50_multi_tf_swing/regime/ — reuse the existing regime label for the panic/high-vol
  gates; never re-derive it
- The plan-doc format reference: ../csm-set/docs/plans/examples/phase1-sample.md (Overview → AI
  Prompt → Scope → Design Decisions → Implementation Steps → File Changes → Success Criteria →
  Completion Notes)

1. CREATE A BRANCH
- New branch off the current default branch: feature/phase-7-risk-engine.

2. PLAN BEFORE CODE (write the plan file first)
Before writing any implementation code, author the phase plan at:
  docs/plans/phase-7-risk-engine.md
following the section structure of ../csm-set/docs/plans/examples/phase1-sample.md. It MUST
include:
- A header block (Feature / Branch / Created date = today / Status / Depends On: Phase 5 ✓,
  Phase 6 ✓)
- An "AI Prompt" section that embeds this entire prompt verbatim inside a fenced block (so the
  plan is self-reproducing, exactly like the sample)
- Scope (what ships now vs explicitly deferred), Design Decisions (numbered Dxx with rationale —
  at minimum: the 200-THB/pt multiplier as a single named constant; Decimal-vs-float boundary for
  money; how stop-distance-in-points flows from execution/; whether the kill switch is a pure
  library guard + env flag now with the admin endpoint deferred until api/ lands; how the capital
  ladder is encoded as runtime guards), Implementation Steps, File Changes table, Success
  Criteria, and a Completion Notes section to fill in at the end.
After the plan is written, implement against it and keep it honest (mark deferrals truthfully —
match the ROADMAP's "data-gated / deferred" discipline used by Phases 3–6; never fake a backtest
or a magnitude claim).

3. IMPLEMENTATION — src/tfex_s50_multi_tf_swing/risk/
New leaf package (one-way dependency signals/ + execution/ + regime/ → risk/; it must import
NOTHING downstream — no backtest/, no live/, no api/). Mirror the existing package conventions
exactly.

3.1 risk/sizing.py — Position Sizing
- position_size = account_risk / (stop_distance × multiplier), rounded DOWN to whole contracts
  (you cannot trade a fractional S50 future); a sub-1-contract result ⇒ 0 contracts (no trade),
  not a rounded-up 1.
- The S50 multiplier = 200 THB per index point is a single named module-level constant (per TFEX
  hard rule #1 — "encoded in src/tfex_s50_multi_tf_swing/risk/sizing.py as a constant, never
  hardcoded inline elsewhere").
- Default account_risk = 1% of equity (config-driven, not hardcoded at call sites).
- Volatility-scaled by construction: wider stop ⇒ smaller size.
- Money quantities (equity, risk-amount, margin) are Decimal, never float at any boundary that
  can reach the gateway; stop distance / points may be float internally but document the
  boundary. Serialise decimals as strings on the wire.
- Unit-test the verbatim worked example: equity 100,000 THB, 1% risk, 5-pt stop, 200 THB/pt ⇒
  exactly 1 contract; plus wider-stop-shrinks-size and the sub-1-contract→0 boundary.

3.2 risk/limits.py — Daily & Streak Limits (+ no-averaging-down)
- Daily loss limit: cumulative −2R for the session ⇒ stop trading today.
- Consecutive-loss limit: 3 losses in a row ⇒ pause until next session.
- Daily trade-count cap (configurable) to prevent tilt.
- Encode and TEST TFEX hard rule #4 "No averaging down" here (a new entry that increases exposure
  in the direction of an existing losing position is rejected) and hard rule "never widen a stop
  after entry."
- Model the session-state machine cleanly (a frozen-ish stateful guard or an immutable "apply
  event → new state" reducer) so it is deterministic and unit-testable across boundary cases.

3.3 Volatility Scaling
- Scale size down (e.g., halve) when realised vol breaches a high percentile; no-trade at an
  extreme percentile (panic regime). Reuse the existing regime/ label and the Phase-2
  realised-vol-percentile feature — do not recompute regime.

3.4 Kill Switch (TFEX hard rule #8 — overrides everything)
- Detect abnormal spread (e.g., > k × median), latency-budget breach, broker-disconnect/API-error
  spike, market halt, and daily-loss-limit-hit ⇒ flatten all positions + halt new entries.
- Manual kill switch via env flag (TFEX_S50_MULTI_TF_SWING_*) now; the admin endpoint is deferred
  until the api/ package exists (note this explicitly — Phases 3–6 deliberately added no FastAPI
  endpoint, stay ROADMAP-pure). Provide a typed KillSwitchState that any later live/API layer can
  consume.

3.5 Capital Deployment Ladder (§7.5)
- Encode the Paper(0) → Micro-Live(1) → Validated(2) → Scale ladder as runtime guards (a function
  that, given a deployment stage + evidence inputs, caps max contracts). No scaling without
  evidence (hard rule: "scale only on statistical evidence, never on confidence").

3.6 Config & errors
- RiskConfig (frozen Pydantic, bounded fields) surfaced on the existing Settings via env prefix
  TFEX_S50_MULTI_TF_SWING_RISK_* and a Settings.risk_config() accessor — mirror how
  regime_thresholds() / bias_config() / signal_config() already work. No threshold hardcoded at a
  call site; an unset env must reproduce the documented defaults.
- risk/errors.py with module-local exceptions inheriting the shared TfexS50Error base. Never
  raise Exception(...) / except Exception: pass.
- risk/models.py Pydantic models for inputs/outputs (e.g., PositionSizeRequest /
  PositionSizeResult, RiskDecision, SessionRiskState, KillSwitchState). Pydantic at every
  boundary; never raw dicts.
- risk/__init__.py public re-exports.

ROADMAP-purity (match Phases 3–6): no gateway extended_data change, no FastAPI endpoint, no live/
wiring, no walk-forward (Phase 8). The risk engine consumes Phase-5 sizing-ready outputs and emits
contract-sized, guarded decisions that Phase 8 will drive.

4. QUALITY BAR (non-negotiable — matches the repo CI gate)
- from __future__ import annotations atop every src/ module; type-safe throughout; mypy strict
  clean (uv run mypy src tests).
- logger = logging.getLogger(__name__) with %-formatting; never print in src/.
- File ≤ ~400 lines, functions ≤ ~50 lines.
- Coverage ≥ 90% with risk/ added to the enforced set (update the cov config so risk/ joins
  adapters/ data/ features/ regime/ bias/ signals/ execution/ ml/). Tests mirror source layout
  under tests/unit/risk/. Cover boundary cases explicitly: zero/negative equity, zero stop
  distance (must raise a typed error, never divide-by-zero), exactly-at-limit vs just-over-limit
  for −2R and the 3-loss streak, panic-regime no-trade, and a fault-injection test that proves the
  kill switch flattens + halts (this is a named Phase-7 exit criterion).
- Determinism: no wall-clock or RNG leaking into pure logic; inject "now"/session date.
- Security/safety: validate all inputs at the Pydantic boundary; no secrets in repo; the 200
  multiplier and all limits come from constants/config, not magic numbers at call sites.
- Run the full gate locally and paste real output before pushing:
  uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest
  (Re-run ruff format --check after any late sed/manual edit — a post-format edit invalidates
  formatting.)

5. DOCS / KNOWLEDGE / MEMORY UPDATES (only where warranted)
- docs/plans/ROADMAP.md: tick the Phase 7 sub-items that shipped, mark any deferrals [-] with a
  one-line honest reason, and update the Current Status section (active phase → Phase 8; add the
  Phase-7 completion line + plan link, matching the Phase-6 entry's style).
- CLAUDE.md (this repo): add a "Phase 7 — risk layer" subsection under Architecture (mirroring the
  Phase 5/6 subsections), and confirm the "risk/ joins the list once it lands (Phase 7)" coverage
  note is now satisfied.
- .claude/knowledge/risk-engine.md: append implementation notes / any design decisions or gotchas
  discovered (keep the spec authoritative).
- If a kill-switch / capital-ladder operational runbook is warranted, add it under
  .claude/playbooks/ and cross-link from CLAUDE.md's "Where to look next".
- ../../CLAUDE.md (umbrella): only touch if the umbrella status table genuinely needs it (the tfex
  per-strategy roadmap lives in the sub-repo, not the umbrella — do not duplicate phase detail
  upward; a one-line status nudge is the most that belongs here, if anything).
- ../../.claude/*: update only if a genuinely cross-cutting note changes; otherwise leave it.
- Persist any durable, non-obvious cross-session fact to the memory dir and add a one-line pointer
  to MEMORY.md — e.g. update the existing project-tfex-s50-strategy.md entry with "Phase 7 Risk
  Engine shipped <date>" rather than creating a duplicate.

6. COMMIT, PUSH, PR
- Conventional Commits, tight scope. Commit inside the strategies/tfex-s50-multi-tf-swing sub-repo
  against its own remote; push feature/phase-7-risk-engine; open a PR to that repo's default
  branch with a body summarising scope, design decisions, what's deferred (and why), and the local
  gate output. End the PR body with the standard Claude Code attribution line.
- After the push/PR, report the result as an ASCII box-drawing table (not a markdown pipe table)
  with columns Repo | Branch | Commit | GitHub.

EXPECTED DELIVERABLES (summary)
1. docs/plans/phase-7-risk-engine.md (plan written first, embeds this prompt, completion notes
   filled).
2. src/tfex_s50_multi_tf_swing/risk/ — __init__.py, errors.py, models.py, sizing.py, limits.py,
   plus volatility-scaling / kill-switch / capital-ladder logic.
3. RiskConfig on Settings (TFEX_S50_MULTI_TF_SWING_RISK_*, risk_config()).
4. tests/unit/risk/ ≥ 90% coverage incl. the worked-example sizing test and the kill-switch
   fault-injection test; full gate green.
5. Updated ROADMAP status, CLAUDE.md, risk-engine knowledge (+ playbook if warranted), memory
   pointer.
6. Commit + PR on the sub-repo, with the ASCII result table.

Stay strictly within Phase 7 scope. If anything is genuinely blocked, defer it explicitly and
honestly in the plan and ROADMAP rather than faking it — exactly as Phases 3–6 did.
```

---

## Scope

### In Scope (Phase 7)

| Component | Description | Status |
|---|---|---|
| `risk/errors.py` | `RiskError` base + `RiskInputError` / `RiskLimitError` / `RiskConfigError` | Complete |
| `risk/models.py` | All frozen Pydantic I/O models + `RiskConfig` + `DeploymentStage` / trigger literals | Complete |
| `risk/sizing.py` | `S50_MULTIPLIER` constant, `compute_position_size`, `volatility_scale_factor` | Complete |
| `risk/limits.py` | Session reducer, daily-loss / streak / trade-count gates, no-avg-down, no-widen-stop | Complete |
| `risk/killswitch.py` | `evaluate_kill_switch` (spread / latency / broker / halt / daily-loss / manual) | Complete |
| `risk/ladder.py` | `max_contracts_for_stage` runtime guard + `LadderEvidence` | Complete |
| `risk/decision.py` | `evaluate_entry` orchestrator (kill-switch-first, regime/vol, limits, sizing, ladder cap) | Complete |
| `risk/__init__.py` | Public re-exports | Complete |
| `RiskConfig` on `Settings` | `TFEX_S50_MULTI_TF_SWING_RISK_*` + `risk_config()` | Complete |
| `tests/unit/risk/` | ≥ 90 % coverage incl. the two named exit-criterion tests | Complete |
| Coverage gate | `risk/` joined to `pyproject.toml` cov set | Complete |
| Docs / knowledge / playbook / memory | ROADMAP, CLAUDE.md, risk-engine.md, kill-switch playbook | Complete |

### Out of Scope / Deferred (Phase 7)

- **Kill-switch admin endpoint** — deferred until the `api/` package lands. Phases 3–6 added no
  FastAPI endpoint; `risk/` ships a pure library guard + a manual env flag + a typed
  `KillSwitchState` a future live/API layer consumes.
- **Capital-ladder "≥ 6 months live" evidence actuals** — data-gated. The guard *encodes* the
  rule today; the real `months_live` / stable-expectancy / drawdown-within-budget inputs arrive
  in Phase 9 (paper) / Phase 10 (live).
- **Wiring into `backtest/` / `live/`** — Phase 8 drives the engine. `decision.evaluate_entry` is
  a pure, importable entry point, not yet called by any downstream layer.
- **Cost model / THB PnL accounting in `execution/`** — the multiplier lives in `risk/` for
  sizing; turning simulated R-multiples into THB equity curves is Phase 8.
- **`extended_data.report.margin_usage` gateway field** — wired in a later pipeline phase, not
  here (ROADMAP-pure).

---

## Design Decisions

### D1 — `S50_MULTIPLIER` is a single named constant

`S50_MULTIPLIER: Final[Decimal] = Decimal("200")` lives only in `risk/sizing.py` (TFEX hard
rule #1). Every consumer imports it; it is never re-typed inline. `Decimal` (not `float`) because
it is a money multiplier.

### D2 — Decimal-vs-float boundary

Money is `Decimal` end-to-end: `equity`, `risk_amount`, the `S50_MULTIPLIER`, and `stop_distance`
(the `SetupSignal.trigger_price` / `stop_reference` it derives from are already `Decimal`). The
sizing division is therefore exact `Decimal` arithmetic. Statistical inputs (`rv_percentile`) stay
`float` — internal quantities that never cross the gateway, exactly as Phases 2/3 established. The
volatility scale factor is a quantised `Decimal` so the size computation stays in one numeric
domain. Decimals serialise as strings on the wire.

### D3 — Floor to whole contracts; sub-1 ⇒ 0

`raw_contracts.quantize(Decimal("1"), rounding=ROUND_DOWN)`. You cannot trade a fractional S50
future, and rounding *up* would silently increase risk beyond the 1 % budget. A sub-1-contract
result is **0 contracts (no trade)**, never a rounded-up 1.

### D4 — Stop distance flows in from `execution/` / `signals/`

The caller derives `stop_distance = abs(entry − stop)` from a `SetupSignal`
(`trigger_price − stop_reference`) or an execution `Trade` (`entry − stop`) — both already
`Decimal` — and passes it on `PositionSizeRequest.stop_distance_points`. `risk/` does not reach
back into `signals/`/`execution/` to recompute it (keeps the leaf dependency one-way and the math
honest about roll-aware raw prices, hard rule #3). A zero or negative stop distance ⇒
`RiskInputError` **before** any division (no divide-by-zero).

### D5 — `account_risk` default 1 % is config-driven

`RiskConfig.risk_per_trade_pct` defaults to `0.01` (bounded `gt 0, le 1`). No call site hardcodes
1 %. An unset env reproduces the documented default.

### D6 — Volatility scaling reuses the regime label, never recomputes it

`volatility_scale_factor` takes the *already-classified* `Regime` and the Phase-2 `rv_percentile`
as inputs and composes two caps: (a) the regime cap from
`regime.policy.regime_to_size_multiplier` (panic → 0.5, range_low_vol → 0, others → 1.0), and
(b) a percentile cap that halves size when `rv_percentile ≥ high_vol_percentile`. The final factor
is `min(regime_cap, percentile_cap)`. **Panic ⇒ no-trade (0)** when `panic_no_trade` is set
(default `True`) — deliberately stricter than the regime policy's "≤ 50 % if a clear setup"
because the risk engine has the final say and the spec says "do not trade" at the extreme
percentile. This is configurable, so a future, validated, reduced-size-in-panic policy is a config
flip, not a code change.

### D7 — Session limits are an immutable reducer

`SessionRiskState` is frozen. `register_outcome(state, outcome, config) → SessionRiskState`
returns a new state (cumulative R, consecutive-loss counter reset on a win, trade count, and the
`halted` flag set when `cumulative_r ≤ −daily_loss_limit_r`, `consecutive_losses ≥
max_consecutive_losses`, or `trades_today ≥ max_trades_per_day`). `can_open(state, config)` reads
the state. Deterministic — the session date is injected via `start_session(session_date)`; no
wall-clock, no RNG.

### D8 — No-averaging-down and no-widen-stop are encoded + tested

`assert_no_average_down(open_position, new_direction, *, position_is_losing)` raises
`RiskLimitError` when a new entry would increase exposure in the **same direction** as an existing
**losing** position (TFEX hard rule #4). `assert_stop_not_widened(direction, original_stop,
new_stop)` raises when a stop is moved further from entry after the fact ("never widen a stop after
entry").

### D9 — Kill switch: pure library guard + env flag now; admin endpoint deferred

`evaluate_kill_switch(health, session_state, config) → KillSwitchState` is a pure function. Manual
engagement is the `TFEX_S50_MULTI_TF_SWING_RISK_KILL_SWITCH_ENGAGED` env flag (surfaced on
`RiskConfig.kill_switch_engaged`). The **admin endpoint is explicitly deferred** until the `api/`
package exists — Phases 3–6 added no FastAPI endpoint and Phase 7 stays ROADMAP-pure.
`KillSwitchState` (frozen, typed) is the contract a later live/API layer consumes.

### D10 — Kill switch overrides everything

`decision.evaluate_entry` evaluates the kill switch **first**. If engaged, it returns a no-trade
`RiskDecision` (0 contracts, `flatten_positions=True`, `halt_entries=True`) regardless of how good
the setup is (TFEX hard rule #8).

### D11 — Capital ladder is a runtime guard, evidence is data-gated

`max_contracts_for_stage(stage, evidence, config) → int` caps contracts by deployment stage:
paper → 0, micro_live → 1, validated → 2 (only when `evidence.months_live ≥
validated_min_months_live` **and** `evidence.expectancy_stable` **and**
`evidence.drawdown_within_budget`, else it caps down to micro_live), scale → a careful step-up
gated on the same evidence. "Scale only on statistical evidence, never on confidence." The guard
encodes the rule now; the real evidence inputs are produced by Phase 9/10 (data-gated).

### D12 — ROADMAP-pure

No gateway `extended_data` change, no FastAPI endpoint, no `live/` wiring, no walk-forward.
`decision.evaluate_entry` is a pure library entry point and is **not** imported by `backtest/`.
Phase 8 will drive it.

### D13 — `RiskConfig` surfaced on `Settings`

`Settings` gains `TFEX_S50_MULTI_TF_SWING_RISK_*` bounded fields + a `risk_config()` lazy-import
accessor, mirroring `regime_thresholds()` / `bias_config()` / `signal_config()` /
`ml_filter_config()`. `RiskConfig` is added to the `TYPE_CHECKING` import block. An unset env
reproduces the documented defaults.

---

## Implementation Steps

### Step 1: `risk/errors.py`
`RiskError(TfexS50Error)` base; `RiskInputError`, `RiskLimitError`, `RiskConfigError` subclasses.

### Step 2: `risk/models.py`
`DeploymentStage` + `KillSwitchTrigger` literals; `RiskConfig`, `PositionSizeRequest`,
`PositionSizeResult`, `TradeOutcome`, `SessionRiskState`, `OpenPosition`, `LadderEvidence`,
`MarketHealth`, `KillSwitchState`, `RiskDecision`. All frozen; money fields `Decimal`; UTC
validators where a timestamp is carried.

### Step 3: `risk/sizing.py`
`S50_MULTIPLIER`, `compute_position_size`, `volatility_scale_factor`.

### Step 4: `risk/limits.py`
`start_session`, `register_outcome`, `can_open`, `assert_no_average_down`,
`assert_stop_not_widened`.

### Step 5: `risk/killswitch.py`
`evaluate_kill_switch`.

### Step 6: `risk/ladder.py`
`max_contracts_for_stage`.

### Step 7: `risk/decision.py`
`evaluate_entry` orchestrator.

### Step 8: `risk/__init__.py`
Public re-exports.

### Step 9: `Settings` + `.env.example`
`RiskConfig` fields + `risk_config()`; document every var in `.env.example`.

### Step 10: tests + cov gate
`tests/unit/risk/` mirroring source; add `risk/` to `pyproject.toml` cov set.

### Step 11: docs / knowledge / playbook / memory
ROADMAP, CLAUDE.md, risk-engine.md, kill-switch playbook, memory pointer.

---

## File Changes

| File | Action | Description |
|---|---|---|
| `docs/plans/phase-7-risk-engine.md` | CREATE | This plan |
| `src/tfex_s50_multi_tf_swing/risk/__init__.py` | CREATE | Public re-exports |
| `src/tfex_s50_multi_tf_swing/risk/errors.py` | CREATE | Exception hierarchy |
| `src/tfex_s50_multi_tf_swing/risk/models.py` | CREATE | Pydantic I/O models + `RiskConfig` |
| `src/tfex_s50_multi_tf_swing/risk/sizing.py` | CREATE | `S50_MULTIPLIER`, sizing + vol scaling |
| `src/tfex_s50_multi_tf_swing/risk/limits.py` | CREATE | Session reducer + no-avg-down / no-widen |
| `src/tfex_s50_multi_tf_swing/risk/killswitch.py` | CREATE | Kill-switch evaluation |
| `src/tfex_s50_multi_tf_swing/risk/ladder.py` | CREATE | Capital-deployment guard |
| `src/tfex_s50_multi_tf_swing/risk/decision.py` | CREATE | `evaluate_entry` orchestrator |
| `src/tfex_s50_multi_tf_swing/config/settings.py` | MODIFY | `RiskConfig` fields + `risk_config()` |
| `.env.example` | MODIFY | Phase 7 risk vars |
| `pyproject.toml` | MODIFY | Add `risk/` to cov set |
| `tests/unit/risk/*` | CREATE | Full test suite |
| `docs/plans/ROADMAP.md` | MODIFY | Tick §7.1–§7.5, Current Status → Phase 8 |
| `CLAUDE.md` | MODIFY | Phase 7 risk-layer subsection + coverage note |
| `.claude/knowledge/risk-engine.md` | MODIFY | Implementation notes |
| `.claude/playbooks/risk-kill-switch-and-ladder.md` | CREATE | Operational runbook |

---

## Success Criteria

- [x] `compute_position_size(100k equity, 1 % risk, 5-pt stop)` ⇒ exactly **1 contract**.
- [x] Wider stop shrinks size; sub-1-contract result ⇒ **0 contracts** (no rounding up).
- [x] Zero/negative equity and zero/negative stop distance ⇒ `RiskInputError` (no divide-by-zero).
- [x] Daily `−2R` and 3-consecutive-loss limits halt at the boundary; trade-count cap enforced.
- [x] No-averaging-down + no-widen-stop raise `RiskLimitError`.
- [x] Panic regime ⇒ vol scale factor 0 (no trade); high percentile ⇒ halved.
- [x] **Kill-switch fault-injection test** proves flatten + halt on each trigger.
- [x] Capital ladder caps contracts per stage; no scaling without evidence.
- [x] `Settings().risk_config()` with no env reproduces documented defaults.
- [x] `risk/` ≥ 90 % coverage, in the enforced set; `uv run mypy src tests` clean; full gate green.

---

## Completion Notes

_(Filled in at the end of the session — see the final section.)_
