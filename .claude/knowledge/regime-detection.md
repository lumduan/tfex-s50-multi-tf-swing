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

## Implementation status (2026-05-29)

**Step 1 (rule baseline) and the §3.4 policy table are implemented** in
`src/tfex_s50_multi_tf_swing/regime/`. Steps 2 (clustering) and 3 (LightGBM) are deferred
until a hand-labelled regime dataset exists.

### Input contract

The classifier reads the **un-normalised** Phase 2 feature panel
(`build_panel(df, tf, FeatureConfig(normalise=False))`). The normalised panel z-scores
`ema_slope_*` / `dist_from_vwap` against a trailing window, which destroys the absolute
signs the rules rely on. `build_regime_inputs()` produces the raw input columns:
`ema_fast_minus_slow` (derived from `close` via `indicators.ema`, since EMA *levels* are
not panel columns), `ema_slope_fast`, `structure`, `dist_from_vwap`, `rv_percentile`,
`trend_persistence`, `volume_expansion`, `range_compression`.

### Finalised default thresholds (`RegimeThresholds`)

| Threshold | Default | Rule |
| --- | --- | --- |
| `panic_rv` | 0.95 | `panic` when `rv_percentile` exceeds it |
| `panic_volume_z` | 3.0 | `panic` when `volume_expansion` z-score exceeds it |
| `range_low_rv` | 0.30 | `range_low_vol` lower bound (with `range_compression == 1`) |
| `range_high_rv` | 0.70 | `range_high_vol` upper band reference |
| `trend_persist_min` | 0.30 | min `|trend_persistence|` to call a tape trending |

Overridable via `TFEX_S50_MULTI_TF_SWING_REGIME_*` / `Settings.regime_thresholds()`.

### Evaluation order & edge cases

`panic` is evaluated first (a blow-off dominates an otherwise-trending tape), then trend,
then `range_low_vol`, with `range_high_vol` as the residual. Rows with null core inputs
(insufficient lookback) are labelled `range_low_vol` — the no-trade bucket — so trading is
never enabled on undefined features. The lunch dead-zone is a no-trade *condition* layered
on top via `policy.is_no_trade(regime, lunch_zone=True)`, not a sixth regime.
