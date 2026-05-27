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
