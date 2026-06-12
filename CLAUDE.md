# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this
repository.

## Project

`tfex-s50-multi-tf-swing` is a multi-timeframe swing-intraday quant trading system for
**SET50 Index Futures (S50) on TFEX**. It is a **headless Data Engine** following the
same pattern as `csm-set`: a FastAPI service on container port 8000 (host port 8200)
that POSTs daily reports to the umbrella **`quant-api-gateway`** under the standard
ingestion contract `POST /api/v1/ingest/daily-report`.

The system trades a single instrument (S50) using a strict multi-timeframe hierarchy:

- **1D** — regime detection and higher-timeframe bias (Daily bars; migrated from 4H, 2026-06-05).
- **1H** — main setup detection + execution (migrated from 5m, 2026-06-05).
- **5m / 4H** — retained in the type system for backward-compatible Parquet store reads;
  no active signal path references them.

Design philosophy: the system is **boring, conservative, and engineered to survive
across regimes** — not optimised for a beautiful backtest. Edge comes from regime
awareness + cost efficiency + risk management + execution quality.

**Active phase: 1H-execution migration (2026-06-05).** Execution TF is 1H;
HTF regime/bias runs on Daily bars. Strategy B (ORB, 1H) is the sole active core
strategy. Strategy C (Sweep) is permanently disabled. Strategy A (Pullback) is
disabled by default. Commission model: 160 THB round-trip (80 THB/side).

The repo follows the umbrella's two-mode pattern (controlled by
`TFEX_S50_MULTI_TF_SWING_PUBLIC_MODE`):

- **Public** (Docker default, `true`): read-only. Live trading and write endpoints
  return 403. Pre-computed results under `results/static/` only.
- **Private** (`false`): owner mode. Scheduler runs, data refresh / backtest / paper /
  live endpoints are live, and pipeline hooks mirror daily snapshots to the gateway
  when `TFEX_S50_MULTI_TF_SWING_DB_WRITE_ENABLED=true` plus the configured DSNs.

## Commands

Everything runs through `uv`. Never call `python` / `pip` / `poetry` / `conda` directly.

```bash
uv sync --all-groups                                     # install deps (incl. dev)
uv run pytest tests/ -v                                  # full test suite
uv run pytest tests/unit/features/test_trend.py::test_x  # single test
uv run pytest --cov=src --cov-report=term-missing        # with coverage
uv run ruff check .                                      # lint
uv run ruff format --check .                             # format check
uv run mypy src tests                                    # strict type check
uv run uvicorn api.main:app --reload --port 8000         # API dev server (when api/ lands)
```

Combined quality gate (must pass before every push, matching CI):

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest
```

Owner pipeline (private mode — implemented progressively from Phase 1 onward):

```bash
uv run python scripts/refresh_ohlcv.py    # pull OHLCV (4H/1H/5m) → data/raw + continuous (Phase 1)
uv run python scripts/validate_ohlcv.py   # validate a stored snapshot (Phase 1)
uv run python scripts/build_features.py   # continuous → data/features/<tf> + aligned_5m (Phase 2)
uv run python scripts/refresh_daily.py    # end-of-day pipeline → gateway daily report (future)
uv run python scripts/run_paper.py        # paper-trading runner (Phase 9)
```

Docker:

```bash
docker compose up                                                        # public mode, host port 8200
docker compose -f docker-compose.yml -f docker-compose.private.yml up    # owner mode (writable volumes + broker creds)
```

## Architecture

### Layering (one-way dependency)

```
src/tfex_s50_multi_tf_swing/  →  api/
```

`src/tfex_s50_multi_tf_swing/` is the library core and must NEVER import from `api/`.
If a UI is added later, it follows the same one-way rule (`src/ → api/ → ui/`).
Tests mirror the source layout (`tests/unit/<subpkg>/` ↔ `src/tfex_s50_multi_tf_swing/<subpkg>/`).

### Five-layer system map

```
┌─────────────────────────────────────────────┐
│  Raw Market Data (multi-TF OHLCV)            │
│  1D → Regime / Macro Bias                    │
│  1H → Main Setup Detection + Execution       │
└─────────────────────┬───────────────────────┘
                      │
┌─────────────────────▼───────────────────────┐
│  Data Layer                                  │
│  - Continuous Futures Contract               │
│  - Feature Engineering                       │
│  - Validation Pipeline                       │
└─────────────────────┬───────────────────────┘
                      │
┌─────────────────────▼───────────────────────┐
│  Intelligence Layer                          │
│  - Regime Detection                          │
│  - Higher-TF Bias Engine                     │
│  - ML Probability Filter                     │
└─────────────────────┬───────────────────────┘
                      │
┌─────────────────────▼───────────────────────┐
│  Execution Layer                             │
│  - Setup Detection (Strategy B active; A/C disabled) │
│  - Execution Engine (1H)                     │
│  - Risk Engine                               │
└─────────────────────┬───────────────────────┘
                      │
┌─────────────────────▼───────────────────────┐
│  Validation & Deployment                     │
│  - Walk-Forward Backtest                     │
│  - Paper Trading                             │
│  - Live Trading                              │
└─────────────────────────────────────────────┘
```

### Data flow inside `src/tfex_s50_multi_tf_swing/`

```
data/    →  features/  →  regime/  →  bias/  →  signals/  →  execution/  →  risk/
                                                                              │
                                                                              ▼
                                                                       backtest/
                                                                              │
                                                                              ▼
                                                                       live/ (paper / broker)
                                                                              │
                                                                              ▼
                                                                       adapters/  →  gateway
