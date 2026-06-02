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

- **4H** — regime detection and higher-timeframe bias.
- **1H** — main setup detection (pullback continuation, opening range, sweep reversal).
- **5m** — execution timing and risk optimisation.

Design philosophy: the system is **boring, conservative, and engineered to survive
across regimes** — not optimised for a beautiful backtest. Edge comes from regime
awareness + cost efficiency + risk management + execution quality.

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
│  4H → Regime / Macro Bias                    │
│  1H → Main Setup Detection                   │
│  5m → Execution & Risk Optimisation          │
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
│  - Setup Detection (Strategies A / B / C)    │
│  - Execution Engine (5m)                     │
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
  currently `adapters/`, `data/`, `features/`, and `regime/`. `risk/` joins the list once
  it lands (Phase 7).
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
- **Strategy A/B/C specifications:** `.claude/knowledge/strategy-design.md`
- **Risk engine specification:** `.claude/knowledge/risk-engine.md`
- **ML filter design:** `.claude/knowledge/ml-filter.md`
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
