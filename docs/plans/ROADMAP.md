# TFEX S50 Multi-TF Swing Roadmap

Multi-timeframe swing-intraday quant system for SET50 Index Futures (S50) on TFEX.
Development phases ordered by dependency — each phase must be complete and validated
before the next begins. The goal is a **robust live system, not a beautiful backtest**.

---

## Status Legend

| Symbol | Meaning |
|--------|---------|
| `[ ]` | Not started |
| `[~]` | In progress |
| `[x]` | Complete |
| `[-]` | Skipped / deferred |

---

## Market data source — the Market Data Engine

> **The single most important data rule for this strategy: tfex NEVER fetches tvkit and
> NEVER owns the TradingView cookie.** All OHLCV is produced once by the canonical
> **`quant-marketdata-engine`** (the sole tvkit-cookie owner) and tfex *reads* it. Every
> data-acquisition step below — backfill, daily refresh, backtest, paper, live — resolves
> through this one source. This supersedes the original Phase-1 assumption (authored before
> the engine existed) that the strategy fetches tvkit itself.

### How tfex reaches the engine

- The engine runs on container `quant-marketdata-engine:8000` (host `:8300`) on
  `quant-network` and is **gateway-proxied** at `/api/v2/engines/market-data/*`. tfex calls
  the **gateway proxy**, never the engine directly across a repo boundary, never tvkit.
  - In-container base URL: `http://quant-api-gateway:8000/api/v2/engines/market-data`.
  - Host-local dev: `http://localhost:<gateway-host-port>/api/v2/engines/market-data`
    (the engine itself is reachable at `http://localhost:8300` for debugging only).
- The data layer selects its source via the flag
  **`TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE = mirror | engine`** through the factory
  `data/sources.py:build_ohlcv_fetcher`. Both branches return the identical
  `FetcherProtocol`, so `refresh_all` and everything downstream
  (store → continuous → validator → db_writer) is source-agnostic and the switch is
  reversible.

| Mode | Default? | Behaviour |
|---|---|---|
| **`mirror`** | ✅ current default | Legacy Phase-1 path: `OhlcvFetcher` fetches tvkit and writes the local Parquet store + the `09` TimescaleDB mirror. **Requires the tvkit cookie** — the only path that still does. Retained for rollback until tfex is verified on `engine`. |
| **`engine`** | pending Phase 5.x | `EngineOhlcvFetcher` reads **RAW per-dated-contract** bars (`/ohlcv?adjusted=false`, e.g. `S50M2026`) from the Market Data Engine via the gateway proxy. **No tvkit cookie on this path.** Needs `..._MARKET_DATA_ENGINE_BASE_URL` (include the proxy prefix); `..._MARKET_DATA_ENGINE_API_KEY` only if the engine sets one. |

### What the `engine` source does (and does not) do

- **Continuous is built locally.** tfex reads raw dated contracts and back-adjusts via
  `data/continuous.py` — the exact series the strategy was validated on (option (b),
  back-adjusted). The engine's native back-adjusted `S501!` is unbuilt (engine Phase-5
  adjustment-parity), so `fetch_continuous_reference` returns an empty frame and the `S501!`
  cross-check is skipped on this source.
- **The `09` mirror is a derived cache, not a source of truth.** On `engine`,
  `market_data.*` (in `db_market_data`) is canonical; tfex's standalone
  `db_tfex_s50_multi_tf_swing.ohlcv_raw` / `.ohlcv_continuous` (init-script `09`) is demoted
  to a derived local cache — never a parallel ingest. The physical DROP/migration of the `09`
  tables is a **separate `quant-infra-db` PR**, deferred until `engine` is the validated
  default and no reader touches `09`.
- **`open_interest` is carried** through the engine path (NULL for equities).

### Edge cases this source model must handle

- **Engine / gateway unavailable** → no live read; fall back to the offline **Parquet
  snapshot / local store** for backtest scans (infra-db is not a hard dependency for offline
  work). A typed error surfaces; the daily refresh fails loudly rather than silently fetching
  tvkit.
- **`4h` not yet supported on `engine`.** The engine read API serves only `1d | 1h | 5m`;
  `4h` (a `cagg_ohlcv_4h` aggregate that is **not routed**) is declined client-side with a
  typed `EngineTimeframeUnavailableError` **before any I/O** — **never rolled up locally**
  (D10). Enabling it later = add an engine `4h` route, then a one-line change to
  `data/engine_fetcher.py:_TF_TO_ENGINE`. Until then, `4h` is only available on the `mirror`
  source (see Phase 4 — HTF Bias Engine).
- **Mirror cache staleness.** While `mirror` is the default, the local Parquet / `09` mirror
  can drift from the canonical store. The cutover to `engine` ends this divergence; the
  verification gate below guards the flip.
- **Verification gate.** Flipping the default `mirror` → `engine` is gated on **Tier-1 parity
  (100%)** for the contracts tfex uses (5m / 1h), producing
  `quant-marketdata-engine/reports/verification-tfex.json`, plus a confirmation that the
  locally back-adjusted continuous matches the validated series. This is **pending Phase 5.x**
  (no mirror Parquet / no TFEX data in the engine yet).

### Status of the engine integration

This integration is **Phase 4 of the cross-cutting `feature-market-data-engine`** (the
reader-cutover phase) — **distinct from this strategy's own Phase 4 (HTF Bias Engine)
below**. It **shipped 2026-06-02** as tfex PR #6 (`8756b1a`): the flag, the
`EngineOhlcvFetcher`, the `adapters/market_data_engine_client.py`, and the boundary tests.
**The default is still `mirror`** — tfex end-to-end verification + the default flip are
**pending Phase 5.x**.

**See also:**
[`../../../../quant-marketdata-engine/docs/plans/ROADMAP.md`](../../../../quant-marketdata-engine/docs/plans/ROADMAP.md)
(engine roadmap, Phase 4) ·
[`../../../../quant-marketdata-engine/docs/README.md`](../../../../quant-marketdata-engine/docs/README.md)
(engine reference docs) ·
[`../../../../.claude/knowledge/feature-market-data-engine-reader-cutover.md`](../../../../.claude/knowledge/feature-market-data-engine-reader-cutover.md)
(reader-cutover decisions) ·
[`../../../../.claude/playbooks/marketdata-engine-cutover.md`](../../../../.claude/playbooks/marketdata-engine-cutover.md)
(cutover runbook).

---

## Phase 0 — Project Bootstrap & Gateway Onboarding

> Goal: working repo, clean tooling, registered as a strategy under the umbrella
> ingestion contract. After this phase the service is *callable* end-to-end even if
> the data and signal layers are still stubs.

### 0.1 Repository & Tooling

- [x] GitHub repo created and renamed to `lumduan/tfex-s50-multi-tf-swing`
- [x] Local skeleton synced from the Python template (uv, ruff, mypy strict, pytest)
- [x] Initial feature branch `feat/initial-roadmap-and-agent-context`
- [x] Personalise `pyproject.toml`: name `tfex-s50-multi-tf-swing`, description, package
  path `src/tfex_s50_multi_tf_swing/`
- [x] `.env.example` with strategy env prefix `TFEX_S50_MULTI_TF_SWING_*`
- [x] Pre-commit hooks active (`ruff check`, `ruff format`, `mypy`)
- [x] Verify quality gates on empty project: `uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest`

### 0.2 Roadmap & Agent Context

- [x] `docs/plans/ROADMAP.md` — this document
- [x] `CLAUDE.md` — agent guide mirroring `csm-set/CLAUDE.md`
- [x] `.claude/knowledge/*` — strategy overview, feature engineering, regime detection,
  strategy design, risk engine, ML filter, backtest protocol
- [x] `.claude/playbooks/*` — development workflow, gateway onboarding
- [x] `README.md` rewritten for the strategy

### 0.3 Gateway & DB Registration

