# ML Probability Filter

ML is a **filter**, **ranking** layer, and **probability engine** — never a strategy.
The model gates rule-based signals; it does not invent trades.

## What the model predicts

| Target | Use |
| --- | --- |
| `P(trend_continuation)` | Gate Strategies A and B |
| `P(fake_breakout)` | Gate Strategy C |
| `P(volatility_expansion)` | Optional sizing input |

## What the model does NOT predict

- Next candle direction
- Exact price target
- "When the market will crash"

These framings are seductive and useless. Stay with probabilities over discrete
setups.

## Model family

LightGBM / XGBoost / CatBoost. **No Deep Learning at this stage.** Reasons:

- TFEX data volume is small.
- Markets are non-stationary; DL overfits faster than it generalises.
- Trees are interpretable; importance audits catch leakage early.

## Training discipline

- **Walk-forward only**: train on `[t0, t1]`, evaluate on `[t1, t2]`; advance window.
- Re-fit per window (e.g., quarterly).
- Out-of-sample metrics required to ship — no in-sample bragging.
- Feature importance audited; no single feature may dominate.
- Triple-barrier labels (TP / SL / time) standardise the target.

## Thresholds

Each model has a documented decision threshold (e.g., enter if
`P(trend_continuation) > 0.55`). Thresholds are themselves walked forward — tuning
on the full dataset is leakage.

## A/B integration

Every model release is A/B compared against the unfiltered ruleset on a held-out
window. Ship the filter only if it improves out-of-sample expectancy or profit factor
without making any regime worse.

## What NOT to do

- Never random-split a time series.
- Never train on the full dataset before walk-forward validation.
- Never let a model with no economic story ship — the model must align with a
  documented hypothesis (trend continuation, mean reversion, regime persistence).
- Never replace the rule-based strategy with the model. The model is a gate.
