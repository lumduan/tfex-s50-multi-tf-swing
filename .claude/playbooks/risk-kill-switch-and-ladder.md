# Playbook — risk engine: kill switch & capital-deployment ladder

Operational runbook for the Phase-7 risk engine (`src/tfex_s50_multi_tf_swing/risk/`). Covers the
kill switch (flatten + halt) and the capital-deployment ladder (how to step size up). See
`.claude/knowledge/risk-engine.md` (spec + implementation notes) and
`docs/plans/phase-7-risk-engine.md`.

> **Risk Engine > any signal.** Every guard below is allowed to block a "good" setup. The system
> not trading is a feature, not a bug. Money quantities are `Decimal`; the S50 multiplier is the
> code constant `S50_MULTIPLIER = 200`, never an env var.

## 0. Golden rules

- **Kill switch overrides everything** (hard rule #8). When engaged: flatten all positions, halt new
  entries — no exceptions, no "this time is different".
- **No averaging down** (hard rule #4) and **never widen a stop after entry** — both raise
  `RiskLimitError`; they are bugs to surface, not conditions to swallow.
- **Scale only on statistical evidence, never on confidence.** A great month is not evidence.

## 1. Configure risk (env)

All knobs are `TFEX_S50_MULTI_TF_SWING_RISK_*` (see `.env.example`); an unset env reproduces the
documented defaults. Build the config in code via `Settings().risk_config() -> RiskConfig`.

Key vars:

- `RISK_PER_TRADE_PCT` (default `0.01`) — fraction of equity risked per trade.
- `RISK_DAILY_LOSS_LIMIT_R` (`2.0`), `RISK_MAX_CONSECUTIVE_LOSSES` (`3`),
  `RISK_MAX_TRADES_PER_DAY` (`6`) — the session halt limits.
- `RISK_HIGH_VOL_PERCENTILE` (`0.70`) / `RISK_HIGH_VOL_SIZE_FACTOR` (`0.5`) / `RISK_PANIC_NO_TRADE`
  (`true`) — volatility scaling.
- `RISK_KILL_SWITCH_ENGAGED` (`false`), `RISK_SPREAD_ANOMALY_MULT` (`5.0`),
  `RISK_LATENCY_BUDGET_MS` (`500`), `RISK_MAX_ERROR_RATE` (`0.10`) — kill-switch override + budgets.
- `RISK_DEPLOYMENT_STAGE` (`paper`) + the per-stage contract caps + `*_MIN_MONTHS_LIVE` — the ladder.

## 2. The kill switch

`risk.killswitch.evaluate_kill_switch(health, session_state, config) -> KillSwitchState` is a pure
function. It engages (and sets `flatten_positions = halt_entries = True`) on **any** of:

| Trigger | Condition |
|---|---|
| `manual` | `RISK_KILL_SWITCH_ENGAGED=true` (the only override today) |
| `spread_anomaly` | `spread > spread_anomaly_mult × median_spread` (needs a non-zero median) |
| `latency_breach` | `latency_ms > latency_budget_ms` |
| `broker_disconnect` | broker not connected **or** `error_rate > max_error_rate` |
| `market_halt` | exchange halt / circuit breaker |
| `daily_loss_limit` | session cumulative R ≤ `-daily_loss_limit_r` |

### Engage the manual kill switch (incident)

1. Set `TFEX_S50_MULTI_TF_SWING_RISK_KILL_SWITCH_ENGAGED=true` and reload settings
   (`get_settings.cache_clear()` in-process, or restart the owner process).
2. The next `decision.evaluate_entry` returns `allow_entry=False, contracts=0` with
   `kill_switch.flatten_positions=True` — the live layer (Phase 9/10) acts on that directive.
3. **Admin endpoint:** not available yet — it is deferred until the `api/` package lands. The env
   flag is the only manual override in Phase 7. `KillSwitchState` is the typed contract the future
   endpoint / live loop will consume.

### Disengage

Set the flag back to `false`, reload, and confirm `evaluate_kill_switch(...).engaged is False` on
clean `MarketHealth` before resuming.

## 3. The capital-deployment ladder

`risk.ladder.max_contracts_for_stage(stage, evidence, config) -> int` caps size by stage and never
grants more than the `LadderEvidence` supports:

| Stage | Cap | Required evidence |
|---|---|---|
| `paper` | 0 | none — validate logic only |
| `micro_live` | 1 | strategy passed the paper window (Phase 9) |
| `validated` | 2 | `months_live ≥ 6` + `expectancy_stable` + `drawdown_within_budget` |
| `scale` | 4 (careful step-up) | `months_live ≥ 12` + `expectancy_stable` + `drawdown_within_budget` |

A requested stage whose evidence is unmet is **capped down** to the highest qualifying rung (e.g.
`scale` with only validated-level evidence → 2). The evidence inputs are **data-gated** — they come
from Phase 9 (paper) / Phase 10 (live), not from confidence.

### Stepping up (the only sanctioned path)

1. Accumulate the live evidence (paper/live months, expectancy stability, drawdown vs budget).
2. Bump `RISK_DEPLOYMENT_STAGE` one rung (`paper → micro_live → validated → scale`) — never skip.
3. Confirm `max_contracts_for_stage(...)` returns the higher cap for your real `LadderEvidence`
   before trading it. If it caps down, the evidence is not there yet — stay put.

## 4. Verifying after a change

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest
```

The kill-switch fault-injection test (`tests/unit/risk/test_killswitch.py`) and the worked-example
sizing test (`tests/unit/risk/test_sizing.py`) are the Phase-7 exit criteria — they must stay green.