- [x] Add gateway entry in `quant-api-gateway/strategies.json`:
  ```json
  {
    "id": "tfex-s50-multi-tf-swing",
    "name": "TFEX S50 Multi-Timeframe Swing",
    "type": "TFEX_DERIVATIVES",
    "service_url": "http://quant-tfex-s50-multi-tf-swing:8000",
    "capital_weight": 1.0,
    "active": false
  }
  ```
- [x] Database init script in `quant-infra-db/init-scripts/08_schema_db_tfex_s50_multi_tf_swing.sql`:
  - [x] `equity_curve` (TimescaleDB hypertable)
  - [x] `trade_history` (with `side`, `contracts`, `margin_used`)
  - [x] `backtest_log`
  - [x] `benchmark_equity_curve` (S50 underlying / SET50 TR)
- [x] Reserve host port `:8200` to avoid collision with csm-set (`:8100`) and OpenBB (`:8500`)

### 0.4 Adapter Scaffolding

- [x] `src/tfex_s50_multi_tf_swing/adapters/payload.py` — Pydantic builder for
  `POST /api/v1/ingest/daily-report` (decimal-as-string, UTC tz-aware)
- [x] `src/tfex_s50_multi_tf_swing/adapters/gateway_client.py` — async `httpx.AsyncClient`
  with retry and idempotency
- [x] `src/tfex_s50_multi_tf_swing/adapters/hooks.py` — `run_post_refresh_hook` entrypoint
- [x] Unit tests on adapter modules (≥90% coverage; achieved 99.42%)

### 0.5 Docker

- [x] `docker-compose.yml` — public-safe defaults, joins external `quant-network`
- [x] `docker-compose.private.yml` — write-mode override with `env_file`
- [x] `Dockerfile` parameterised on `TFEX_S50_MULTI_TF_SWING_PUBLIC_MODE`

**Exit criteria:** `docker compose up` starts the service on `quant-network`, gateway
catalog lists the new strategy, an empty daily-report POST round-trips with `202`,
all quality gates pass.

---

## Phase 1 — Data Infrastructure

> Goal: clean, validated OHLCV at 4H / 1H / 5m for S50 futures, stored as Parquet,
> with a back-adjusted continuous contract that survives quarterly rollovers.

> **Status:** code complete on `feature/phase-1-data-infrastructure` (2026-05-28); 5-year backfill
> + visual rollover review pending a real TradingView session token. See
> [`phase-1-data-infrastructure.md`](phase-1-data-infrastructure.md) for the full plan.

### 1.1 OHLCV Ingestion

