# Strategy Design

Three strategies, one execution engine. Each strategy is gated by HTF bias and the
regime-to-strategy policy; signals are then filtered by the ML probability layer.

## Higher-timeframe bias engine (4H)

The bias engine **reduces bad trades**; it does not generate signals.

**Long bias** is set when *all* of:

- 4H `EMA20 > EMA50`, positive slope
- HH/HL structure intact (recent swing highs and lows are ascending)
- Price above HTF VWAP
- Volatility healthy: regime is not `panic` and not `range_low_vol`

**Short bias** is the mirror.

Bias output is a Pydantic `BiasSignal` with `direction` ∈ {`long`, `short`, `neutral`}
and a `reasons` list for auditability.

## Strategy A — Pullback Continuation ⭐ (primary)

**Pattern**: Impulse → Pullback → Compression → Continuation.

| Step | Timeframe | Condition |
| --- | --- | --- |
| 1 | 4H | Trend up: `EMA20 > EMA50`, positive slope, recent HH/HL |
| 2 | 1H | Pullback to EMA, structure intact, volume contracting, ATR contracting |
| 3 | 5m | Volatility compression detected, waiting for re-expansion |
| 4 | 5m | Entry: compression breakout + VWAP reclaim + volume expansion |

Visual flow:

```
4H uptrend
   ↓
1H pullback to EMA20
   ↓
5m squeeze (ATR compression)
   ↓
5m breakout high + volume expand
   ↓
Entry Long
```

Mirror logic applies for shorts.

## Strategy B — Opening Range Breakout

1. Compute opening range (first 15m / 30m / 60m — configurable).
2. Wait for a breakout candle with **volume expansion**.
3. Require HTF alignment (Strategy A's bias).
4. Skip during lunch dead zone (12:00–14:00).
5. Skip in `range_low_vol` regime.

## Strategy C — Liquidity Sweep Reversal

1. Detect a high/low sweep: price pierces a recent swing extreme and immediately
   reverses (stop-run pattern).
2. Wait for the confirmation candle and a structure shift.
3. Apply the ML `P(fake_breakout)` filter — high probability of fake breakout means
   the sweep is real and the reversal is tradeable.
4. Best in `range_high_vol`; tolerated in trend regimes only on counter-trend retests.

## Execution Engine (5m)

### Entry

- Breakout candle close
- Volume confirmation (volume z-score above threshold)
- Spread acceptable (skip if spread > k × median)

### Stop loss

`SL = entry − k · ATR` **anchored to structure**. The stop must be placed at a level
where "if hit, the idea is wrong" — not where noise kicks us out.

### Take profit (hybrid policy)

| Method | When |
| --- | --- |
| Fixed RR (1:2, 1:3) | Backtest baseline, stable, easy to test |
| Structure-based | Previous high, HTF resistance, opening-range extension |
| Volatility-based | `TP = entry + k · ATR` |
| Trailing | Trail behind EMA20 or last swing low/high |

**Recommended default**: Partial TP — close 50% at +1R, trail the remainder behind
structure.

### Trade management

- Move stop to breakeven on +1R, with a configurable buffer to avoid noise stop-outs.
- Time stop: exit if no progress within `N` bars.
- Never average down. Never widen a stop. A losing trade is a wrong idea.

## What NOT to do

- Do not stack many overlapping setups in the same direction at the same time —
  correlated risk.
- Do not trade outside the regime's allowed strategy set.
- Do not place stops at obvious round numbers — funds hunt those.

## Phase 5 implementation notes (2026-06-03)

The specifications above are realised by the `signals/`, `execution/`, and `backtest/` packages
(ROADMAP §5.1–§5.5). How the design maps to code:

- **One aligned 5m frame.** `signals/inputs.build_signal_inputs` reuses the Phase-2 causal aligner
  to put everything on the 5m grid: `1h_*` features + the **1H regime** (`1h_regime`, which gates
  the strategy whitelist via `regime.policy.regime_to_strategies`) and the per-4H
  **`4h_bias_direction`** (the HTF veto). Higher-TF columns are availability-shifted, so no setup
  reads an HTF bar before it closed.
- **Gate thresholds live in `SignalConfig`** (frozen, env-overridable via
  `TFEX_S50_MULTI_TF_SWING_SIGNAL_*`): A's pullback band + ATR/volume contraction caps + 5m
  compression ceilings; the shared `volume_expansion_min`; B's `or_window`; C's
  `require_structure_shift`; the `swing_window` for the causal swing-low/high stop anchor. No
  threshold is hard-coded at a call site.
- **A / B require the 4H bias; C does not.** C is gated on the 1H `range_high_vol` regime + a
  confirmed `liquidity_sweep_flag` + a VWAP-reclaim reversal (and an optional structure shift), so
  it runs on the `engine` OHLCV source where `4h` is unavailable. The ML `P(fake_breakout)` filter
  is a **Phase-6 hook**, not implemented.
- **Execution = `execution/engine.simulate_trade`:** next-bar-open fill, `k·ATR` stop clamped to
  the structure invalidation, partial-TP (50 %) + trailing remainder (or full TP at
  `partial_fraction = 1.0`), breakeven at +1R, time stop. PnL is in **points + R-multiples** only
  — the 200-THB/pt sizing (Phase 7 `risk/`) and the cost model (Phase 8) are out of scope.
- **Sizing-ready, not sized.** A `SetupSignal` carries direction + entry + structure stop; a
  `Trade` carries the R-multiple. These are exactly the inputs the Phase-7 risk engine consumes —
  Phase 5 stays ROADMAP-pure (no `risk/`, no gateway `extended_data` change, no endpoint).
- **Per-strategy backtest** (`backtest/`) reports expectancy / profit factor / max-DD / win-rate /
  regime-stratified PnL independently per strategy. The positive-expectancy *magnitude* claim is
  deferred → data-gated on the 5-year backfill + a cost model.
