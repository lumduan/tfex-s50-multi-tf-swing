# TFEX S50 1H Timeframe Migration — Trend-Only Ultra-Low-Risk Setup

## Context

The TFEX S50 swing trading system (`strategies/tfex-s50-multi-tf-swing`) currently
operates on a **4H → 1H → 5m** timeframe hierarchy: 4H for regime/bias, 1H for setup
detection, and 5m for execution. Post-Phase-8 walk-forward analysis (14-month window)
exposed a 31.13R drawdown driven primarily by Strategy C (high-turnover sweep reversal)
and entries in unfavourable regimes.

Several risk mitigations were already applied (post-Phase-8): Strategy B is the sole
default active strategy, the entry regime gate defaults to `trend_up` only, `k_atr_stop`
is widened to 2.0, and `risk_per_trade_pct` is tightened to 0.5%. However, the 5m
execution timeframe still generates excessive turnover that erodes returns under high
retail commission costs.

This migration shifts execution from 5m to 1H, moves regime/bias detection from 4H/1H to
Daily (1d), hardens the trend-only gate, and implements a realistic 80 THB/side retail
commission model — producing an ultra-low-risk, low-turnover configuration suitable for
retail traders.

## Original Prompt

> Act as an expert Quantitative Developer. We are moving our TFEX (S501!) swing trading
> system from a 5-minute timeframe to a 1-Hour execution timeframe to reduce
> over-trading and mitigate high retail commission costs.
>
> 1. **Timeframe Realignment:**
>    - Change the core Execution Timeframe from 5m to 1H (`frames["1h"]`).
>    - Update the High-Timeframe (HTF) Filter to use Daily bars (`frames["1d"]`)
>      instead of 4H for trend and regime detection.
> 2. **Strict Regime Gating & Strategy Selection:**
>    - Enable Strategy B (ORB/Breakout modified for 1H) as the core strategy.
>    - Disable Strategy C (Sweep) completely.
>    - Implement a hard gate: Allow trade execution ONLY when the Daily (1d)
>      Market Regime is 'trend_up'. Block all entries during 'range_high_vol'
>      and 'trend_down'.
> 3. **Execution Parameters & Risk Setup:**
>    - Set the default `k_atr_stop` multiplier to 2.0 to widen stops and avoid
>      intraday noise.
>    - Keep risk per trade capped strictly at 0.5% of total equity, letting the
>      position sizing engine dynamically scale down contract sizes based on the
>      wider 1H ATR.
> 4. **Implement Realistic Cost Model (Retail Commission):**
>    - Inject an explicit commission fee into the Cost Model: Set it to a fixed
>      80 THB per contract per side (160 THB round-trip per contract), including
>      VAT/fees.
>    - Ensure the backtest metrics (Expectancy, NAV, Drawdown) deduct this cost
>      from every executed trade.

## Scope

### In Scope

| Item | Description |
|------|-------------|
| Timeframe type system | Add `"1d"` to `Timeframe` Literal, `TIMEFRAMES` tuple, `TIMEFRAME_MINUTES` dict; keep `"5m"` and `"4h"` for backward compat |
| Data fetchers | Add `"1d"` mapping to engine fetcher (`_TF_TO_ENGINE`) and mirror fetcher (`_TF_INTERVAL`) |
| Signal input pipeline | Rewire from `5m(base) + 1h(HTF) + optional 4h(HTF)` to `1h(base) + 1d(HTF)`; rename columns (`4h_bias_direction` → `1d_bias_direction`, `1h_regime` → `1d_regime`); drop `1h_*` prefixed feature columns (now base) |
| Regime classifier | Runs on 1d bars instead of 1h (classifier code is timeframe-agnostic — no logic change) |
| Bias engine | Runs on 1d bars instead of 4h (classifier code is timeframe-agnostic — no logic change) |
| Strategy B (ORB) | Adapt for 1H execution: `or_window` default 15→60, column refs updated |
| Strategy A | Update column refs to compile (disabled by default, untested in new regime) |
| Strategy C | Remove from active registry in `gate.py` (already disabled by default; now permanently out) |
| Regime gate | `apply_regime_gate` now gates on `1d_regime` instead of `1h_regime` (default `trend_up` only — unchanged) |
| Config defaults | `or_window` 15→60, `swing_window` 12→4, `time_stop_bars` 24→8, `commission_per_contract` 85→160 |
| Cost model | Commission default 85→160 THB round-trip (80/side); flows through all metrics |
| Backtest data source | `load_continuous_frames` loads `["1h", "1d"]` instead of `["5m", "1h"] + optional ["4h"]`; `build_execution_bars` takes 1h frame |
| Walk-forward harness | Drives 1H execution + 1D regime/bias; commission-laden metrics |
| Tests | Update all signal/backtest/execution/data tests for new timeframe wiring; add tests for 1D regime gate, commission=160, Strategy C disabled, 1H sizing |
| Notebooks | Re-run 01/02/04/08 with new timeframes |
| Docs | Update `CLAUDE.md`, knowledge notes, roadmap |
| Scripts | Update `run_walk_forward.py`, `build_features.py` |