> **Source is now flag-driven** (`TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE`, see
> [Market data source](#market-data-source--the-market-data-engine) above). The tvkit
> fetcher below is the **`mirror`** (legacy) path and remains the current default; the
> canonical path is **`engine`**, which reads the Market Data Engine via the gateway proxy
> and holds **no tvkit cookie**. The engine source shipped 2026-06-02
> (`feature-market-data-engine` Phase 4); the original "strategy fetches tvkit" assumption
> here is **superseded** by it (default flip pending Phase 5.x).

- [x] `src/tfex_s50_multi_tf_swing/data/fetcher.py` — TFEX S50 OHLCV loader at 4H, 1H, 5m
  - [x] **`mirror` source:** `OhlcvFetcher` fetches `tvkit` (TradingView). TFEX direct feed
    deferred; see Phase 1 plan §8. **Superseded** for canonical use by the `engine` source
    (`data/engine_fetcher.py:EngineOhlcvFetcher` reading the gateway proxy; no cookie).
  - [x] Async batch fetch, retry on transient errors (both sources are `httpx.AsyncClient`)
- [x] Storage layout:
  - [x] `data/raw/<contract>/<timeframe>.parquet` (per quarterly contract — H/M/U/Z)
  - [x] `data/cleaned/<contract>/<timeframe>.parquet` (path reserved by store; Phase 1 emits same content as raw)
  - [x] `data/continuous/<timeframe>.parquet` (back-adjusted)
  - [ ] `data/features/<timeframe>.parquet` — **deferred to Phase 2**
  - [ ] `data/labels/<timeframe>.parquet` — **deferred to Phase 6**

### 1.2 Continuous Futures Contract

- [x] `src/tfex_s50_multi_tf_swing/data/continuous.py` — back-adjusted continuous series
  - [x] Roll on volume crossover near expiry (configurable: `5d_before_expiry` default)
  - [x] Ratio-adjust historical prices to remove rollover gap (ratio = far_close / near_close)
  - [x] Preserve raw per-contract series for execution simulation
- [x] Unit tests: synthetic two-contract roll, assert post-roll continuity in returns

### 1.3 Session Metadata

- [x] `src/tfex_s50_multi_tf_swing/data/session.py`
  - [x] Thai market holiday calendar (2024–2026 baseline; annual refresh documented inline)
  - [x] Trading session boundaries (morning 09:45–12:30, afternoon 14:30–16:55, night
    18:45–03:00; pinned per-minute by unit tests)
  - [x] Expiry-week flag, rollover-week flag
  - [x] Time-of-day buckets: pre-open / open / mid-morning / lunch / afternoon / pre-close / night

### 1.4 Validation Pipeline

- [x] `src/tfex_s50_multi_tf_swing/data/validator.py`
  - [x] Missing candle detection within the observed time window
  - [x] Duplicate timestamp detection
  - [x] Abnormal spread / price-gap flag (>3σ)
  - [x] Cross-timeframe consistency (5m aggregated → 1H == fetched 1H)
  - [x] **Bonus**: `validate_continuous_against_reference` cross-checks our back-adjusted continuous against TradingView's `S501!`
    - On the **`engine`** source this cross-check is **skipped**: the engine's native
      back-adjusted `S501!` is unbuilt, so `fetch_continuous_reference` returns an empty
      frame and the `refresh_all` `height > 0` guard no-ops the comparison. The cross-check
      runs only on the `mirror` source.
- [x] Validation report saved to `data/validation/<date>.json`

### 1.5 Data Quality Notebook

- [x] `notebooks/01_data_quality.ipynb`
  - [x] Missing-candle heatmap per session
  - [x] Return distribution by year, by session
  - [x] Volume / open-interest evolution across rollovers
  - [x] Spread distribution

### Notes

- Per the user's decision (2026-05-28), the **`mirror`** source writes a TimescaleDB mirror
  to `db_tfex_s50_multi_tf_swing.ohlcv_raw` and `.ohlcv_continuous` (schema 09 in
  `quant-infra-db`), so OpenBB / future SQL consumers can read OHLCV without a Parquet
  round-trip. **On the `engine` source this `09` mirror is demoted to a derived local cache**
  (the canonical store is `market_data.*` in `db_market_data`, owned by the engine); the
  physical DROP/migration of the `09` tables is a separate `quant-infra-db` PR, deferred until
  `engine` is the validated default. Parquet remains the durable offline cache either way.
- The `S501!` cross-check is informational, not a hard validator failure — it surfaces
  in `ValidationReport.cross_check` so a human can eyeball divergence at roll
  boundaries (runs on `mirror` only; skipped on `engine`, see §1.4).
- **5-year backfill (`mirror` only):** the legacy path requires a real `TVKIT_AUTH_TOKEN`
  (anonymous tvkit sessions cap at 5,000 bars per symbol) — operationally gated on auth, not
  code-gated. **On the `engine` source tfex holds no cookie at all**: the Market Data Engine
  (the sole cookie owner) performs the backfill once, and tfex simply reads the result via
  the gateway proxy.

**Exit criteria:** continuous 4H / 1H / 5m series for ≥ 5 years of S50 history,
validation report shows < 0.1% missing candles, rollovers visually clean in the
back-adjusted series.

---

## Phase 2 — Feature Engineering

> Goal: a feature panel covering trend, volatility, time-of-day, market structure,
> and regime — this is where the real edge lives, not in any single model.

> **Status:** code complete on `feature/phase-2-feature-engineering` (2026-05-29).
> Polars-native, look-ahead-free. 214 tests pass, 100 % coverage on every
> `features/` module (95.6 % combined incl. data/adapters), mypy strict clean.
> See [`phase-2-feature-engineering.md`](phase-2-feature-engineering.md).

### 2.1 Trend Features

- [x] `src/tfex_s50_multi_tf_swing/features/trend.py`
  - [x] `ema_slope`: `(EMA_t - EMA_{t-n}) / n`, normalised by ATR (`ema_slope_20`, `ema_slope_50`)
  - [x] `structure`: HH/HL/LH/LL classification from confirmed swing pivots
  - [x] `dist_from_vwap`: `(price - VWAP) / ATR` per session
- [x] Unit tests against hand-computed values on synthetic series

### 2.2 Volatility Features

- [x] `src/tfex_s50_multi_tf_swing/features/volatility.py`
  - [x] `atr_ratio`: `ATR_short / ATR_long` (expansion / compression detector)
  - [x] `bollinger_squeeze`: Bollinger band width vs Keltner channel
  - [x] `realised_vol`: rolling realised volatility, multiple horizons
- [x] Unit tests: ATR expansion detection on known squeeze → expansion sequence

### 2.3 Time-of-Day Features

- [x] `src/tfex_s50_multi_tf_swing/features/time_of_day.py`
  - [x] `opening_range`: high/low of first 15m (and 30m, 60m variants)
  - [x] `lunch_zone_flag`: 12:00–14:00 dead-zone indicator
  - [x] `close_auction_flag`: last 15m of session
- [x] Repeatable Thai-market patterns documented in feature comments
  (vectorised session tagging mirrors `SessionCalendar`; anti-drift test asserts agreement)

### 2.4 Market Structure Features

- [x] `src/tfex_s50_multi_tf_swing/features/structure.py`
  - [x] `overnight_gap`: gap vs prior session close
  - [x] `prev_day_high_low`: distance to previous day's H/L in ATR units (`dist_to_prev_high/low`)
  - [x] `initial_balance_range`: IB high/low from first hour (`ib_high`, `ib_low`)
  - [x] `liquidity_levels`: swept-high / swept-low markers (`liquidity_sweep_flag`, emitted at `t+k`)

### 2.5 Regime Features

- [x] `src/tfex_s50_multi_tf_swing/features/regime.py`
  - [x] `realised_vol_percentile` (rolling N-day rank → `rv_percentile`)
  - [x] `trend_persistence` (rolling sign agreement)
  - [x] `range_compression` (low ATR + low ADX flag)
  - [x] `volume_expansion`

### 2.6 Feature Pipeline

- [x] `src/tfex_s50_multi_tf_swing/features/pipeline.py`
  - [x] Combine into panel keyed by `(timestamp, timeframe)`
  - [x] Winsorise outliers at 1st / 99th percentile
  - [x] z-score normalise on a trailing window (no look-ahead)
- [x] Unit test: no data leakage across rolling windows
  (prefix-equals-full look-ahead regression test in `test_pipeline.py`)
- [x] **Bonus**: causal multi-timeframe alignment (`features/align.py`) — HTF features
  availability-shifted (`time + bar_duration`) then backward as-of joined onto the base TF;
  materialised to `data/features/aligned_5m.parquet`.

**Exit criteria:** feature panel materialised under `data/features/` ✓ (per-TF + aligned),
all features have unit tests ✓. Feature-stability notebook scaffolded
(`notebooks/02_feature_stability.ipynb`); the full 5-year visual rollover review remains
**data-gated** on a real `TVKIT_AUTH_TOKEN` backfill, exactly like Phase 1's backfill.

> **Notes (2026-05-29):**
> - Stack is **Polars** (not pandas) to match Phase 1; features compute and persist as
>   **Float64** (flags `Int8`, categoricals `Utf8`). Decimal is reserved for money at the
>   gateway boundary — features are internal and never cross it.
> - Look-ahead discipline: trailing-only windows (never `center`), confirmation lag
>   shifted forward for pivots/sweeps, prev-session refs strictly prior, trailing-window
>   winsorise + z-score, and availability-shifted as-of joins across timeframes.
> - Bars are open-labelled (verified in `data/fetcher.py`), so an HTF bar at `time=t` is
>   only usable at `t + TIMEFRAME_MINUTES[tf]`; the aligner keys off that.

---

## Phase 3 — Regime Detection

> Goal: classify every bar into one of five regimes so downstream strategies can
> turn themselves on or off. Regime awareness is the single largest source of edge.

### 3.1 Rule-Based Baseline

- [x] `src/tfex_s50_multi_tf_swing/regime/rules.py`
  - [x] Classify into `trend_up`, `trend_down`, `range_low_vol`, `range_high_vol`, `panic`
  - [x] Rule set documented in `.claude/knowledge/regime-detection.md`
- [x] Unit tests on labelled synthetic series

### 3.2 Clustering Step (optional intermediate)

- [-] `notebooks/03_regime_clustering.ipynb` — KMeans / Gaussian Mixture on regime
  feature vector; visual comparison against rule-based labels *(deferred — optional;
  see note below)*

### 3.3 LightGBM Classifier

- [-] `src/tfex_s50_multi_tf_swing/regime/model.py` *(deferred — needs a hand-labelled
  dataset; see note below)*
  - [-] LightGBM multi-class classifier
  - [-] Trained on rule-based labels as weak supervision, then refined with
    hand-curated regime windows
  - [-] Walk-forward retrain schedule (quarterly)
- [-] Confusion matrix and regime transition stability notebook

### 3.4 Regime-to-Strategy Mapping

- [x] `src/tfex_s50_multi_tf_swing/regime/policy.py` — `regime_to_strategies()` returning
  the allowed strategy set per regime:
  - [x] `trend_up / trend_down` → A (pullback continuation), B (opening-range breakout)
  - [x] `range_high_vol` → C (liquidity sweep reversal)
  - [x] `range_low_vol` → no trade
  - [x] `panic` → reduced size (50%) or no trade
- [x] Unit test: every regime maps to a defined policy

**Exit criteria:** regime classifier with > 70% agreement vs hand-labelled regimes
on a held-out year; "no trade" regimes correctly suppress signals; regime-to-strategy
policy table green-flagged.

> **Notes (2026-05-29):**
> - **§3.1 + §3.4 shipped** in PR `feature/phase-3-regime-detection`. New leaf package
>   `src/tfex_s50_multi_tf_swing/regime/` (`errors.py`, `models.py`, `rules.py`,
>   `policy.py`) consuming the **un-normalised** Phase 2 feature panel. Plan:
>   [`phase-3-regime-detection.md`](phase-3-regime-detection.md). Coverage gate extended
>   to `regime/` (100% on the new module; suite 96% overall).
> - **§3.2 + §3.3 deferred.** The LightGBM exit criterion (> 70% agreement vs
>   hand-labelled regimes on a held-out year) requires a hand-labelled regime dataset that
>   does not exist yet, and `.claude/knowledge/regime-detection.md` says "do not skip
>   steps" — the rule baseline (step 1) is the weak-supervision target for the future
>   model. Clustering (§3.2) is explicitly optional. Both move to a follow-up PR once a
>   labelled window set exists.
> - **Stayed ROADMAP-pure:** no FastAPI endpoint, no gateway `extended_data` change, no
>   `risk/` wiring this phase — the `api/` (Phase 5) and `risk/` (Phase 7) packages do not
>   exist yet. `regime/policy.py` is the gating contract those phases will consume.
> - **Gotcha:** the `structure` (HH/HL/LH/LL) feature is frequently null on synthetic
>   series with sparse swing pivots, so deterministic classifier tests build the regime
>   input frame directly (per-branch) rather than relying on the full pipeline to emit a
>   specific structure label. Null core inputs (insufficient lookback) are classified
>   `range_low_vol` — the no-trade bucket — so trading is never enabled on undefined
>   features.
> - **Dep hygiene:** bumped transitive `idna` 3.13→3.17 and `urllib3` 2.6.3→2.7.0 in
>   `uv.lock` to clear pre-existing `pip-audit` advisories (not introduced by this phase).

---

## Phase 4 — Higher-Timeframe Bias Engine (4H)

> Goal: reduce bad trades by enforcing alignment with the dominant 4H trend before
> any setup is considered. The bias engine *vetoes* trades; it does not generate them.

> **Data-source dependency (4h):** this engine consumes **`4h`** bars, which the **`engine`**
> OHLCV source currently **declines** (`EngineTimeframeUnavailableError`) because the Market
> Data Engine has no `4h` route yet (`cagg_ohlcv_4h` unrouted; no local rollup — D10). Until
> the engine exposes a `4h` route, `4h` is available **only on the `mirror` source**. The
> `bias/` package itself is **source-agnostic** — it consumes already-loaded 4H frames and
> never fetches tvkit / picks a fetcher. This is the one place tfex's roadmap is blocked from
> running fully on the canonical engine source; the unblocker is an engine `4h` route follow-up
> (then a one-line enablement in `data/engine_fetcher.py:_TF_TO_ENGINE`, a
> `quant-marketdata-engine` change out of scope for this strategy). See
> [Market data source](#market-data-source--the-market-data-engine).

### 4.1 4H Trend Filter

- [x] `src/tfex_s50_multi_tf_swing/bias/htf.py`
  - [x] `ema20_above_ema50` (Long) / `ema20_below_ema50` (Short)
  - [x] Positive vs negative EMA slope
  - [x] HH/HL structure check
  - [x] Price relative to HTF VWAP
  - [x] Volatility-healthy gate (not in `panic`, not in `range_low_vol`) — reuses `regime/`

### 4.2 Bias Output

- [x] `BiasSignal` Pydantic model: `direction: Literal["long", "short", "neutral"]`,
  `reasons: list[str]`
- [x] CLI/notebook to visualise bias overlaid on 4H chart
  (`scripts/visualise_bias.py`, `notebooks/04_htf_bias.ipynb`)

### 4.3 Backtest of Bias Filter

- [~] Compare baseline naive strategy with/without bias filter on the same period
  — **demonstration only** (`scripts/bias_counter_trend_demo.py`, naive candidate proxy)
- [-] Confirm bias filter improves expectancy or reduces drawdown — **deferred → blocked-on
  Phase 5** (needs `signals/` + `execution/` + `backtest/`, which do not exist yet)

**Exit criteria:** bias signal materialised per 4H bar ✓; the ≥ 30% counter-trend-reduction
histogram vs the *real* unfiltered baseline is **deferred to Phase 5** — the §4.3 demonstration
proves the veto mechanism on a naive candidate proxy, but the magnitude claim awaits real
signals (see Design Decision D9 in the Phase 4 plan).

> **Notes (2026-06-03):**
> - **§4.1 + §4.2 shipped** on `feature/phase-4-htf-bias-engine`. New leaf package
>   `src/tfex_s50_multi_tf_swing/bias/` (`errors.py`, `models.py`, `htf.py`, `__init__.py`)
>   consuming the **un-normalised** Phase 2 panel + the Phase 3 regime label. Plan:
>   [`phase-4-htf-bias-engine.md`](phase-4-htf-bias-engine.md). Coverage gate extended to
>   `bias/` (100% on the new module; suite 96.6% overall, 343 passed).
> - **Composition is conservative unanimity:** a directional bias needs *every* gate to agree
>   (EMA cross + slope + structure + VWAP) **and** a healthy regime; any disagreement, tie EMA,
>   null `structure`, or insufficient lookback → `neutral` (never a directional guess). It
>   **vetoes, never generates** — `BiasSignal` carries `direction` + one auditable `reasons`
>   string per gate.
> - **Reuses `regime/`:** the volatility-healthy gate reads the *same* regime classification
>   (`panic` / `range_low_vol` → `neutral`), never re-derived; deadbands live in `BiasConfig`
>   (`TFEX_S50_MULTI_TF_SWING_BIAS_*` via `Settings.bias_config()`), no threshold hard-coded.
> - **§4.3 deferred** (mirrors the Phase 3 deferral honesty): no faked backtest. The demo
>   script computes a counter-trend-reduction % on a naive 1-bar-momentum candidate proxy and
>   saves a **public-safe** artifact (counts only, no raw OHLCV) to `results/static/bias/`.
> - **Stayed ROADMAP-pure:** no FastAPI endpoint, no gateway `extended_data` change, no
>   `risk/`/`signals/` wiring — those packages do not exist (Phases 5 / 7). `bias/` is the veto
>   contract they will consume; it imports nothing downstream and never fetches tvkit.
> - **4h-source constraint restated:** `4h` is mirror-only today (engine declines it before any
>   I/O, no local rollup); `bias/` is source-agnostic so the cutover to an engine `4h` route is
>   a one-line `_TF_TO_ENGINE` change with zero bias-layer impact.
> - **Gotcha:** `structure` (HH/HL/LH/LL) is frequently null on sparse synthetic pivots, so the
>   classifier tests build bias-input frames per-branch directly (one row per gate) rather than
>   relying on the pipeline to emit a specific label — the same approach Phase 3 used.

---

## Phase 5 — Setup Detection & Signal Strategies

> Goal: three trading strategies — A (primary), B and C — each gated by HTF bias
> and regime policy, each backtested independently before combination.

### 5.1 Strategy A — Pullback Continuation ⭐ (primary)

- [x] `src/tfex_s50_multi_tf_swing/signals/strategy_a.py`
  - [x] 4H confirms direction (HTF `bias_direction` veto) + 1H regime whitelists A
  - [x] 1H pullback to VWAP, structure intact, volume contracting, ATR contracting
  - [x] 5m volatility compression detected, awaiting re-expansion
  - [x] 5m entry on swing-breakout + VWAP reclaim + volume expansion
- [x] Unit tests on hand-crafted scenarios for entry, no-entry, false-trigger

### 5.2 Strategy B — Opening Range Breakout

- [x] `src/tfex_s50_multi_tf_swing/signals/strategy_b.py`
  - [x] Opening range read from `or_high_{or_window}` / `or_low_{or_window}` (default 15m)
  - [x] Breakout with volume expansion confirms entry
  - [x] HTF-aligned and not in `range_low_vol` regime
  - [x] Suppressed during lunch zone (`lunch_zone_flag`)

### 5.3 Strategy C — Liquidity Sweep Reversal

- [x] `src/tfex_s50_multi_tf_swing/signals/strategy_c.py`
  - [x] Detect high/low sweep (`liquidity_sweep_flag`; works on the engine source, no 4H bias)
  - [x] Confirm reversal (VWAP reclaim) + structure shift
  - [-] Optional ML probability check — **Phase 6 hook** (documented, not implemented)

### 5.4 Execution Engine (5m)

- [x] `src/tfex_s50_multi_tf_swing/execution/engine.py`
  - [x] Entry: **next-bar-open** fill + spread-proxy acceptable (no same-bar look-ahead)
  - [x] Stop loss: structure-aware *and* volatility-aware (`SL = entry − k·ATR`,
    clamped to the nearest invalidation level)
  - [x] Take profit: hybrid policy — partial TP at 1R (50%), trail remainder on
    structure (or full TP when `partial_fraction = 1.0`)
  - [x] Move stop to breakeven on +1R (configurable buffer to avoid noise stop-outs)
  - [x] Time stop: exit if no progress within `N` bars
- [x] Unit tests on simulated bar sequences

### 5.5 Per-Strategy Backtest

- [x] Backtest each strategy independently before any composite is built
  (`backtest/per_strategy.py` + `metrics.py`; harness + synthetic-trade tests + public-safe demo)
- [x] Report expectancy, profit factor, max drawdown, regime-stratified PnL (in **R-multiples**)
- [-] **Positive-expectancy-after-costs magnitude** — deferred → **data-gated** on the 5-year
  backfill (blocked on a TVKIT token / engine TFEX data) + a cost model (Phase 8)

**Exit criteria:** each strategy reaches positive expectancy after costs on the
training period and is stable across at least two distinct regimes — **deferred (data-gated)**,
exactly like Phase 1's backfill and Phase 4 §4.3; the Phase-5 code + harness + demonstration ship,
the magnitude claim awaits real data.

> **Notes (2026-06-03):**
> - **§5.1–§5.4 shipped + §5.5 harness** on `feature/phase-5-setup-detection-signals` as three
>   new leaf packages: `signals/` (`errors`, `models`, `inputs`, `base`, `strategy_a/b/c`),
>   `execution/` (`errors`, `models`, `engine`), `backtest/` (`errors`, `models`, `metrics`,
>   `per_strategy`). Plan: [`phase-5-setup-detection-signals.md`](phase-5-setup-detection-signals.md).
>   Coverage gate extended to all three (`signals/` 96–100 %, `execution/` 98–100 %, `backtest/`
>   100 %; suite 97.17 %, 440 passed), mypy strict clean.
> - **Multi-TF resolved on the 5m grid:** `signals/inputs.build_signal_inputs` reuses the Phase-2
>   causal aligner to widen 5m with `1h_*` + `1h_regime` (the gating regime) and the per-4H
>   `4h_bias_direction` (the veto) — every HTF column availability-shifted, no look-ahead
>   (asserted by `test_inputs.py`). Each strategy mirrors the bias shape
>   (`classify_frame`/`classify_row`/`to_signals`) and fires only on full agreement.
> - **4h / engine-source aware:** A and B require the 4H bias (mirror-only); when the `engine`
>   source omits `4h`, `4h_bias_direction` defaults to `neutral` so A/B emit nothing while **C**
>   (gated on the 1H regime, not the 4H bias) still runs.
> - **Execution** fills next-bar-open (no same-bar look-ahead), clamps `k·ATR` to the structure
>   stop, banks a partial + trails the remainder (or full TP at `partial_fraction = 1.0`), and is
>   source-agnostic on the bars (raw per-contract in live/Phase-8 per hard-rule #3). **PnL is
>   points + R only** — the 200-THB/pt multiplier is Phase 7, the cost model Phase 8.
> - **Stayed ROADMAP-pure:** no `risk/` (Phase 7), no gateway `extended_data` change (later
>   pipeline phase), no FastAPI endpoint, no ML filter (Phase 6 hook in C). Signals/execution emit
>   *sizing-ready* outputs the Phase-7 risk engine will consume.
> - **Gotcha:** under mypy strict, module-level `STRATEGY_ID = "A"` infers `str`; annotated as
>   `StrategyId`. Full `take_profit` was unreachable under the partial+trail policy, so it now
>   fires only with `partial_fraction = 1.0` (full close at target).

---

## Phase 6 — ML Probability Filter

> Goal: use ML as a **filter**, not a strategy. The model produces probabilities
> that gate existing rule-based signals; it does not generate trades.

> **Status (2026-06-04): machinery shipped, default-OFF; magnitude data-gated.**
> The `ml/` package (labels, features, walk-forward LightGBM trainer, versioned store,
> the gate) ships behind `TFEX_S50_MULTI_TF_SWING_ML_FILTER_ENABLED` (default `false`):
> with the toggle off — or no model artifact present — the filter is the identity
> function and Phase-5 behaviour is byte-for-byte unchanged. Wired only at the
> backtest/detect layer (`run_per_strategy_backtest(ml_filter=…)`), ROADMAP-pure like
> Phase 5 (no `risk/`, no API endpoint, no `extended_data` change). Tested ≥ 90 %
> (100 %) on `ml/`, mypy strict. **Real trained models + the out-of-sample A/B
> expectancy claim remain data-gated on the 5-year backfill** (same gate as Phases
> 1/3/4/5). Plan: [`phase-6-ml-probability-filter.md`](phase-6-ml-probability-filter.md).

### 6.1 Labelled Dataset

- [x] `src/tfex_s50_multi_tf_swing/ml/labels.py`
  - [x] Triple-barrier labelling (TP / SL / time)
  - [x] Per-setup labels for `trend_continuation` and `fake_breakout`
  - [x] Saved to `data/labels/` keyed by `(setup_id, label_type)` (`save_labels`)

### 6.2 LightGBM Models

- [x] `src/tfex_s50_multi_tf_swing/ml/models.py` + `training.py` / `store.py`
  - [x] `P(trend_continuation)` — gates Strategy A & B
  - [x] `P(fake_breakout)` — gates Strategy C
  - [x] Walk-forward training schedule, no random splits
- [x] Feature importance audit; no single feature dominating (`audit_importance`)

### 6.3 Filter Integration

- [x] Threshold per model documented + configurable (`P(continuation) ≥ 0.55`, `P(fake) ≤ 0.50`)
- [x] A/B compare harness with vs without ML filter (`ml_filter` param; `scripts/ml_filter_demo.py`)
  - the out-of-sample *magnitude* claim is **data-gated** on the 5-year backfill

### 6.4 Anti-Overfit Discipline

- [x] Walk-forward only — never random split (asserted in tests)
- [x] Out-of-sample metrics computed per fold; required to ship a real model — **data-gated**
- [x] No Deep Learning at this stage (see Non-goals)

**Exit criteria:** ML-filtered strategies improve out-of-sample expectancy or
profit factor vs unfiltered; no regime sees a worse performance with the filter on.
*(Machinery in place; the exit metric is data-gated on the 5-year backfill.)*

---

## Phase 7 — Risk Engine

> Goal: survive every regime. Risk Engine is more important than any signal.

### 7.1 Position Sizing

- [x] `src/tfex_s50_multi_tf_swing/risk/sizing.py`
  - [x] `position_size = account_risk / (stop_distance × multiplier)` (floored; sub-1 ⇒ 0)
  - [x] S50 multiplier: 200 THB per point (`S50_MULTIPLIER`, single named constant)
  - [x] Default `account_risk = 1%` of equity (`RiskConfig.risk_per_trade_pct`)
  - [x] Volatility scaling: wider stop ⇒ smaller position (+ §7.3 regime/percentile factor)
- [x] Unit tests against the worked example
  (100k equity, 1% risk, 5-pt stop ⇒ 1 contract)

### 7.2 Daily & Streak Limits

- [x] `src/tfex_s50_multi_tf_swing/risk/limits.py` (immutable session reducer)
  - [x] Daily loss limit: `-2R` → stop trading today
  - [x] Consecutive loss limit: 3 in a row → pause until next session
  - [x] Daily trade-count cap (configurable)
  - [x] **Bonus:** no-averaging-down (hard rule #4) + no-widen-stop guards, tested

### 7.3 Volatility Scaling

- [x] Scale size down when realised volatility breaches a high percentile (`high_vol_size_factor`)
- [x] No-trade gate at extreme percentile / panic regime (`panic_no_trade`, reuses `regime/`)

### 7.4 Kill Switch

- [x] Abnormal spread / latency / broker-disconnect / market-halt / daily-loss → flatten + halt
- [x] Manual kill switch via env flag (`TFEX_S50_MULTI_TF_SWING_RISK_KILL_SWITCH_ENGAGED`)
- [-] Admin endpoint — **deferred** until the `api/` package lands (Phases 3–6 added no FastAPI
  endpoint; `KillSwitchState` is the typed contract a future live/API layer consumes)

### 7.5 Capital Deployment Ladder

| Phase | Size | Condition |
| --- | --- | --- |
| Paper | 0 | Validate logic only |
| Micro Live | 1 contract | Strategy passed paper |
| Validated | 2 contracts | Statistical evidence (≥ 6 months live) |
| Scale | Scale carefully | Stable for 6+ months in production |

**Exit criteria:** risk engine unit-tested across boundary cases ✓, kill switch
verified in a fault-injection test ✓, capital-ladder rules encoded as runtime guards ✓.

> **Notes (2026-06-04):**
> - **§7.1–§7.5 shipped** on `feature/phase-7-risk-engine` as the `risk/` leaf package
>   (`errors`, `models`, `sizing`, `limits`, `killswitch`, `ladder`, `decision`). Plan:
>   [`phase-7-risk-engine.md`](phase-7-risk-engine.md). Coverage gate extended to `risk/`
>   (100 % on the module; suite 97.8 %, 584 passed), mypy strict clean.
> - **Money is Decimal end-to-end** (equity, risk amount, stop distance, the `S50_MULTIPLIER =
>   200`); `rv_percentile` stays float. Sizing floors to whole contracts (`ROUND_DOWN`); a sub-1
>   result is 0 (no trade), never rounded up.
> - **Volatility scaling reuses the regime label** (`regime.policy.regime_to_size_multiplier`,
>   never re-derived): halve above `high_vol_percentile`, no-trade in `panic` (stricter than the
>   regime policy's ≤ 50 %, configurable via `panic_no_trade`).
> - **Session limits are an immutable reducer** (`register_outcome` → new `SessionRiskState`),
>   deterministic with the session date injected; the no-averaging-down (#4) and no-widen-stop
>   guards raise `RiskLimitError`.
> - **Kill switch overrides everything** (hard rule #8) — `decision.evaluate_entry` checks it
>   first; any trigger flattens + halts. Manual override is an **env flag**; the **admin endpoint
>   is deferred** to `api/`.
> - **Capital ladder is a runtime guard** (`max_contracts_for_stage`): paper 0 / micro-live 1 /
>   validated 2 / scale 4, capped down when evidence is absent. The "≥ 6 months live" evidence is
>   **data-gated** (Phase 9/10) — the guard encodes the rule, the inputs arrive later.
> - **Stayed ROADMAP-pure (like Phases 3–6):** no gateway `extended_data` change, no FastAPI
>   endpoint, no `live/` wiring, no walk-forward. `decision.evaluate_entry` is a pure entry point
>   **not** wired into `backtest/`; Phase 8 will drive it.
> - **Gotcha:** `RiskConfig.risk_per_trade_pct` is a float ratio; it is converted via
>   `Decimal(str(pct))` before multiplying equity so the sizing arithmetic stays exact Decimal.

---

## Phase 8 — Walk-Forward Backtest

> Goal: prove the system survives across regimes, with realistic costs. **No random
> splits ever.**

> **Data source:** walk-forward reads OHLCV from the **Market Data Engine** (the `engine`
> source, gateway proxy) — never from a per-strategy tvkit fetch. For heavy full-history
> columnar scans, read the engine's **Parquet snapshot** (the derived offline cache), which
> stays usable even when infra-db / the gateway is down. See
> [Market data source](#market-data-source--the-market-data-engine).

### 8.1 Walk-Forward Harness

- [x] `src/tfex_s50_multi_tf_swing/backtest/walk_forward.py`
  - [x] Anchored windows (default; train start fixed + expanding) — rolling variant configurable
  - [x] Re-fit ML models per window — injectable `ml_filter_factory` hook honouring the default-OFF gate
  - [x] Configurable cost model
- [x] Cost simulation (`src/tfex_s50_multi_tf_swing/backtest/costs.py`):
  - [x] Commission: per-contract fee + clearing fee (Decimal, folded via `S50_MULTIPLIER`)
  - [x] Slippage: ATR-scaled (and worse on illiquid sessions — night / lunch edge via `data/session.py`)
  - [x] Spread: tick-based

### 8.2 Metrics

- [x] `src/tfex_s50_multi_tf_swing/backtest/metrics.py`
  - [x] Expectancy (avg R per trade)
  - [x] Max drawdown (peak-to-trough, time underwater + recovery — `drawdown_profile`)
  - [x] Profit factor (gross-up / gross-down)
  - [x] Regime-stratified metrics (per regime: expectancy, win rate) + loud `regime_concentration`
  - [x] Sharpe / Sortino (per period)

### 8.3 Reporting

- [x] `notebooks/08_walk_forward.ipynb`
  - [x] Equity curve per window, concatenated (NAV indexed to 100, vs S50 buy-and-hold)
  - [x] Drawdown chart with regime overlay
  - [x] Per-strategy and combined results
  - [x] Sensitivity sweep on key thresholds (ATR multiplier, ML thresholds)
- [x] Owner script `scripts/run_walk_forward.py` → public-safe `results/static/backtest/walk_forward.json`

**Exit criteria:** positive expectancy after costs across all walk-forward windows,
max drawdown within budget, regime stability evidenced.

> **Notes (2026-06-04):** Shipped on `feature/phase-8-walk-forward-backtest` as a cohesive
> extension of the `backtest/` leaf package — `costs.py` (cost model), `walk_forward.py` (anchored
> harness, the first place `risk.decision.evaluate_entry` is driven per trade), `data_source.py`
> (engine / Parquet-snapshot loader, never tvkit), extended `metrics.py` + `models.py` +
> `errors.py`, `WalkForwardConfig` / `CostModel` on `Settings`, `scripts/run_walk_forward.py` +
> `notebooks/08_walk_forward.ipynb`. 100 % coverage on the new modules, mypy strict, full gate green.
> - **Anchored windows only** (TFEX hard rule #6) — `generate_windows` is deterministic and asserts
>   `train_end ≤ test_start`; a non-random / no-look-ahead test is part of the suite.
> - **Combined run shares one daily `SessionRiskState`** across A/B/C (portfolio-wide limits); the
>   per-strategy runs are isolated. Execution uses the **raw per-contract** series, signals the
>   back-adjusted continuous (hard rule #3). Money is `Decimal` via the single `S50_MULTIPLIER`.
> - **The exit-criteria *magnitudes* are deferred → data-gated** on the (non-existent) 5-year TFEX
>   backfill + engine TFEX data — Phase 8 ships the *machinery* + a synthetic / public-safe
>   demonstration, never a faked backtest. `[~]`-grade: machinery complete, numbers pending data.
> - **Backtest deployment stage:** the capital ladder caps `paper` to 0 contracts, so a backtest
>   runs at `micro_live`+ (the owner script evaluates scaled capacity with full evidence; live
>   deployment stays ladder-gated). **rv-percentile size-halving** is not threaded onto the
>   execution `Trade` — backtest sizing uses the regime cap (a documented, non-faked enhancement).
> - **Stayed ROADMAP-pure:** no FastAPI endpoint, no gateway `extended_data` change, no `live/`
>   wiring. Plan: [`phase-8-walk-forward-backtest.md`](phase-8-walk-forward-backtest.md).

---

## Phase 9 — Paper Trading

> Goal: run real-time without sending orders, for 2–3 months, across multiple
> regimes (trend, sideways, high vol, low vol).

### 9.1 Real-Time Pipeline

- [ ] `src/tfex_s50_multi_tf_swing/live/paper.py`
  - [ ] Consumes live 5m bars **read from the Market Data Engine** (the `engine` source via
    the gateway proxy `/api/v2/engines/market-data/*`) — never a per-strategy tvkit fetch
  - [ ] Computes signal + risk + sizing
  - [ ] Emits a *would-be* order to log, never to broker
- [ ] Latency budget audit (signal → would-be order)

### 9.2 Logging & Comparison

- [ ] Log every signal, hypothetical entry, hypothetical exit
- [ ] Compare expected fill (at signal close) vs actual fill (at next bar open):
  document slippage distribution

### 9.3 Regime Coverage Requirement

- [ ] Paper trading window must include at least:
  - [ ] One sustained trend
  - [ ] One sustained range
  - [ ] One high-volatility event
  - [ ] One low-volatility chop period

**Exit criteria:** 60+ trading days of paper logs, slippage / expected-fill within
the model's cost budget, no kill-switch trigger, no PnL surprises vs backtest
expectations within an acceptable confidence band.

---

## Phase 10 — Live Deployment

> Goal: 1 contract, 100k–200k THB capital, live execution with full logging.

> **Two distinct feeds, do not conflate:** market **OHLCV** (signals, regime, bias) is read
> from the **Market Data Engine** (the `engine` source via the gateway proxy); the broker
> API below is only for **order routing, fills, positions, and margin**. tfex still holds no
> tvkit cookie in live mode. See
> [Market data source](#market-data-source--the-market-data-engine).

### 10.1 Broker Integration

- [ ] `src/tfex_s50_multi_tf_swing/live/broker.py` — chosen TFEX broker API client
  (Settrade / TradeMax / TFEX-supported gateway)
- [ ] Order types: market-on-close, limit-with-timeout, stop-market
- [ ] Reconciliation: positions / fills / margin reflect broker state

### 10.2 Logging Pipeline

- [ ] Log: signal → order → fill → slippage → latency → equity update
- [ ] Mirror daily snapshot to gateway via the Phase 0 adapter
- [ ] Mongo logs for execution-grade telemetry

### 10.3 Monitoring & Alerting

- [ ] Real-time alerts on: stop hit, daily loss limit hit, consecutive loss, spread
  anomaly, broker disconnect
- [ ] Daily report posted to gateway, surfaced in OpenBB dashboard

### 10.4 Gateway Activation

- [ ] Flip `active: true` in `quant-api-gateway/strategies.json`
- [ ] Confirm auto `portfolio_snapshot` rows are generated combining csm-set + tfex

**Exit criteria:** at least 1 calendar month of live trading at 1 contract with
clean logs, no kill-switch triggers, daily reports flowing to gateway.

---

## Phase 11 — Adaptive Evolution (Future)

> Goal: only after Phase 10 demonstrates stable live PnL for 6+ months.

- [ ] Multi-strategy portfolio across A, B, C with weight optimisation
- [ ] Dynamic capital allocation by regime (more capital in trend regimes)
- [ ] Ensemble ML models (LightGBM + XGBoost + CatBoost, no Deep Learning)
- [ ] Regime-specific models (separate trained model per regime)
- [ ] Cross-instrument extension (S50 → bond futures, gold futures) — only with
  statistical evidence

**Exit criteria:** documented evidence the per-strategy weights or regime-specific
models outperform the unified policy out-of-sample. No early scaling allowed.

---

## Dependency Map

```
Phase 0 (Bootstrap & Onboarding)
    └── Phase 1 (Data Infrastructure)
            └── Phase 2 (Feature Engineering)
                    ├── Phase 3 (Regime Detection)
                    │       └── Phase 4 (HTF Bias Engine)
                    │               └── Phase 5 (Setup Detection & Signals)
                    │                       ├── Phase 6 (ML Filter)
                    │                       │       └── Phase 8 (Walk-Forward Backtest)
                    │                       └── Phase 7 (Risk Engine)
                    │                               └── Phase 8 (Walk-Forward Backtest)
                    └── (features inform regime + signals + risk)

Phase 8 (Walk-Forward Backtest)
    └── Phase 9 (Paper Trading)
            └── Phase 10 (Live Deployment)
                    └── Phase 11 (Adaptive Evolution)
```

---

## Estimated Timeline

| Phase | Scope                              | Estimate     |
|-------|------------------------------------|--------------|
| 0     | Project Bootstrap & Gateway        | 1 week       |
| 1     | Data Infrastructure                | 2 weeks      |
| 2     | Feature Engineering                | 2–3 weeks    |
| 3     | Regime Detection                   | 2 weeks      |
| 4     | HTF Bias Engine                    | 1 week       |
| 5     | Setup Detection & Signals          | 3–4 weeks    |
| 6     | ML Probability Filter              | 2 weeks      |
| 7     | Risk Engine                        | 1 week       |
| 8     | Walk-Forward Backtest              | 2 weeks      |
| 9     | Paper Trading                      | 2–3 months   |
| 10    | Live Deployment                    | open-ended   |
| 11    | Adaptive Evolution                 | open-ended   |

**MVP to live (Phase 0–10): ~6–9 months** of disciplined work, with the majority of
the calendar consumed by paper trading rather than coding.

---

## Current Status

> Update this section as phases complete.

- **Active phase:** Phase 9 — Paper Trading (next). **Phase 8 — Walk-Forward Backtest machinery
  shipped 2026-06-04** on `feature/phase-8-walk-forward-backtest` (the `backtest/` extension:
  `costs.py` cost model, `walk_forward.py` anchored harness driving `risk.decision.evaluate_entry`
  per trade with one shared daily session across A/B/C, `data_source.py` engine/Parquet-snapshot
  loader, extended `metrics.py` (Sharpe/Sortino, drawdown profile, regime concentration) +
  `models.py` + `errors.py`, `WalkForwardConfig`/`CostModel` on `Settings`,
  `scripts/run_walk_forward.py` + `notebooks/08_walk_forward.ipynb`). 100 % coverage on the new
  modules, mypy strict, suite 98 %. Stayed ROADMAP-pure (no `extended_data`/gateway change, no
  FastAPI endpoint, no `live/` wiring). **Deferred → data-gated:** the exit-criteria *magnitudes*
  (positive expectancy after costs, drawdown within budget, regime stability) need the 5-year TFEX
  backfill + engine TFEX data — the harness + a synthetic demonstration ship now.
- **Phase 7 — Risk Engine shipped
  2026-06-04** on `feature/phase-7-risk-engine` (the `risk/` leaf package: position sizing on the
  `S50_MULTIPLIER = 200` constant, daily-loss / streak / trade-count limits as an immutable session
  reducer, no-averaging-down + no-widen-stop guards, regime/volatility scaling reusing `regime/`,
  the kill switch — hard rule #8, env-flag override — and the capital-deployment ladder as a runtime
  guard, plus a pure `decision.evaluate_entry` orchestrator). 100 % coverage on `risk/`, mypy strict,
  suite 97.8 %. Stayed ROADMAP-pure (no `extended_data`/gateway change, no FastAPI endpoint, no
  `live/` wiring, no walk-forward). **Deferred:** the kill-switch **admin endpoint** (needs `api/`)
  and the ladder's **"≥ 6 months live" evidence actuals** (data-gated on Phase 9/10).
- **Phase 6 — ML Probability Filter machinery shipped 2026-06-04** on
  `feature/phase-6-ml-probability-filter` (the `ml/` package: triple-barrier labels, feature
  extraction, walk-forward LightGBM trainer + importance audit, versioned cached store, the
  default-OFF gate wired at `run_per_strategy_backtest(ml_filter=…)`). 100 % coverage on `ml/`, mypy
  strict. Default OFF (`TFEX_S50_MULTI_TF_SWING_ML_FILTER_ENABLED=false`) ⇒ Phase-5 behaviour
  byte-for-byte; **real trained models + the out-of-sample A/B magnitude claim remain data-gated** on
  the 5-year backfill. Phase 5 §5.1–§5.4 + the §5.5 harness shipped 2026-06-03; the §5
  positive-expectancy exit metric is deferred → data-gated. Phase 4 §4.3's counter-trend backtest is
  now unblocked (the `signals/` + `execution/` + `backtest/` layers exist) but remains data-gated.
- **Completed sub-phases:** 0.1–0.5 (2026-05-28); Phase 1 (2026-05-28); Phase 2.1–2.6
  (2026-05-29); Phase 3 §3.1 + §3.4 (2026-05-29); Phase 4 §4.1 + §4.2 (2026-06-03); Phase 5
  §5.1–§5.4 + §5.5 harness (2026-06-03); Phase 6 §6.1–§6.4 machinery, default-OFF (2026-06-04;
  magnitude data-gated); Phase 7 §7.1–§7.5 (2026-06-04; admin endpoint + ladder evidence deferred);
  Phase 8 §8.1–§8.3 machinery (2026-06-04; exit-criteria magnitudes data-gated).
- **Phase 0 plan:** [`phase-0-bootstrap-and-gateway-onboarding.md`](phase-0-bootstrap-and-gateway-onboarding.md).
- **Phase 1 plan:** [`phase-1-data-infrastructure.md`](phase-1-data-infrastructure.md). All five sub-phases shipped on 2026-05-28: tvkit fetcher, back-adjusted continuous via 5d volume-crossover roll, Thai session calendar, validation pipeline + `S501!` cross-check, data-quality notebook. 159 tests, ≥ 94 % coverage on `adapters/` + `data/`, mypy strict clean. TimescaleDB hypertable mirror added via `quant-infra-db` PR #9 (`ohlcv_raw`, `ohlcv_continuous`).
- **Phase 2 plan:** [`phase-2-feature-engineering.md`](phase-2-feature-engineering.md). Shipped 2026-05-29: trend / volatility / time-of-day / market-structure / regime feature groups + the §2.6 pipeline (winsorise + trailing z-score) and a causal multi-timeframe aligner. Polars-native, look-ahead-free. 214 tests, 100 % coverage on every `features/` module (95.6 % combined), mypy strict clean. Owner CLI `scripts/build_features.py`; stability notebook scaffolded (data-gated).
- **Phase 3 plan:** [`phase-3-regime-detection.md`](phase-3-regime-detection.md). §3.1 rule-based classifier + §3.4 regime→strategy policy shipped 2026-05-29; clustering (§3.2) and the LightGBM classifier (§3.3) deferred until a hand-labelled regime dataset exists.
- **Phase 4 plan:** [`phase-4-htf-bias-engine.md`](phase-4-htf-bias-engine.md). §4.1 4H trend filter + §4.2 `BiasSignal` output / visualisation shipped 2026-06-03 as the `bias/` leaf package (conservative-unanimity gates, reuses `regime/` for the volatility-healthy veto, source-agnostic). §4.3 is a demonstration only; the ≥ 30% counter-trend-reduction exit metric is deferred to Phase 5. `4h` stays **mirror-only** until an engine `4h` route lands.
- **Phase 5 plan:** [`phase-5-setup-detection-signals.md`](phase-5-setup-detection-signals.md).
  §5.1–§5.4 (Strategies A/B/C + the 5m execution engine) and the §5.5 per-strategy backtest
  harness shipped 2026-06-03 as the `signals/` + `execution/` + `backtest/` leaf packages
  (gated by the Phase-4 bias veto + Phase-3 regime policy on a causally aligned 5m frame). PnL is
  in points + R; the §5 positive-expectancy magnitude claim and the ML filter (Strategy C) are
  deferred to data/Phase 6/8. Stayed ROADMAP-pure (no `risk/`, no gateway change).
- **Phase 6 plan:** [`phase-6-ml-probability-filter.md`](phase-6-ml-probability-filter.md).
  §6.1–§6.4 machinery shipped 2026-06-04 as the `ml/` leaf package (triple-barrier labels,
  fixed-vector feature extraction, anchored walk-forward LightGBM trainer + importance audit,
  versioned thread-safe-cached store, and the default-OFF gate `ml.filter.filter_signals`
  wired at `run_per_strategy_backtest(ml_filter=…)`). 100 % coverage on `ml/`, mypy strict.
  Default OFF (`TFEX_S50_MULTI_TF_SWING_ML_FILTER_ENABLED`) ⇒ Phase-5 behaviour byte-for-byte;
  real trained models + the OOS A/B magnitude claim are data-gated on the 5-year backfill.
  Stayed ROADMAP-pure (no `risk/`, no API endpoint, no `extended_data`/gateway change).
- **Phase 7 plan:** [`phase-7-risk-engine.md`](phase-7-risk-engine.md).
  §7.1–§7.5 shipped 2026-06-04 as the `risk/` leaf package (sizing on the `S50_MULTIPLIER = 200`
  constant, daily-loss / streak / trade-count limits, no-averaging-down + no-widen-stop guards,
  regime/volatility scaling reusing `regime/`, the kill switch with an env-flag override, the
  capital-deployment ladder runtime guard, and a pure `decision.evaluate_entry` orchestrator).
  100 % coverage on `risk/`, mypy strict; `RiskConfig` surfaced on `Settings`
  (`TFEX_S50_MULTI_TF_SWING_RISK_*` + `risk_config()`). The kill-switch admin endpoint is deferred
  to `api/`; the ladder's live-evidence actuals are data-gated (Phase 9/10). Stayed ROADMAP-pure
  (no `extended_data`/gateway change, no FastAPI endpoint, no `live/` wiring, no walk-forward).
- **Phase 8 plan:** [`phase-8-walk-forward-backtest.md`](phase-8-walk-forward-backtest.md).
  §8.1–§8.3 machinery shipped 2026-06-04 as the `backtest/` extension (anchored walk-forward
  harness driving the Phase-7 risk engine per trade, a configurable cost model, drawdown-profile /
  Sharpe-Sortino / regime-concentration metrics, and public-safe reporting). 100 % coverage on the
  new modules, mypy strict; `WalkForwardConfig` / `CostModel` surfaced on `Settings`
  (`TFEX_S50_MULTI_TF_SWING_WALK_FORWARD_*` / `_COST_*`). The exit-criteria magnitudes are
  data-gated on the 5-year TFEX backfill + engine TFEX data. Stayed ROADMAP-pure.
- **Market-data engine integration:** `feature-market-data-engine` **Phase 4 (reader
  cutover) shipped 2026-06-02** (tfex PR #6, `8756b1a`) — the
  `TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE = mirror | engine` flag + `EngineOhlcvFetcher` +
  engine client + boundary tests. **Default is still `mirror`**; tfex end-to-end verification
  and the default flip to `engine` are **pending Phase 5.x** (no TFEX data in the engine yet).
  See [Market data source](#market-data-source--the-market-data-engine).
- **Blocked by:** nothing for the strategy roadmap. Next: Phase 9 (Paper Trading) runs the
  validated pipeline real-time (would-be orders only) over 60+ trading days across regimes. The
  Phase-8 exit-criteria *magnitudes* remain data-gated on the 5-year TFEX backfill + engine TFEX
  data; the walk-forward harness is ready to produce them the moment that data lands.

---

## Non-goals / Anti-patterns

These are explicit "do not do" rules. They are intentional constraints, not aspirations
postponed to a later phase.

| Anti-pattern | Why it is forbidden |
|---|---|
| Deep Learning from the start | TFEX data volume is small, non-stationary, and prone to overfit. LightGBM / XGBoost / CatBoost are the ceiling for now. |
| Multi-strategy / multi-asset launch | More than one strategy or one instrument before Phase 11 is unmanageable to debug and to attribute PnL. |
| Tick-level / HFT execution | Retail-level latency and infrastructure cost mean we cannot win on speed. We win on selection and survival. |
| Averaging down on losers | Strictly forbidden in futures. A losing trade is a wrong idea, not a discount. |
| Scaling because of confidence | Capital is scaled only on statistical evidence — minimum 6 months of stable live PnL, walk-forward consistency, drawdown within budget. Confidence is not evidence. |
| Random train / test splits | Walk-forward only. Random splits leak future information into past decisions. |
| Trading every regime | Some regimes (`range_low_vol`, lunch dead zone) are explicitly no-trade. The system not trading is a feature, not a bug. |
| Indicator hunting / "secret signal" | Edge comes from regime awareness + cost efficiency + risk management + execution. Not from a magic indicator. |