```

`adapters/payload.py` builds the `POST /api/v1/ingest/daily-report` Pydantic payload;
`adapters/gateway_client.py` posts it idempotently to `quant-api-gateway` over the
shared `quant-network`.

### Storage

- **Parquet (PyArrow)** is the durable store for all tabular data under `data/`
  (gitignored) and `results/static/` (tracked, public-safe). Partition by date /
  contract where feasible.
- The Postgres dependency is opt-in via `TFEX_S50_MULTI_TF_SWING_DB_WRITE_ENABLED`.
  Phase 0 wired the gateway HTTP path via `adapters/`. Phase 1 added a direct
  Postgres mirror via `data/db_writer.py` (asyncpg), gated by the same flag plus
  `TFEX_S50_MULTI_TF_SWING_PG_DSN`.
- Postgres DBs when write-back is on:
  - `db_tfex_s50_multi_tf_swing`: `equity_curve` (TimescaleDB hypertable),
    `trade_history` (with `side`, `contracts`, `margin_used`), `backtest_log`,
    `benchmark_equity_curve` (S50 underlying / SET50 TR), plus the Phase 1
    `ohlcv_raw` / `ohlcv_continuous` hypertables (provisioned by
    `quant-infra-db` init-script 09).
  - `db_gateway`: written **only via HTTP** to `quant-api-gateway`. The strategy
    does not connect directly to `db_gateway`.

### Phase 1 — data layer

- **TradingView symbols** are pinned in `src/tfex_s50_multi_tf_swing/data/contracts.py`:
  - Per-contract: `TFEX:S50<H|M|U|Z><yyyy>` (e.g. `TFEX:S50H2026`).
  - Continuous reference: `TFEX:S501!` — TradingView's auto-roll. **Cross-check
    only**; the strategy builds its own back-adjusted continuous so the roll
    policy is explicit (`roll_offset_days`, default 5) and reproducible.
- **Back-adjustment ratio** = `far_close(t_roll) / near_close(t_roll)`. The
  `RollRecord` stored alongside continuous Parquet captures the ratio so a human
  can audit any subsequent re-roll.
- **TimescaleDB OHLCV tables** live ONLY in `db_tfex_s50_multi_tf_swing` (never
  `db_gateway`). The standard ingestion contract is unchanged in Phase 1.

### Phase 2 — feature layer

- `src/tfex_s50_multi_tf_swing/features/` consumes the back-adjusted continuous series
  and emits a panel keyed by `(time, timeframe)` to `data/features/<tf>.parquet`, plus a
  causally-aligned `data/features/aligned_5m.parquet`. One-way dependency: `data/ → features/`.
- **Features are Float64** (flags `Int8`, categoricals `Utf8`) — statistical quantities
  that never cross the gateway boundary, so the Decimal-for-money rule does not apply to
  them. Prices read from the store are cast Decimal→Float64 at the feature boundary.
- **Look-ahead-free by construction:** trailing-only windows (never `center`),
  confirmation lag shifted forward for swing pivots / liquidity sweeps, strictly-prior
  session references, trailing-window winsorise + z-score, and availability-shifted
  (`time + TIMEFRAME_MINUTES[tf]`) as-of joins in `features/align.py`. Bars are
  open-labelled (see `data/fetcher.py`).
- Vectorised session tagging in `features/time_of_day.py` mirrors `SessionCalendar`'s
  constants; an anti-drift test asserts row-by-row agreement.

### Market data source (`TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE`)

**Authoritative rule: tfex never fetches tvkit and never owns the TradingView cookie.** The
canonical OHLCV producer is the standalone **`quant-marketdata-engine`** (the sole
tvkit-cookie owner, container `quant-marketdata-engine:8000` / host `:8300`,
gateway-proxied at `/api/v2/engines/market-data/*`); tfex *reads* it. This is the engine
integration delivered by `feature-market-data-engine` **Phase 4 (shipped 2026-06-02)** —
distinct from this strategy's own Phase 4 (HTF Bias Engine).

The owner-side refresh acquires OHLCV through a small factory
(`data/sources.py:build_ohlcv_fetcher`) selected by `TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE`;
both branches return a `FetcherProtocol`, so `refresh_all` and everything downstream
(store → continuous → validator → db_writer) are source-agnostic:

- **`mirror`** (default): the unchanged Phase-1 path — `OhlcvFetcher` fetches tvkit and
  persists the local Parquet store + the 09 TimescaleDB mirror. Requires the tvkit cookie.
- **`engine`**: `EngineOhlcvFetcher` reads RAW per-dated-contract bars from the shared
  **Market Data Engine** (`quant-marketdata-engine`, host `:8300`) over HTTP via
  `adapters/market_data_engine_client.py`, **gateway-proxied** at
  `/api/v2/engines/market-data/*`. tfex holds **no tvkit cookie** on this path. Requires
  `..._MARKET_DATA_ENGINE_BASE_URL` (include the proxy prefix); `..._MARKET_DATA_ENGINE_API_KEY`
  is optional (only when the engine sets its own key). This is Phase 4 of
  `feature-market-data-engine`.

On the `engine` source:

- The engine is the **canonical** store; the 09 mirror
  (`db_tfex_s50_multi_tf_swing.ohlcv_raw` / `.ohlcv_continuous`) is demoted to a **derived
  local cache** materialised from engine-sourced bars — never a parallel ingest. The
  physical drop/migration of the 09 tables is a **separate `quant-infra-db` PR**, deferred
  until the engine source is the validated default.
- **Continuous is built locally.** tfex reads raw dated contracts (`/ohlcv?adjusted=false`)
  and back-adjusts via `data/continuous.py` (the series the strategy was validated on) —
  the engine's native back-adjusted `S501!` is unbuilt (Phase-5 adjustment-parity), so
  `fetch_continuous_reference` returns an empty frame and the cross-check is skipped.
- **4h is deferred.** The engine read API serves only `1d | 1h | 5m`; `4h` (a
  `cagg_ohlcv_4h` aggregate that is not yet routed) raises `EngineTimeframeUnavailableError`
  before any I/O — no local rollup (Decision D10). Enabling it later is a one-line change to
  `data/engine_fetcher.py:_TF_TO_ENGINE` once the engine exposes a 4h route.
- Default is unchanged behaviour; rollback = leave the flag unset / `mirror`. The default
  flip `mirror → engine` is **pending Phase 5.x** end-to-end verification (100% parity).

**See also:** the ROADMAP's authoritative
[Market data source](docs/plans/ROADMAP.md#market-data-source--the-market-data-engine)
section; the engine reference docs
[`../../quant-marketdata-engine/docs/README.md`](../../quant-marketdata-engine/docs/README.md);
and the umbrella reader-cutover knowledge
[`../../.claude/knowledge/feature-market-data-engine-reader-cutover.md`](../../.claude/knowledge/feature-market-data-engine-reader-cutover.md)
+ cutover runbook
[`../../.claude/playbooks/marketdata-engine-cutover.md`](../../.claude/playbooks/marketdata-engine-cutover.md).

### Phase 3 — regime layer

- `src/tfex_s50_multi_tf_swing/regime/` classifies every bar into one of five regimes
  (`trend_up`, `trend_down`, `range_low_vol`, `range_high_vol`, `panic`) and maps each to
  the strategies / position-size it permits (`policy.py`, ROADMAP §3.4). One-way dependency:
  `features/ → regime/`. Pure offline library code — no endpoint, no gateway write.
- It consumes the **un-normalised** feature panel
  (`build_panel(..., FeatureConfig(normalise=False))`): the normalised panel z-scores
  `ema_slope_*` / `dist_from_vwap`, which would destroy the absolute signs the rules need.
  `build_regime_inputs()` bridges from a continuous OHLCV frame; `classify_frame()` is the
  vectorised entry point and `classify_row()` the scalar one.
- **Thresholds live only in config**: `RegimeThresholds` (frozen Pydantic) with defaults
  from `.claude/knowledge/regime-detection.md`, overridable via
  `TFEX_S50_MULTI_TF_SWING_REGIME_*` and `Settings.regime_thresholds()`. No threshold is
  hard-coded at a call site.
- §3.2 (clustering notebook) and §3.3 (LightGBM) are deferred until a hand-labelled regime
  dataset exists; the rule baseline is their weak-supervision target.

### Phase 4 — HTF bias layer

> Note: this is the strategy's own Phase 4 (HTF Bias Engine) — **distinct** from the
> "Phase 4 — OHLCV source" section above, which is `feature-market-data-engine` Phase 4.

- `src/tfex_s50_multi_tf_swing/bias/` materialises **one directional bias per 4H bar**
  (`long` / `short` / `neutral`) used to **veto** counter-trend trades. It **only filters — it
  never generates trades.** One-way dependency: `features/ + regime/ → bias/`; it imports
  nothing downstream (`signals/`, `execution/`, `risk/`, `backtest/`, `api/`).
- Like `regime/`, it consumes the **un-normalised** feature panel
  (`FeatureConfig(normalise=False)`) — z-scored `ema_slope_*` / `dist_from_vwap` destroy the
  absolute signs the gates need. `build_bias_inputs()` bridges from a continuous OHLCV frame
  (reusing `regime.build_regime_inputs` + `regime.classify_frame`, so the volatility-healthy
  gate reads the *same* regime label, never re-derived); `classify_frame()` is the vectorised
  entry point (appends `bias_direction` + `bias_reasons`), `classify_row()` the scalar one, and
  `to_signals()` materialises one `BiasSignal` per bar.
- **Conservative unanimity:** a directional bias requires *every* gate to agree (EMA cross +
  slope + structure HH/HL·LH/LL + VWAP side) **and** a healthy regime (`panic` /
  `range_low_vol` veto to `neutral`). Any disagreement, tie EMA, null `structure`, or
  insufficient lookback → `neutral`. `BiasSignal` carries `direction` + one auditable `reasons`
  string per gate.
- **Deadbands live only in config**: `BiasConfig` (frozen Pydantic), overridable via
  `TFEX_S50_MULTI_TF_SWING_BIAS_*` and `Settings.bias_config()`. No threshold hard-coded.
- **`bias/` is source-agnostic.** It consumes already-loaded 4H frames and never fetches tvkit
  / picks a fetcher. **`4h` is mirror-only** today — the `engine` source declines it
  (`EngineTimeframeUnavailableError`, no local rollup; see the OHLCV-source section). §4.3
  (the ≥ 30% counter-trend-reduction backtest) is deferred to Phase 5 (a demonstration ships in
  `scripts/bias_counter_trend_demo.py`).

### Phase 5 — signal / execution / backtest layers

- `src/tfex_s50_multi_tf_swing/signals/` materialises **trade setups** for three strategies — A
  (pullback continuation), B (opening-range breakout), C (liquidity-sweep reversal). Each mirrors
  the bias/regime shape (`classify_frame` / `classify_row` / `to_signals`) and fires only on full
  gate agreement (never a guess). `signals/inputs.build_signal_inputs` resolves the multi-TF
  substrate onto the **5m grid** via the Phase-2 causal aligner: it widens 5m with `1h_*` features
  + the **1H regime** (`1h_regime`, gates which strategies may trade) and the per-4H
  **`4h_bias_direction`** (the HTF veto), every higher-TF column availability-shifted so nothing
  leaks. One-way dependency: `features/ + regime/ + bias/ → signals/`.
- `src/tfex_s50_multi_tf_swing/execution/` simulates a trade from a `SetupSignal`: **next-bar-open
  fill** (no same-bar look-ahead), a `k·ATR` stop clamped to the structure invalidation, a hybrid
  partial-TP + trailing-remainder exit (or full TP at `partial_fraction = 1.0`), breakeven, and a
  time stop. It is **source-agnostic** on the bars — the live/Phase-8 path passes the **raw
  per-contract** series so roll costs stay honest (hard rule #3). **PnL is points + R only**; the
  200-THB/pt multiplier (Phase 7 `risk/`) and the cost model (Phase 8) are out of scope.
- `src/tfex_s50_multi_tf_swing/backtest/` reports per-strategy expectancy / profit factor / max
  drawdown / win rate / regime-stratified PnL (R-multiples), run independently per strategy
  (`per_strategy.run_per_strategy_backtest` wires detect → simulate → metrics). The walk-forward
  harness + cost model + Sharpe/Sortino are Phase 8.
- **ROADMAP-pure (like Phase 3/4):** no `risk/` wiring, no gateway `extended_data` change, no
  FastAPI endpoint, no ML filter (a Phase-6 hook in Strategy C). Signals/execution emit
  **sizing-ready** outputs the Phase-7 risk engine consumes. The §5 positive-expectancy exit
  metric is deferred → **data-gated** on the 5-year backfill, like Phase 1's backfill.
- **4h / engine-source:** A and B need the 4H bias (mirror-only); on the `engine` source `4h` is
  absent, so `4h_bias_direction` defaults to `neutral` (A/B emit nothing) while **C** still runs.
- **Config:** `SignalConfig` / `ExecutionConfig` (frozen, bounded), surfaced on `Settings` via
  `TFEX_S50_MULTI_TF_SWING_SIGNAL_*` / `_EXECUTION_*` and `signal_config()` / `execution_config()`.
  Defaults reproduce the documented strategy-design behaviour, so an unset env is a no-op.

### Phase 6 — ML probability filter layer

- `src/tfex_s50_multi_tf_swing/ml/` is a **filter, never a strategy** (hard rule #7): a LightGBM
  model gates already-fired rule-based setups, it never generates trades. Two targets —
  `P(trend_continuation)` gates A / B (keep when **high**), `P(fake_breakout)` gates C (keep when
  **low**). The package is a leaf: `signals/ → ml/`; it imports nothing downstream.
- **Default OFF and backward-compatible.** The gate (`ml.filter.filter_signals`) returns a subset of
  the **same** `SetupSignal` instances in their original order, and is the **identity function**
  whenever it is disabled, has no loaded model, lacks a strategy's per-target model, or finds no
  aligned-frame row for a signal's time. With `TFEX_S50_MULTI_TF_SWING_ML_FILTER_ENABLED=false`
  (the default) Phase-5 behaviour is reproduced byte-for-byte.
- **Wired only at the backtest/detect layer** (ROADMAP-pure like Phase 5): an optional, default-`None`
  `ml_filter` parameter on `backtest.per_strategy.run_per_strategy_backtest`. Bind the config + a
  loaded bundle into a closure / `functools.partial` over `filter_signals`. No FastAPI endpoint, no
  live wiring, no `extended_data` / gateway change.
- **Pipeline (owner-side, data-gated):** `ml.labels.label_triple_barrier` (TP / SL / time barriers
  over forward 5m bars) → `ml.features.build_feature_frame` (a fixed, ordered `FEATURE_COLUMNS`
  vector; categoricals to a fixed small-int space with a `0` unknown bucket; missing numerics →
  `NaN` for LightGBM) → `ml.training.walk_forward_train` (**anchored walk-forward only**, never a
  random split; per-fold OOS metrics; a feature-importance audit rejects a model where one feature
  carries `> max_importance_share` of gain) → `ml.store.save_model` / `load_bundle` (LightGBM text
  dump + a `ModelCard` JSON sidecar; the loader is **thread-safe and cached by (path, mtimes)** so a
  booster is parsed once). No raw OHLCV is ever a feature, and no model binary / secret is committed
  (`data/models/`, `data/labels/` are gitignored). LightGBM is imported lazily.
- **Config:** `MLFilterConfig` (frozen, thresholds ∈ [0, 1]) surfaced on `Settings` via
  `TFEX_S50_MULTI_TF_SWING_ML_FILTER_ENABLED` / `_ML_MODEL_DIR` / `_ML_THRESHOLD_CONTINUATION` /
  `_ML_THRESHOLD_FAKE_BREAKOUT` / `_ML_SEED` and `ml_filter_config()`. **Determinism:** fits set
  `deterministic=True` + single-thread + a fixed seed. A future live/async caller must run inference
  via `asyncio.to_thread` (CPU-bound; no async path exists yet). The real trained models + the
  out-of-sample A/B magnitude claim are **data-gated** on the 5-year backfill. Train/evaluate via
  `scripts/ml_filter_demo.py` (synthetic, public-safe) or the lifecycle playbook
  `.claude/playbooks/ml-filter-lifecycle.md`. Design notes: `.claude/knowledge/ml-filter.md`.

### Phase 7 — risk layer

- `src/tfex_s50_multi_tf_swing/risk/` turns the Phase-5 *sizing-ready* outputs
  (`signals.SetupSignal` / `execution.Trade`) into **contract-sized, risk-guarded decisions**. It is
  a leaf: one-way dependency `signals/ + execution/ + regime/ → risk/`; it imports nothing
  downstream (`backtest/`, `live/`, `api/`). Modules: `errors`, `models`, `sizing`, `limits`,
  `killswitch`, `ladder`, `decision`.
- **Position sizing** (`sizing.py`): `position_size = account_risk / (stop_distance × multiplier)`,
  floored to whole contracts (a sub-1 result is **0**, never rounded up). The S50 multiplier is the
  single named constant `S50_MULTIPLIER = Decimal("200")` (TFEX hard rule #1) — never re-typed
  inline. **Money is `Decimal` end-to-end** (equity, risk amount, stop distance); `rv_percentile`
  stays `float`. Volatility scaling (§7.3) reuses the existing regime label
  (`regime.policy.regime_to_size_multiplier`, never re-derived): halve above `high_vol_percentile`,
  no-trade in `panic` (`panic_no_trade`, stricter than the regime policy's ≤ 50 %, configurable).
- **Daily & streak limits** (`limits.py`) are an **immutable session reducer**: `register_outcome`
  folds a closed `TradeOutcome` into a new `SessionRiskState` (deterministic; session date injected,
  no wall-clock). Halts on `-2R` cumulative, 3 consecutive losses, or the trade-count cap. The
  **no-averaging-down** (hard rule #4) and **no-widen-stop** guards raise `RiskLimitError`.
- **Kill switch** (`killswitch.py`, hard rule #8 — overrides everything): abnormal spread / latency
  breach / broker-disconnect / market-halt / daily-loss-hit / manual env flag ⇒ flatten + halt. The
  manual override is `TFEX_S50_MULTI_TF_SWING_RISK_KILL_SWITCH_ENGAGED`; the **admin endpoint is
  deferred** until `api/` lands (Phases 3–6 added no FastAPI endpoint). `KillSwitchState` is the
  typed contract a future live/API layer consumes.
- **Capital-deployment ladder** (`ladder.py`, §7.5): `max_contracts_for_stage` caps by stage
  (paper 0 / micro-live 1 / validated 2 / scale 4), falling back to the highest rung the evidence
  supports. "Scale only on statistical evidence, never on confidence" — the live-evidence inputs are
  **data-gated** (Phase 9/10).
- `decision.evaluate_entry` is the pure orchestrator (kill-switch-first → session limits → sizing →
  ladder cap) that **Phase 8 will drive**; it is not wired into `backtest/` yet (ROADMAP-pure, like
  Phases 3–6). **Config:** `RiskConfig` (frozen, bounded) surfaced on `Settings` via
  `TFEX_S50_MULTI_TF_SWING_RISK_*` + `risk_config()`; an unset env reproduces the documented
  defaults. Design notes: `.claude/knowledge/risk-engine.md`; operations:
  `.claude/playbooks/risk-kill-switch-and-ladder.md`.

### Phase 8 — walk-forward / cost-model layer

- `src/tfex_s50_multi_tf_swing/backtest/` is extended (not duplicated) into the validation harness:
  `costs.py` (the cost model), `walk_forward.py` (the anchored harness), `data_source.py` (the
  source-agnostic loader), plus extended `metrics.py` / `models.py` / `errors.py`. It is a leaf:
  one-way dependency `signals/ + execution/ + risk/ + regime/ + ml/ + data/ → backtest/`; it imports
  nothing from `api/`. **This is the first place `risk.decision.evaluate_entry` is actually driven.**
- **Anchored walk-forward only** (hard rule #6). `walk_forward.generate_windows` is deterministic
  (no RNG, no wall-clock — bounds derived from the injected data span in tz-aware `Asia/Bangkok`),
  defaults to `mode="anchored"` (train start fixed + expanding; `rolling` is configurable), and
  always yields `train_end ≤ test_start`. A no-look-ahead / non-random test guards this.
- **Risk-driven per trade.** `drive_costed_trades` walks costed trades in `entry_time` order,
  starts a fresh `SessionRiskState` per BKK trading date, sizes each via `evaluate_entry`, and skips
  the trade when the engine disallows it (kill switch / session halt / no-trade regime / sub-1
  contract). The **combined** A+B+C run shares **one** daily session (portfolio-wide limits — a
  single live account); the **per-strategy** runs are isolated. THB equity (`Decimal`) compounds
  across windows via the single `risk.sizing.S50_MULTIPLIER`. **The capital ladder caps the `paper`
  stage to 0 contracts**, so a backtest runs at `micro_live`+ (the owner script evaluates scaled
  capacity with full evidence; live deployment stays ladder-gated).
- **Cost model** (`costs.py`): commission + clearing fee (`Decimal`, folded to points via
  `S50_MULTIPLIER`), ATR-scaled slippage (worse on the night / lunch-edge illiquid sessions, via
  `data/session.py`), and tick-based spread. `CostedTrade.net_trade` re-exposes the gross `Trade`
  with net PnL so **every existing R-multiple metric runs unchanged** over the post-cost outcome.
  Execution uses the **raw per-contract** series; signals the back-adjusted continuous (hard rule #3).
- **Metrics** extend (never fork) `metrics.py`: `drawdown_profile` (depth + time-underwater +
  recovery), `sharpe` / `sortino` / `period_ratios` (per-period net-R), and `regime_concentration`
  which **fails loudly** when one regime carries the edge. Typed Pydantic result models in `models.py`.
- **Data source** (`data_source.py`): reads the engine's offline **Parquet snapshot**
  (`ParquetStore`) — **never tvkit** — and raises the typed `WalkForwardDataError` when a frame is
  missing / empty. `4h` stays engine-declined (A/B degrade to `neutral`, C still runs).
- **Per-window ML re-fit** is the injectable `ml_filter_factory` hook (default `None` ⇒ Phase-5
  behaviour byte-for-byte, respecting the default-OFF ML gate); the concrete training wiring lives
  in `scripts/run_walk_forward.py` so the harness stays a lean leaf.
- **Config:** `WalkForwardConfig` / `CostModel` (frozen, bounded) surfaced on `Settings` via
  `TFEX_S50_MULTI_TF_SWING_WALK_FORWARD_*` / `_COST_*` and `walk_forward_config()` / `cost_model()`;
  an unset env reproduces the documented defaults.
- **Reporting:** `scripts/run_walk_forward.py` + `notebooks/08_walk_forward.ipynb` write public-safe
  artifacts (counts / R-metrics / ratios / NAV index only, **never** raw OHLCV) to
  `results/static/backtest/`. **The exit-criteria magnitudes are deferred → data-gated** on the
  5-year TFEX backfill + engine TFEX data — the harness + a synthetic demonstration ship now.
- **Stayed ROADMAP-pure:** no FastAPI endpoint, no gateway `extended_data` change, no `live/` wiring.

### Risk mitigation — drawdown control (post-Phase-8)

A 14-month walk-forward exposed a **31.13R** max drawdown (Window 0), driven by the high-turnover
Strategy C and by entries in unfavourable regimes. Four **config-driven** mitigations cut the tail
risk without any gateway-contract or public/owner-mode change (all reversible via env):

- **Active strategy pool is config-selected** (`signals/gate.py:build_detect_map`,
  `Settings.enabled_strategy_ids`, `TFEX_S50_MULTI_TF_SWING_ENABLED_STRATEGIES`, default **`B`** —
  ORB-only core). Strategy C (the drawdown driver) and the negative-expectancy Strategy A are
  disabled by default but re-enablable with **no code edit** (e.g. `ENABLED_STRATEGIES=A,B,C`).
- **Entry regime gate** (`signals/gate.py:apply_regime_gate`, `SignalConfig.allowed_regimes`,
  `TFEX_S50_MULTI_TF_SWING_SIGNAL_ALLOWED_REGIMES`, default **`trend_up`**) — a vectorised Polars
  pass demotes any fired bar whose 1H regime is outside the allow-set to a clean No-Trade (layers on
  top of the existing Phase-3 per-strategy regime whitelist; only ever removes trades).
- **Wider ATR stop + stricter equity sizing:** `k_atr_stop` default **2.0** (was 1.5);
  `risk_per_trade_pct` default **0.005** (0.5%, was 1%; 1% is the documented aggressive option).
  Sizing is unchanged in logic — already equity-based, `Decimal`, floors sub-1 contracts to 0.
- **Per-window circuit breaker** (`RiskConfig.per_window_loss_limit_r`, default **`-5R`**, driven in
  `backtest/walk_forward.py:drive_costed_trades`): once a window's cumulative net R breaches the
  floor, every further entry that window is suppressed; the trip logs (window id / trades / drawdown)
  and surfaces on `WindowResult.circuit_breaker_tripped`. Stateful per window; resets each boundary.

`notebooks/08_walk_forward.ipynb` re-renders the before/after walk-forward (run with `with_4h=True`
so ORB fires on the local snapshot). Real-data magnitudes stay **data-gated** on the 5-year backfill.

### Execution mode (`TFEX_S50_MULTI_TF_SWING_EXECUTION_MODE`)

The optional execution path (feature-execution-engine Phase 5.1) is gated by
`TFEX_S50_MULTI_TF_SWING_EXECUTION_MODE`. It is a **library + verify-script only**
facility — it is **not** wired into any runner, the daily refresh, or the
backtest/risk path; nothing routes an order unless you call
`tfex_s50_multi_tf_swing.execution.run_sim_loop` (or the verify script) explicitly.

- **`off`** (default): zero-code path. The engine adapter is never instantiated and
  no order HTTP is performed. Adds no required env (module-level `Settings()` keeps
  constructing).
- **`sim`**: submit `NormalizedOrder`s through the **gateway proxy**
  (`/api/v2/engines/execution/*`) to the Execution engine `SimAdapter`, then apply
  the SSE fill stream (`GET /orders/stream`) to a local, evolving `SimPosition`.
  Requires `TFEX_S50_MULTI_TF_SWING_GATEWAY_BASE_URL`,
  `TFEX_S50_MULTI_TF_SWING_GATEWAY_API_KEY` (both reused from the daily-report
  path), and `TFEX_S50_MULTI_TF_SWING_EXECUTION_ACCOUNT`. **`public_mode` defaults
  `True` here, and `sim` is allowed under it** — only `live` is forbidden in public
  mode.
- **`live`**: RESERVED. Rejected at `Settings()` when
  `TFEX_S50_MULTI_TF_SWING_PUBLIC_MODE=true`, and unimplemented in Phase 5.1
  (`run_sim_loop` only runs `sim`). When enabled it would source the real venue from
  `TFEX_S50_MULTI_TF_SWING_EXECUTION_BROKER` (so `live` + broker `sim` is rejected).

Supporting env:

- `TFEX_S50_MULTI_TF_SWING_EXECUTION_ACCOUNT` — broker account stamped on every
  order (`NormalizedOrder.account` is mandatory); required when mode != `off`.
- `TFEX_S50_MULTI_TF_SWING_EXECUTION_BROKER` — `sim` (default) | `liberator` |
  `settrade`.

**TFEX specifics:**

- **`position_effect` is required** on every order — the engine rejects a TFEX
  order without it, so the loop never sends `None`. `NormalizedOrder` pins
  `market="TFEX"` and `wire_dump()` always emits both `market` and
  `position_effect`. (Contrast SET / csm-set, which omits `position_effect`.)
- **`infer_position_effect`** computes OPEN vs CLOSE at submit time against the
  *evolving* position: no position or **same** direction → `OPEN`; **opposite**
  direction with `contracts <= held` → `CLOSE`; an oversize opposite order is a
  **flip, which is unsupported in Phase 5.1** → `SimLoopError`.
- Sizing is in **whole S50 contracts** (integers) and happens **upstream** (the
  risk engine's `PositionSizeResult`); the loop consumes pre-built
  `OrderInstruction`s and never sizes. Instructions are processed **sequentially**
  against the evolving position, so an entry-then-exit pair in one run exercises
  OPEN then CLOSE. `side` is BUY for `long`, SELL for `short`. The S50 book is
  single-direction; a flat book is `None`.

No broker credential ever lives in this repo — the Execution engine is the sole
order-routing-credential owner; tfex only ever posts a normalized order through the
gateway. The loop is single-source (positions move only from stream `fill` events,
never from the POST ack), uses a fresh UUIDv4 `client_order_id` per logical order
(the same id is reused only on transport/5xx retries), a client-side seq watermark
for reconnect dedupe, and a `GET /orders/{cid}` residual reconcile on timeout or
stream reset.

Module locations: `src/tfex_s50_multi_tf_swing/execution/models.py` (wire mirrors +
value objects), `engine_adapter.py` (HTTP/SSE client), `sim_loop.py` (the loop),
`errors.py` (typed exceptions, rooted at the existing `ExecutionError`). Manual
end-to-end check (entry then exit in one invocation):
`uv run python scripts/verify_execution_sim.py --symbol S50Z2026 --contracts 1 --price 970.0`
(needs `TFEX_S50_MULTI_TF_SWING_EXECUTION_MODE=sim` + the gateway env above). See
`.claude/knowledge/execution-mode.md`.

### Public data boundary

Raw OHLCV columns (`open`, `high`, `low`, `close`, `volume`) and proprietary feature
vectors must NEVER appear in `results/static/` or in API responses. Public-mode tests
must enforce this in CI as the project grows. `data/` is gitignored.

## Hard rules — TFEX-specific

1. **Position sizing is in CONTRACTS, not shares or notional.** The S50 multiplier
   is 200 THB per index point — encoded in `src/tfex_s50_multi_tf_swing/risk/sizing.py`
   as a constant, never hardcoded inline elsewhere.
2. **`margin_usage` is a first-class field.** Every daily snapshot to the gateway
   carries `extended_data.report.margin_usage` (decimal as string). Floats are
   forbidden across the gateway boundary.
3. **Continuous contract is rollover-aware.** Back-adjusted prices are used for
   signal generation only. Execution simulation uses the raw per-contract series so
   roll costs are honest.
4. **No averaging down.** Strictly forbidden — a losing trade is a wrong idea, not a
   discount. This rule is encoded in `src/tfex_s50_multi_tf_swing/risk/limits.py` and
   tested.
5. **Regime gates trading.** `range_low_vol` and the lunch dead zone (12:00–14:00) are
   **no-trade** regimes. The system not trading is a feature, not a bug.
6. **Walk-forward only — never random split.** Backtests use anchored walk-forward
   windows. Random splits leak future information.
7. **ML is a filter, not an oracle.** The model produces probabilities that gate
   rule-based signals. It never generates trades. No Deep Learning at this stage.
8. **Kill switch overrides everything.** Abnormal spread, latency spike, broker
   disconnect, daily loss limit hit — flatten positions, halt new entries.

## Hard rules — inherited from the umbrella

1. **Always `uv run`** — never bare `python` / `pip` / `poetry` / `conda`.
2. **Async-first I/O** — all HTTP via `httpx.AsyncClient`. `requests` is forbidden in
   `src/` because it blocks the event loop.
3. **Pydantic at boundaries** — function I/O between `src/`, `api/`, and external
   systems goes through Pydantic models, never raw dicts.
4. **Monetary values are `Decimal`, never `float`, at the gateway boundary.**
   Decimals are serialised as strings on the wire.
5. **Timezone**: store UTC, display `Asia/Bangkok`. TFEX session boundaries are tz-aware
   `pandas.Timestamp` — never mix tz-naive and tz-aware in one frame.
6. **No secrets in repo.** All config via env + `pydantic-settings`. Env var prefix
   is `TFEX_S50_MULTI_TF_SWING_*`.
7. **Ingestion is idempotent.** Posting the same day twice is a no-op (`INSERT … ON
   CONFLICT` at the gateway).
8. **`docs/plans/` is git-tracked.** Do not gitignore it. The roadmap is part of the
   product.

## Coding conventions worth knowing up front

- `from __future__ import annotations` at the top of every `src/` module.
- Module-local exceptions in each subpackage's `errors.py`, all inheriting from a
  shared `TfexS50Error` base. Never `raise Exception(...)` or `except Exception: pass`.
- `logger = logging.getLogger(__name__)` — never `print` in `src/`. Use `%`-formatting
  for log messages so level filtering saves work.
- File-size target ≤ 400 lines; functions ≤ ~50 lines.
- Coverage target ≥ 90% (`--cov-fail-under=90`), enforced over the modules that exist:
  currently `adapters/`, `data/`, `features/`, `regime/`, `bias/`, `signals/`, `execution/`,
  `backtest/`, `ml/`, and `risk/` (added in Phase 7).
- Tests use `asyncio_mode = "auto"` and `--import-mode=importlib`.
- Integration tests requiring the live `quant-infra-db` or the gateway are marked
  `@pytest.mark.infra_db` / `@pytest.mark.gateway` and self-skip when DSNs / base
  URLs are unset.

## Commits

Follow [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`,
`docs:`, `test:`, `chore:`, `refactor:`. Keep scope tight
(`fix(risk): clamp position size`, `chore(skills): update playbook`).

## Where to look next

- **Roadmap (canonical source of truth for what to build next):**
  [`docs/plans/ROADMAP.md`](docs/plans/ROADMAP.md)
- **Strategy overview & rationale:** `.claude/knowledge/strategy-overview.md`
- **Feature engineering rules:** `.claude/knowledge/feature-engineering.md`
- **Regime detection design:** `.claude/knowledge/regime-detection.md`
- **HTF bias engine design:** `.claude/knowledge/bias-engine.md`
- **Strategy A/B/C specifications + Phase-5 implementation notes:** `.claude/knowledge/strategy-design.md`
- **Phase 5 plan (signals / execution / backtest):** [`docs/plans/phase-5-setup-detection-signals.md`](docs/plans/phase-5-setup-detection-signals.md)
- **Phase 6 plan (ML probability filter):** [`docs/plans/phase-6-ml-probability-filter.md`](docs/plans/phase-6-ml-probability-filter.md)
- **Risk engine specification:** `.claude/knowledge/risk-engine.md`
- **Phase 7 plan (risk engine):** [`docs/plans/phase-7-risk-engine.md`](docs/plans/phase-7-risk-engine.md)
- **Phase 8 plan (walk-forward backtest):** [`docs/plans/phase-8-walk-forward-backtest.md`](docs/plans/phase-8-walk-forward-backtest.md)
- **Running the walk-forward backtest:** `.claude/playbooks/walk-forward-backtest.md`
- **Kill-switch / capital-ladder operations:** `.claude/playbooks/risk-kill-switch-and-ladder.md`
- **ML filter design + lifecycle:** `.claude/knowledge/ml-filter.md`, `.claude/playbooks/ml-filter-lifecycle.md`
- **Backtest protocol:** `.claude/knowledge/backtest-protocol.md`
- **Development workflow:** `.claude/playbooks/development-workflow.md`
- **Gateway onboarding checklist:** `.claude/playbooks/onboarding-to-gateway.md`
- **Market data source (engine reads, never tvkit):** the
  [Market data source](docs/plans/ROADMAP.md#market-data-source--the-market-data-engine)
  ROADMAP section; engine docs `../../quant-marketdata-engine/docs/README.md`; reader-cutover
  knowledge `../../.claude/knowledge/feature-market-data-engine-reader-cutover.md`
- **Umbrella system map:** `../../CLAUDE.md`
- **Strategy onboarding contract:** `../../STRATEGY_ONBOARDING.md`
- **Template repo (for code conventions):** `../csm-set/`