### Out of Scope

| Item | Reason |
|------|--------|
| Deleting 5m/4h code paths | Kept for backward compat; unreachable via defaults |
| Adding 4h engine route | Engine-side change; D10 forbids local rollup |
| OHLCV source default flip (`mirror` → `engine`) | Phase 5.x verification; not this migration |
| Strategy A full 1H validation | Disabled by default; column refs compile but logic untested |
| Live/paper trading wiring | Phase 9; not this migration |
| Gateway contract changes | `extended_data` unchanged |

## Design Decisions

### D1: Keep 5m/4h types but remove from active paths

The `Timeframe` Literal retains `"5m"` and `"4h"` so existing data/Parquet stores
remain loadable. No code path reachable via defaults uses 5m or 4h for signal generation.
The old `_build_h4()` function is removed from `inputs.py` (1d replaces it), and
`load_continuous_frames` defaults to `["1h", "1d"]`.

### D2: Regime and bias both run on 1d

The regime classifier (`regime/rules.py`) and bias engine (`bias/htf.py`) are
timeframe-agnostic — they consume named columns from a feature panel and emit labels.
Moving both to 1d means the Daily bar determines market state (regime = trend_up/down/
range/panic) and directional bias (long/short/neutral). The classifier code itself
requires zero changes; only the caller in `inputs.py` changes which frame it feeds.

### D3: 1H becomes the base (unprefixed) timeframe

In the aligned frame, 1H features are unprefixed (`atr_ratio`, `dist_from_vwap`, etc.)
while 1D features get a `1d_` prefix via `align_timeframes`. This matches how 5m was
previously the base. The column constants change:
- `COL_BIAS = "1d_bias_direction"` (was `"4h_bias_direction"`)
- `COL_REGIME = "1d_regime"` (was `"1h_regime"`)
- Old `COL_H1_VWAP`, `COL_H1_STRUCT`, etc. are removed — those features are now base
  (unprefixed)

### D4: Strategy B ORB adapts to 1H via `or_window=60`

The ORB strategy reads `or_high_{or_window}` / `or_low_{or_window}` from the feature
pipeline. With `or_window=60` and the base timeframe at 1H, the opening range is the
first 1H bar's high/low. The strategy's gate logic (bias alignment, volume expansion,
lunch-zone suppression) is unchanged — only the column references change.

### D5: Strategy C permanently removed from registry

Strategy C's `_CLASSIFY` and `_TO_SIGNALS` entries are removed from `gate.py`. The
`strategy_c.py` module remains importable but no code path reaches it. The `StrategyId`
Literal keeps `"C"` for type compatibility and backward-compatible config parsing.

### D6: Commission 80/side = 160 round-trip

The current `commission_per_contract` field models the round-trip fee (both entry and
exit). The spec's 80 THB per contract per side equals 160 THB round-trip. The
`clearing_fee_per_contract` (1 THB) is additive, making the total 161 THB round-trip.
The `commission_points` formula `(commission + clearing) / S50_MULTIPLIER` is unchanged.

### D7: Engine source now fully supports all required timeframes

