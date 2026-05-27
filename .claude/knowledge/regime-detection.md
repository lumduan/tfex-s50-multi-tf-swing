# Regime Detection

Regime detection is the **single most important** component of this system. Choosing
the right strategy for the wrong regime destroys edge faster than any bad signal.

## Regime taxonomy

```python
REGIMES = [
    "trend_up",
    "trend_down",
    "range_low_vol",
    "range_high_vol",
    "panic",
]
```

## Regime → strategy / size policy

| Regime | Strategies allowed | Size policy |
| --- | --- | --- |
| `trend_up` | A (Pullback Continuation), B (Opening Range Breakout) — long only | full |
| `trend_down` | A, B — short only | full |
| `range_high_vol` | C (Liquidity Sweep Reversal) | full |
| `range_low_vol` | **none** — no trade | 0 |
| `panic` | none, or size halved if a clear setup appears | ≤ 50% |
| Lunch dead zone (12:00–14:00) | none — no trade | 0 |

This policy table is encoded in `src/tfex_s50_multi_tf_swing/regime/policy.py` and
unit-tested.

## Evolution path

Implement in this order — do not skip steps:

1. **Rule-based classifier** (baseline). Encodes the rules below in Python and serves
   as the supervision target for ML.
2. **Clustering exploration** (KMeans / GMM) on the regime feature vector to
   *verify* the rule labels capture the natural groupings. Optional, for confidence.
3. **LightGBM multi-class classifier**, trained on rule labels initially, then
   refined with hand-labelled regime windows where the rules look brittle.

**Do not jump straight to Deep Learning.** Tabular regime data is small,
non-stationary, and overfits trivially.

## Rule-based baseline (starting point)

| Regime | Rule sketch |
| --- | --- |
| `trend_up` | 4H `EMA20 > EMA50`, positive slope, HH/HL structure intact, price above session VWAP |
| `trend_down` | mirror of `trend_up` to the downside |
| `range_low_vol` | `rv_percentile < 30` **and** ATR-ratio < 1 (compression) **and** ADX < 20 |
| `range_high_vol` | `rv_percentile > 70` **and** no persistent trend (`trend_persistence` low) |
| `panic` | `rv_percentile > 95` **or** volume_expansion > 3σ **or** spread anomaly |

Refine the thresholds based on the labelled dataset built in Phase 3.

## Validation

- Agreement with hand-labelled regimes on a held-out year must be > 70%.
- Confusion matrix and transition-frequency heatmap saved per training run.
- Confirm `range_low_vol` and `lunch_zone` regimes meaningfully suppress signals.
