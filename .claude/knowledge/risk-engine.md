# Risk Engine

Risk Engine is more important than any signal. A great signal with bad risk dies
within a year; an average signal with great risk survives a decade.

## Position sizing

```
position_size = account_risk / (stop_distance × multiplier)
```

- S50 multiplier: **200 THB per index point**
- Default `account_risk = 1%` of equity
- Stops widen ⇒ position size shrinks (volatility-scaled by construction)

**Worked example** (verbatim from the design notes):

- Equity: 100,000 THB
- Risk: 1% → 1,000 THB at risk
- Stop distance: 5 index points
- Multiplier: 200 THB / point

```
position_size = 1000 / (5 × 200) = 1 contract
```

If the stop is wider, position size must shrink proportionally.

## Hard stops

| Rule | Behaviour |
| --- | --- |
| Daily loss limit | `−2R` cumulative → stop trading for the day |
| Consecutive loss limit | 3 losses in a row → pause until next session |
| Daily trade-count cap | Configurable — prevents tilt |

## Volatility scaling

- When realised vol breaches the high percentile, halve size.
- When realised vol exceeds an extreme percentile (panic regime), do not trade.
- When the spread is abnormally wide, do not enter.

## Kill switch

Any one of these triggers immediately flattens positions and halts new entries:

- Spread anomaly (e.g., > 5 × median)
- Latency spike beyond budget
- Broker disconnect / API error spike
- Market halt / circuit breaker
- Daily loss limit hit
- Manual override (admin endpoint or env flag)

## Capital deployment ladder

| Phase | Size | Required condition |
| --- | --- | --- |
| Paper | 0 contracts | Validate logic only |
| Micro Live | 1 contract | Strategy passed full paper window (Phase 9) |
| Validated | 2 contracts | Statistical evidence: ≥ 6 months live with stable expectancy |
| Scale | Step up carefully | 6+ months stable in production, drawdown within budget |

**Scale only on statistical evidence, never on confidence.** "I feel good about
this trade" is not evidence — drawdowns are won by humility.

## What NOT to do

- Never average down on losers.
- Never widen a stop after entry.
- Never skip the kill-switch check because "this time is different."
- Never scale up immediately after a great month — that is when overfitting becomes
  obvious.

## Implementation notes (Phase 7, shipped 2026-06-04)

The spec above is authoritative; this records how it was realised in
`src/tfex_s50_multi_tf_swing/risk/` (plan: `docs/plans/phase-7-risk-engine.md`).

- **Leaf package, pure functions.** One-way dependency `signals/ + execution/ + regime/ → risk/`;
  it imports nothing downstream. Modules: `errors`, `models`, `sizing`, `limits`, `killswitch`,
  `ladder`, `decision`. No FastAPI endpoint, no `live/` wiring, no walk-forward — ROADMAP-pure like
  Phases 3–6.
- **`S50_MULTIPLIER = Decimal("200")`** is the single named constant (`risk/sizing.py`). Money is
  `Decimal` end-to-end; `risk_per_trade_pct` is a float ratio converted via `Decimal(str(pct))`
  before multiplying equity, so sizing arithmetic stays exact. Sizing floors with `ROUND_DOWN`; a
  sub-1 result is 0 (no trade).
- **Volatility scaling reuses `regime.policy.regime_to_size_multiplier`** (never re-derives the
  regime). Final factor = `min(regime_cap, percentile_cap)`. **Panic ⇒ 0** when `panic_no_trade`
  (default True) — deliberately stricter than the regime policy's ≤ 50 %; flip the config for a
  validated reduced-size-in-panic policy later.
- **Session limits are an immutable reducer** (`register_outcome` → new `SessionRiskState`). The
  `halted` flag latches; `register_outcome` raises `RiskInputError` if the outcome's `session_date`
  disagrees with the state (start a fresh session per day). `assert_no_average_down` /
  `assert_stop_not_widened` raise `RiskLimitError`.
- **Kill switch is checked first** in `decision.evaluate_entry` (hard rule #8). The daily-loss
  trigger fires on cumulative R directly (not the softer streak / trade-count halts). Manual
  override is the env flag `TFEX_S50_MULTI_TF_SWING_RISK_KILL_SWITCH_ENGAGED`; the **admin endpoint
  is deferred** to the `api/` package. `KillSwitchState` is the typed flatten/halt contract.
- **Capital ladder** (`max_contracts_for_stage`) caps down to the highest rung the evidence
  supports. The "≥ 6 months live" evidence is **data-gated** (Phase 9/10) — the guard encodes the
  rule, the `LadderEvidence` inputs arrive later.
- **Config:** `RiskConfig` (frozen, bounded) on `Settings` via `TFEX_S50_MULTI_TF_SWING_RISK_*` +
  `risk_config()`; unset env reproduces these defaults. 100 % coverage on `risk/`, mypy strict.
- **Exit-criterion tests:** the worked-example sizing test (⇒ exactly 1 contract) and the
  kill-switch fault-injection test (each trigger flattens + halts) live in `tests/unit/risk/`.