With the HTF moved from 4h to 1d, both required timeframes (1h, 1d) are served by the
engine. The `_TF_TO_ENGINE` mapping gets `"1d": "1d"` added. This removes the
engine-source degradation where A/B strategies emitted nothing (they required the
unavailable 4h bias). Strategy B now works on both `mirror` and `engine` sources.

## Implementation Steps

### Step 1: Core types (`data/models.py`)

- Add `"1d"` to `Timeframe = Literal["5m", "1h", "4h", "1d"]`
- Add `"1d"` to `TIMEFRAMES` tuple
- Add `"1d": 1440` to `TIMEFRAME_MINUTES` dict
- Update docstring

### Step 2: Data fetchers

**`data/engine_fetcher.py`:**
- Add `"1d": "1d"` to `_TF_TO_ENGINE` dict

**`data/fetcher.py`:**
- Add `"1d": "1440"` to `_TF_INTERVAL` dict

### Step 3: Signal input pipeline (`signals/inputs.py`) — the central change

Rewrite `build_signal_inputs` and its helpers:

- **Required frames:** `"1h"` and `"1d"` (was `"5m"` and `"1h"`)
- **Column constants:**
  - `COL_BIAS = "1d_bias_direction"` (was `"4h_bias_direction"`)
  - `COL_REGIME = "1d_regime"` (was `"1h_regime"`)
  - Remove `COL_H1_VWAP`, `COL_H1_STRUCT`, `COL_H1_ATR_RATIO`, `COL_H1_VOL_EXP`
- **`_build_base()`:** Now builds on 1H frame — feature panel + raw prices + swing levels
- **Remove `_build_h1()`:** 1H is now base, not a higher TF
- **Remove `_build_h4()`:** Replaced by `_build_d1()`
- **New `_build_d1()`:** Builds 1D feature panel + regime classification + bias classification
- **`build_signal_inputs()`:** Requires `"1h"` and `"1d"`; aligns 1d onto 1h grid; fills missing `1d_bias_direction` with `"neutral"` when absent (safe degrade)

### Step 4: Feature layer

**`features/models.py`:**
- Verify `INTRADAY_TIMEFRAMES` includes `"1h"` (already does — `("5m", "1h")`)
- Verify `opening_range_minutes` includes 60 (needed for `or_high_60` / `or_low_60`)

**`features/pipeline.py`:**
- Update `build_aligned()` default `base_timeframe` from `"5m"` to `"1h"`

### Step 5: Regime layer (no logic changes)

**`regime/rules.py`:**
- Update module docstring: regime now runs on 1d bars

### Step 6: Bias layer (no logic changes)

**`bias/htf.py`:**
- Update module docstring: bias now runs on 1d bars instead of 4h

### Step 7: Strategy modules

**`signals/strategy_b.py`:**
- Update docstring: ORB on 1H aligned frame (not 5m)
- All column refs use new `COL_BIAS`/`COL_REGIME` from `inputs.py` (already imported)
- No logic change — the gate expressions are timeframe-agnostic

**`signals/strategy_a.py`:**
- Update column refs: remove `h1_*` references, use base (unprefixed) columns
- Update `REQUIRED_COLUMNS` and gate expressions
- Note: disabled by default; compiles but untested in new regime

**`signals/strategy_c.py`:**
- Add docstring note: permanently disabled per 1H migration
- No code changes (module stays importable)

### Step 8: Gate and models

**`signals/gate.py`:**
- Remove `"C"` entries from `_CLASSIFY` and `_TO_SIGNALS` dicts
- Update docstrings: regime gate now on `1d_regime`
- `apply_regime_gate` uses `COL_REGIME` from `inputs.py` (already imported) — no code change

**`signals/models.py`:**
- `SignalConfig.or_window` default: `15` → `60`
- `SignalConfig.swing_window` default: `12` → `4`
- Update docstrings to reference 1H/1D instead of 5m/4H
- `SetupFeatures`: update docstrings; `h1_*` fields remain for backward compat but are deprecated

**`signals/base.py`:**
- No code changes needed — uses `COL_BIAS`/`COL_REGIME` from `inputs.py`

### Step 9: Execution layer

**`execution/models.py`:**
- `time_stop_bars` default: `24` → `8` (8×1H = 1 BKK session)
- Update docstring

### Step 10: Cost model

