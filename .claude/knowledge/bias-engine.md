# HTF Bias Engine (Phase 4)

Design notes for `src/tfex_s50_multi_tf_swing/bias/` — the higher-timeframe (4H) bias filter
that gates every downstream setup. Companion to `regime-detection.md` and `strategy-design.md`.

## What it is

One **directional bias per 4H bar** — `long` / `short` / `neutral` — used to **veto**
counter-trend trades. **It only filters; it never generates trades** (a hard ROADMAP rule). It
is a pure offline library leaf: `features/ + regime/ → bias/`, importing nothing downstream
(`signals/`, `execution/`, `risk/`, `backtest/`, `api/`).

## Inputs (un-normalised, like `regime/`)

Reads the **un-normalised** Phase 2 panel (`FeatureConfig(normalise=False)`) — the normalised
panel z-scores `ema_slope_*` / `dist_from_vwap`, destroying the absolute signs the gates need.
`build_bias_inputs()` bridges from a continuous OHLCV frame by reusing
`regime.build_regime_inputs` + `regime.classify_frame`, so the volatility-healthy gate reads the
**same** regime label the Phase 3 layer produces — never re-derived. Required input columns:
`ema_fast_minus_slow`, `ema_slope_fast`, `structure`, `dist_from_vwap`, `regime`.

## Gates and composition (conservative unanimity)

A directional bias requires **every** gate to agree **and** a healthy regime. Any disagreement,
tie, null `structure`, or insufficient lookback → `neutral` (never a directional guess).

| Direction | All-of gates (4H) |
|---|---|
| `long`  | `ema_fast>ema_slow` ∧ `ema_slope_fast>slope_deadband` ∧ `structure∈{HH,HL}` ∧ `dist_from_vwap>vwap_deadband` ∧ `regime∉neutral_regimes` |
| `short` | `ema_fast<ema_slow` ∧ `ema_slope_fast<-slope_deadband` ∧ `structure∈{LH,LL}` ∧ `dist_from_vwap<-vwap_deadband` ∧ `regime∉neutral_regimes` |
| `neutral` | regime ∈ {`panic`, `range_low_vol`}; or any gate fails/ties; or `structure` null; or insufficient lookback |

`ema_fast`/`ema_slow` use `FeatureConfig.ema_spans` (default 20/50). `ema_slope_fast` is the
ATR-normalised fast-EMA slope (`ema_slope_{spans[0]}`). The "volatility-healthy gate" reuses the
two no-trade regimes from the Phase 3 policy table.

## Thresholds (config only, env-overridable)

`BiasConfig` (frozen Pydantic): `slope_deadband` (≥0, default 0.0), `vwap_deadband` (≥0, default
0.0), `neutral_regimes` (default `("panic", "range_low_vol")`). The deadbands are noise bands —
default 0.0 gives a strict sign test; raise them to suppress chop near zero. Surfaced on
`Settings` via `TFEX_S50_MULTI_TF_SWING_BIAS_SLOPE_DEADBAND` / `_BIAS_VWAP_DEADBAND` and
`Settings.bias_config()`. No threshold is hard-coded at a call site.

## Output contract — `BiasSignal`

Frozen Pydantic, exactly `direction: Literal["long","short","neutral"]` + `reasons: list[str]`.
`reasons` carries **one human-auditable string per gate** (e.g. `"ema_fast>ema_slow (long)"`,
`"structure HH/HL (long)"`, `"slope>0 (long)"`, `"price>vwap (long)"`, `"regime panic (veto)"`)
so a human can read exactly why a bar got its label. Per-bar `time` lives on the classified
*frame* column, not on the scalar signal.

Entry points (mirroring `regime/`): `classify_frame()` (vectorised — appends `bias_direction` +
`bias_reasons`), `classify_row()` (scalar from `BiasFeatures`), `to_signals()` (one
`BiasSignal` per bar). The frame and row paths produce identical direction + reason strings
(asserted by the test suite).

## The 4h-source caveat (the crux)

`bias/` consumes **`4h`** bars, but the canonical **`engine`** OHLCV source **declines** `4h`:
`data/engine_fetcher.py:engine_timeframe("4h")` raises `EngineTimeframeUnavailableError` before
any I/O (`_TF_TO_ENGINE = {"5m","1h"}`; D10 forbids a local rollup). So **`4h` is mirror-only**
today — read it from `data/continuous/4h.parquet` (the `mirror` source).

`bias/` itself is **source-agnostic**: it consumes already-loaded frames and never fetches
tvkit, owns no cookie, and picks no fetcher (that selection stays in `data/sources.py`). The
**unblocker** is an engine `4h` route → then a one-line change to `_TF_TO_ENGINE`; that engine
route is a `quant-marketdata-engine` change, out of scope for the strategy. See the OHLCV-source
section in `CLAUDE.md` and `docs/plans/ROADMAP.md` → Phase 4.

## §4.3 backtest — deferred, demonstrated

The ROADMAP §4.3 exit metric (≥ 30% counter-trend-entry reduction vs the *real* unfiltered
strategy) needs `signals/` + `execution/` + `backtest/`, which do not exist (Phases 5 / 8). It
is **deferred → blocked-on Phase 5**. `scripts/bias_counter_trend_demo.py` demonstrates the
*mechanism* on a naive 1-bar-momentum candidate proxy and writes a **public-safe** artifact
(counts only, no raw OHLCV) to `results/static/bias/`. Do not read the demo's % as the §4.3
exit figure — the magnitude claim awaits real signals.

## Gotchas

- `structure` (HH/HL/LH/LL) is frequently **null** on sparse-pivot synthetic series, so
  classifier tests build bias-input frames **per-branch directly** (one row per gate) rather
  than relying on the pipeline to emit a specific label (same approach as Phase 3).
- Null core inputs ⇒ `neutral`, never directional — trading is never enabled on undefined
  features.
- Bias features are `float`, not `Decimal` — internal statistical quantities that never cross
  the gateway boundary.
