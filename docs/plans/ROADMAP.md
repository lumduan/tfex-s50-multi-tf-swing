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
> Data Engine has no `4h` route yet (`cagg_ohlcv_4h` unrouted; no local rollup, D10). Until
> the engine exposes a `4h` route, `4h` is available **only on the `mirror` source**. This is
> the one place tfex's roadmap is blocked from running fully on the canonical engine source —
> the unblocker is the engine `4h` route follow-up (then a one-line enablement in
> `data/engine_fetcher.py:_TF_TO_ENGINE`). See
> [Market data source](#market-data-source--the-market-data-engine).

### 4.1 4H Trend Filter

- [ ] `src/tfex_s50_multi_tf_swing/bias/htf.py`
  - [ ] `ema20_above_ema50` (Long) / `ema20_below_ema50` (Short)
  - [ ] Positive vs negative EMA slope
  - [ ] HH/HL structure check
  - [ ] Price relative to HTF VWAP
  - [ ] Volatility-healthy gate (not in `panic`, not in `range_low_vol`)

### 4.2 Bias Output

- [ ] `BiasSignal` Pydantic model: `direction: Literal["long", "short", "neutral"]`,
  `reasons: list[str]`
- [ ] CLI/notebook to visualise bias overlaid on 4H chart

### 4.3 Backtest of Bias Filter

- [ ] Compare baseline naive strategy with/without bias filter on the same period
- [ ] Confirm bias filter improves expectancy or reduces drawdown

**Exit criteria:** bias signal materialised per 4H bar; histogram of trades shows
≥ 30% reduction in counter-trend entries vs the unfiltered baseline.

---

## Phase 5 — Setup Detection & Signal Strategies

> Goal: three trading strategies — A (primary), B and C — each gated by HTF bias
> and regime policy, each backtested independently before combination.

### 5.1 Strategy A — Pullback Continuation ⭐ (primary)

- [ ] `src/tfex_s50_multi_tf_swing/signals/strategy_a.py`
  - [ ] 4H confirms uptrend (EMA20 > EMA50, positive slope, HH/HL)
  - [ ] 1H pullback to EMA20, structure intact, volume contracting, ATR contracting
  - [ ] 5m volatility compression detected, awaiting re-expansion
  - [ ] 5m entry on compression breakout + VWAP reclaim + volume expansion
- [ ] Unit tests on hand-crafted scenarios for entry, no-entry, false-trigger

### 5.2 Strategy B — Opening Range Breakout

- [ ] `src/tfex_s50_multi_tf_swing/signals/strategy_b.py`
  - [ ] Opening range computed in first 15m (configurable)
  - [ ] Breakout with volume expansion confirms entry
  - [ ] HTF-aligned and not in `range_low_vol` regime
  - [ ] Suppressed during lunch zone

### 5.3 Strategy C — Liquidity Sweep Reversal

- [ ] `src/tfex_s50_multi_tf_swing/signals/strategy_c.py`
  - [ ] Detect high/low sweep (stop-run pattern)
  - [ ] Confirm reversal candle + structure shift
  - [ ] Optional ML probability check (Phase 6) to filter fake breakouts

### 5.4 Execution Engine (5m)

- [ ] `src/tfex_s50_multi_tf_swing/execution/engine.py`
  - [ ] Entry: breakout candle close + volume confirm + spread acceptable
  - [ ] Stop loss: structure-aware *and* volatility-aware (`SL = entry − k·ATR`,
    anchored to nearest invalidation level)
  - [ ] Take profit: hybrid policy — partial TP at 1R (50%), trail remainder on
    structure (`EMA20` or swing-low/high)
  - [ ] Move stop to breakeven on +1R (configurable buffer to avoid noise stop-outs)
  - [ ] Time stop: exit if no progress within `N` bars
- [ ] Unit tests on simulated bar sequences

### 5.5 Per-Strategy Backtest

- [ ] Backtest each strategy independently before any composite is built
- [ ] Report expectancy, profit factor, max drawdown, regime-stratified PnL

**Exit criteria:** each strategy reaches positive expectancy after costs on the
training period and is stable across at least two distinct regimes.

---

## Phase 6 — ML Probability Filter

> Goal: use ML as a **filter**, not a strategy. The model produces probabilities
> that gate existing rule-based signals; it does not generate trades.

### 6.1 Labelled Dataset

- [ ] `src/tfex_s50_multi_tf_swing/ml/labels.py`
  - [ ] Triple-barrier labelling (TP / SL / time)
  - [ ] Per-setup labels for `trend_continuation` and `fake_breakout`
  - [ ] Saved to `data/labels/` keyed by `(setup_id, label_type)`

### 6.2 LightGBM Models

- [ ] `src/tfex_s50_multi_tf_swing/ml/models.py`
  - [ ] `P(trend_continuation)` — gates Strategy A & B
  - [ ] `P(fake_breakout)` — gates Strategy C
  - [ ] Walk-forward training schedule, no random splits
- [ ] Feature importance audit; no single feature dominating

### 6.3 Filter Integration

- [ ] Threshold per model documented (e.g., `P(continuation) > 0.55`)
- [ ] A/B compare strategies with vs without ML filter

### 6.4 Anti-Overfit Discipline

- [ ] Walk-forward only — never random split
- [ ] Out-of-sample metrics required to ship
- [ ] No Deep Learning at this stage (see Non-goals)

**Exit criteria:** ML-filtered strategies improve out-of-sample expectancy or
profit factor vs unfiltered; no regime sees a worse performance with the filter on.

---

## Phase 7 — Risk Engine

> Goal: survive every regime. Risk Engine is more important than any signal.

### 7.1 Position Sizing

- [ ] `src/tfex_s50_multi_tf_swing/risk/sizing.py`
  - [ ] `position_size = account_risk / (stop_distance × multiplier)`
  - [ ] S50 multiplier: 200 THB per point
  - [ ] Default `account_risk = 1%` of equity
  - [ ] Volatility scaling: wider stop ⇒ smaller position
- [ ] Unit tests against the worked example
  (100k equity, 1% risk, 5-pt stop ⇒ 1 contract)

### 7.2 Daily & Streak Limits

- [ ] `src/tfex_s50_multi_tf_swing/risk/limits.py`
  - [ ] Daily loss limit: `-2R` → stop trading today
  - [ ] Consecutive loss limit: 3 in a row → pause until next session
  - [ ] Daily trade-count cap (configurable)

### 7.3 Volatility Scaling

- [ ] Scale size down when realised volatility breaches a high percentile
- [ ] Optional no-trade gate at extreme percentile (panic regime)

### 7.4 Kill Switch

- [ ] Abnormal spread / latency / market-halt detection → flatten all positions
- [ ] Manual kill switch via env var or admin endpoint

### 7.5 Capital Deployment Ladder

| Phase | Size | Condition |
| --- | --- | --- |
| Paper | 0 | Validate logic only |
| Micro Live | 1 contract | Strategy passed paper |
| Validated | 2 contracts | Statistical evidence (≥ 6 months live) |
| Scale | Scale carefully | Stable for 6+ months in production |

**Exit criteria:** risk engine unit-tested across boundary cases, kill switch
verified in a fault-injection test, capital-ladder rules encoded as runtime guards.

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

- [ ] `src/tfex_s50_multi_tf_swing/backtest/walk_forward.py`
  - [ ] Anchored windows, e.g.: train 2016–2021 / test 2022; train 2017–2022 / test 2023
  - [ ] Re-fit ML models per window
  - [ ] Configurable cost model
- [ ] Cost simulation:
  - [ ] Commission: per-contract fee + clearing fee
  - [ ] Slippage: ATR-scaled (and worse on illiquid sessions)
  - [ ] Spread: tick-based

### 8.2 Metrics

- [ ] `src/tfex_s50_multi_tf_swing/backtest/metrics.py`
  - [ ] Expectancy (avg R per trade)
  - [ ] Max drawdown (peak-to-trough, time underwater)
  - [ ] Profit factor (gross-up / gross-down)
  - [ ] Regime-stratified metrics (per regime: expectancy, win rate)
  - [ ] Sharpe / Sortino (per period)

### 8.3 Reporting

- [ ] `notebooks/08_walk_forward.ipynb`
  - [ ] Equity curve per window, concatenated
  - [ ] Drawdown chart with regime overlay
  - [ ] Per-strategy and combined results
  - [ ] Sensitivity sweep on key thresholds (ATR multiplier, ML thresholds)

**Exit criteria:** positive expectancy after costs across all walk-forward windows,
max drawdown within budget, regime stability evidenced.

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

- **Active phase:** Phase 4 — Higher-Timeframe Bias Engine (Phase 3 §3.1/§3.4 shipped on
  `feature/phase-3-regime-detection`, 2026-05-29; §3.2/§3.3 deferred pending a hand-labelled
  regime dataset).
- **Completed sub-phases:** 0.1–0.5 (2026-05-28); Phase 1 (2026-05-28); Phase 2.1–2.6
  (2026-05-29); Phase 3 §3.1 + §3.4 (2026-05-29).
- **Market-data engine integration:** `feature-market-data-engine` **Phase 4 (reader
  cutover) shipped 2026-06-02** (tfex PR #6, `8756b1a`) — the
  `TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE = mirror | engine` flag + `EngineOhlcvFetcher` +
  engine client + boundary tests. **Default is still `mirror`**; tfex end-to-end verification
  and the default flip to `engine` are **pending Phase 5.x** (no TFEX data in the engine yet).
  See [Market data source](#market-data-source--the-market-data-engine).
- **Phase 0 plan:** [`phase-0-bootstrap-and-gateway-onboarding.md`](phase-0-bootstrap-and-gateway-onboarding.md).
- **Phase 1 plan:** [`phase-1-data-infrastructure.md`](phase-1-data-infrastructure.md). All five sub-phases shipped on 2026-05-28: tvkit fetcher, back-adjusted continuous via 5d volume-crossover roll, Thai session calendar, validation pipeline + `S501!` cross-check, data-quality notebook. 159 tests, ≥ 94 % coverage on `adapters/` + `data/`, mypy strict clean. TimescaleDB hypertable mirror added via `quant-infra-db` PR #9 (`ohlcv_raw`, `ohlcv_continuous`).
- **Phase 2 plan:** [`phase-2-feature-engineering.md`](phase-2-feature-engineering.md). Shipped 2026-05-29: trend / volatility / time-of-day / market-structure / regime feature groups + the §2.6 pipeline (winsorise + trailing z-score) and a causal multi-timeframe aligner. Polars-native, look-ahead-free. 214 tests, 100 % coverage on every `features/` module (95.6 % combined), mypy strict clean. Owner CLI `scripts/build_features.py`; stability notebook scaffolded (data-gated).
- **Phase 3 plan:** [`phase-3-regime-detection.md`](phase-3-regime-detection.md). §3.1
  rule-based classifier + §3.4 regime→strategy policy shipped 2026-05-29; clustering (§3.2)
  and the LightGBM classifier (§3.3) deferred until a hand-labelled regime dataset exists.
- **Blocked by:** nothing for the strategy roadmap. Next: Phase 4 (HTF Bias Engine) — note
  its `4h` data needs the `mirror` source until an engine `4h` route lands (see Phase 4).
  The engine-source default flip is the only market-data item, pending Phase 5.x verification.

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