**`backtest/costs.py`:**
- `commission_per_contract` default: `Decimal("85")` → `Decimal("160")`
- Update docstring: "160 THB round-trip (80 THB/side)"

### Step 11: Backtest data source

**`backtest/data_source.py`:**
- `load_continuous_frames`: load `["1h", "1d"]` instead of `["5m", "1h"]`; drop `with_4h` param
- `build_execution_bars`: rename `frame_5m` param to `frame`; accept 1H bars; update docstring

### Step 12: Config

**`config/settings.py`:**
- `signal_or_window`: `15` → `60`
- `signal_swing_window`: `12` → `4`
- `execution_time_stop_bars`: `24` → `8`
- `cost_commission_per_contract`: `Decimal("85")` → `Decimal("160")`
- Update docstrings

### Step 13: Scripts

**`scripts/run_walk_forward.py`:**
- Remove `--with-4h` argument
- Call `load_continuous_frames(store)` (no `with_4h`)
- Pass `frames["1h"]` to `build_execution_bars` (was `frames["5m"]`)

**`scripts/build_features.py`:**
- Update `--base-timeframe` default from `"5m"` to `"1h"`

### Step 14: Tests

**`tests/unit/signals/conftest.py`:**
- Update `SCHEMA`: `4h_bias_direction` → `1d_bias_direction`, `1h_regime` → `1d_regime`, remove `1h_*` columns, `or_high_15` → `or_high_60`/`or_low_60`
- Update `_ATTR_TO_COL` mapping
- Update `LONG_BASE`, `SHORT_BASE`: remove `h1_*` keys, use base feature keys, update `or_high`/`or_low`

**`tests/unit/signals/test_inputs.py`:**
- Update frame builders to use 1h+1d (not 5m+1h+4h)
- Update column name assertions

**`tests/unit/signals/test_strategy_b.py`:**
- Update frame schema and column refs
- Test with `or_window=60`

**`tests/unit/signals/test_strategy_a.py`:**
- Update column refs to compile

**`tests/unit/signals/test_gate.py`:**
- Add test: Strategy C absent from `build_detect_map` output
- Verify `COL_REGIME` is `"1d_regime"` in gate

**`tests/unit/backtest/test_data_source.py`:**
- Update for 1h+1d loading

**`tests/unit/backtest/test_costs.py`:**
- Update expected commission to 160

**`tests/unit/backtest/test_walk_forward.py`:**
- Update frame/data refs

**`tests/unit/execution/test_engine.py`:**
- Generate test data at 1H intervals
- Update `time_stop_bars` expectations

**`tests/unit/data/test_engine_fetcher.py`:**
- Add test: `engine_timeframe("1d")` returns `"1d"`

### Step 15: Notebooks

Re-run with `uv run jupyter nbconvert --to notebook --execute --inplace`:
- `notebooks/01_data_quality.ipynb`
- `notebooks/02_feature_stability.ipynb`
- `notebooks/04_htf_bias.ipynb` (must reflect Daily HTF, not 4H)
- `notebooks/08_walk_forward.ipynb` (must reflect 1H execution + 160-THB commission)

### Step 16: Docs

- `CLAUDE.md`: Update timeframe hierarchy, config key defaults, commission model, system map
- `.claude/knowledge/strategy-design.md`: Update timeframe references
- Umbrella `.claude/knowledge/feature-tfex-integration.md`: Update status line
- `docs/plans/ROADMAP.md`: Add this migration as a completed phase/sub-phase

## File Changes Summary

