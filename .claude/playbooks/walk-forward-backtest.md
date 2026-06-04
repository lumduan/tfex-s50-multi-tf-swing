# Playbook — running the walk-forward backtest (Phase 8)

How to run the anchored walk-forward harness, where its inputs come from, and where the
public-safe artifact lands. See `.claude/knowledge/backtest-protocol.md` and
`docs/plans/phase-8-walk-forward-backtest.md`.

> **Data-gated.** The exit-criteria *magnitudes* (positive expectancy after costs, drawdown within
> budget, regime stability) need the 5-year TFEX backfill + engine TFEX data. Until then the harness
> runs on whatever continuous snapshot the local store holds and the numbers are a *machinery
> demonstration*, not a magnitude claim. Never fake a backtest.

## 0. Golden rules

- **Anchored walk-forward only**, never a random / k-fold split (hard rule #6). Windows are
  deterministic; `train_end ≤ test_start` always.
- **OHLCV comes from the Market Data Engine / its offline Parquet snapshot — never tvkit** (tfex
  holds no cookie). The loader raises `WalkForwardDataError` if the snapshot is missing/empty.
- Execution uses the **raw per-contract** series; signals the back-adjusted continuous (hard rule #3).
- Money is `Decimal` via the single `risk.sizing.S50_MULTIPLIER`; ratios stay float.
- Artifacts under `results/static/backtest/` are **public-safe** — counts / metrics / ratios / NAV
  index only, never raw OHLCV or the equity-curve array.

## 1. Prerequisite — a local continuous snapshot

The harness reads `continuous/{5m,1h}.parquet` from `ParquetStore(settings.data_dir)`. Refresh it
from the engine source (never tvkit) first:

```bash
# engine source (preferred; no tvkit cookie). Requires the engine base URL.
export TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE=engine
export TFEX_S50_MULTI_TF_SWING_MARKET_DATA_ENGINE_BASE_URL=http://localhost:8080/api/v2/engines/market-data
uv run python scripts/refresh_ohlcv.py --contract <...> --timeframe 5m --timeframe 1h --start <d> --end <d>
```

`4h` is engine-declined (`EngineTimeframeUnavailableError`); A/B then degrade to `neutral` bias and
emit nothing, while C still runs. `--with-4h` only works on the `mirror` source.

## 2. Run the demonstration

```bash
uv run python scripts/run_walk_forward.py
# or, with the mirror 4H frame and a custom output dir:
uv run python scripts/run_walk_forward.py --with-4h --out-dir results/static/backtest
```

Writes `results/static/backtest/walk_forward.json` (combined + per-strategy results, per-window
summaries, NAV index). The script runs the backtest at a **scaled** deployment stage with full
ladder evidence — the capital ladder caps the `paper` stage to **0 contracts**, so `paper` takes no
trades; this only affects historical sizing, never live deployment (which stays env-gated).

## 3. Config knobs (`pydantic-settings`, prefix `TFEX_S50_MULTI_TF_SWING_`)

- `WALK_FORWARD_MODE` = `anchored` (default) | `rolling`; `WALK_FORWARD_TRAIN_SPAN_DAYS` /
  `_TEST_SPAN_DAYS` / `_STEP_DAYS`; `WALK_FORWARD_START_EQUITY`; `WALK_FORWARD_SEED`;
  `WALK_FORWARD_REFIT_ML`.
- `COST_COMMISSION_PER_CONTRACT` / `_CLEARING_FEE_PER_CONTRACT` (Decimal THB, round-trip),
  `COST_SLIPPAGE_ATR_MULT`, `COST_ILLIQUID_SESSION_MULT`, `COST_TICK_SIZE`, `COST_SPREAD_TICKS`.

An unset env reproduces the documented defaults.

## 4. The notebook (visual report)

`notebooks/08_walk_forward.ipynb` — per-window NAV curve (indexed to 100, vs S50 buy-and-hold),
drawdown + regime overlay, per-strategy + combined tables, and a sensitivity sweep on the ATR-stop
multiplier (and ML thresholds when enabled). Outputs stay in the notebook (not committed as raw data).

## 5. Per-window ML re-fit

`run_walk_forward(..., ml_filter_factory=...)` accepts an injectable factory called per window per
strategy with the **train** slice. The default `None` reproduces Phase-5 behaviour byte-for-byte
(respecting the default-OFF ML gate). The owner script binds a pre-loaded bundle when
`TFEX_S50_MULTI_TF_SWING_ML_FILTER_ENABLED=true`; true per-window training is data-gated.