| File | Change |
|------|--------|
| `src/.../data/models.py` | Add `"1d"` to `Timeframe`, `TIMEFRAMES`, `TIMEFRAME_MINUTES` |
| `src/.../data/engine_fetcher.py` | Add `"1d": "1d"` to `_TF_TO_ENGINE` |
| `src/.../data/fetcher.py` | Add `"1d": "1440"` to `_TF_INTERVAL` |
| `src/.../signals/inputs.py` | Rewire: 1h base + 1d HTF; rename columns; replace helpers |
| `src/.../signals/strategy_b.py` | Update docstring, column refs compile with new names |
| `src/.../signals/strategy_a.py` | Update column refs to compile; `h1_*` → base names |
| `src/.../signals/strategy_c.py` | Docstring note: permanently disabled |
| `src/.../signals/gate.py` | Remove Strategy C from `_CLASSIFY`/`_TO_SIGNALS` |
| `src/.../signals/models.py` | Defaults: `or_window=60`, `swing_window=4`; docstrings |
| `src/.../features/pipeline.py` | Default `base_timeframe="1h"` |
| `src/.../features/models.py` | Verify `opening_range_minutes` includes 60 |
| `src/.../regime/rules.py` | Docstring: regime on 1d |
| `src/.../bias/htf.py` | Docstring: bias on 1d |
| `src/.../execution/models.py` | Default `time_stop_bars=8` |
| `src/.../backtest/costs.py` | Default `commission_per_contract=160` |
| `src/.../backtest/data_source.py` | Load `["1h", "1d"]`; `build_execution_bars` takes 1h |
| `src/.../config/settings.py` | Defaults: `or_window=60`, `swing_window=4`, `time_stop_bars=8`, `commission=160` |
| `scripts/run_walk_forward.py` | Drop `--with-4h`; 1h execution bars |
| `scripts/build_features.py` | Default `base_timeframe="1h"` |
| `tests/unit/signals/conftest.py` | New schema, column map, baselines |
| `tests/unit/signals/test_*.py` | Updated frame builders, column assertions |
| `tests/unit/backtest/test_*.py` | Updated data source, costs, walk-forward tests |
| `tests/unit/execution/test_engine.py` | 1H test data intervals |
| `tests/unit/data/test_engine_fetcher.py` | `"1d"` mapping test |
| `notebooks/*.ipynb` | Re-run with new timeframes |
| `CLAUDE.md` | Updated hierarchy, config, commission |
| `.claude/knowledge/*.md` | Updated timeframe references |
| Umbrella `.claude/knowledge/feature-tfex-integration.md` | Status update |

## Acceptance Criteria

1. Execution TF is 1H (`frames["1h"]`); HTF trend/regime is Daily (`frames["1d"]`); no live path depends on 5m or 4h for entries
2. Strategy B is the active core strategy; Strategy C (Sweep) cannot emit entries
3. Entries occur only under Daily regime `trend_up`; `range_high_vol` and `trend_down` are hard-blocked (proven by tests)
4. `k_atr_stop` default is 2.0; risk-per-trade is capped at 0.5% equity and sizing scales contracts down with the wider 1H ATR
5. 80 THB/contract/side (160 round-trip) commission is deducted from every executed trade and reflected in Expectancy, NAV, and Drawdown in the backtest
6. `uv run ruff check`, `ruff format --check`, `mypy` (strict), and `pytest` all pass; `adapters/` + `risk/` coverage ≥90%
7. The four notebooks are updated and re-run to completion (or gaps documented)
8. The plan doc exists at `strategies/tfex-s50-multi-tf-swing/docs/plans/1h-timeframe-trend-only-migration.md`
9. Branch created, changes committed, PR opened, results reported in the box table

## Verification Commands

```bash
cd strategies/tfex-s50-multi-tf-swing
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest
uv run pytest --cov=src/tfex_s50_multi_tf_swing/adapters --cov=src/tfex_s50_multi_tf_swing/risk --cov-report=term-missing
uv run jupyter nbconvert --to notebook --execute --inplace notebooks/01_data_quality.ipynb
uv run jupyter nbconvert --to notebook --execute --inplace notebooks/02_feature_stability.ipynb
uv run jupyter nbconvert --to notebook --execute --inplace notebooks/04_htf_bias.ipynb
uv run jupyter nbconvert --to notebook --execute --inplace notebooks/08_walk_forward.ipynb
```

## Assumptions

- The feature pipeline's `opening_range_minutes` list includes 60 (verified if not, added)
- `lunch_zone_flag` works correctly on 1H bars (it's already computed for intraday TFs)
- The existing ParquetStore has or can generate 1d continuous data
- Strategy A column refs are updated to compile but the strategy is not validated in the new regime (disabled by default)
- The `"5m"` and `"4h"` Literal values remain in the type system for backward compat with Parquet stores
