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
uv run python scripts/fetch_history.py    # pull OHLCV (4H/1H/5m) → data/raw
uv run python scripts/build_continuous.py # back-adjusted continuous contract → data/continuous
uv run python scripts/refresh_daily.py    # end-of-day pipeline → gateway daily report
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
- **No SQLite/Postgres in `src/tfex_s50_multi_tf_swing/` core** — the Postgres / Mongo
  dependency lives entirely in `src/tfex_s50_multi_tf_swing/adapters/` and is opt-in
  via `TFEX_S50_MULTI_TF_SWING_DB_WRITE_ENABLED`.
- Postgres DBs when write-back is on:
  - `db_tfex_s50_multi_tf_swing`: `equity_curve` (TimescaleDB hypertable),
    `trade_history` (with `side`, `contracts`, `margin_used`), `backtest_log`,
    `benchmark_equity_curve` (S50 underlying / SET50 TR).
  - `db_gateway`: written **only via HTTP** to `quant-api-gateway`. The strategy
    does not connect directly to `db_gateway`.

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
- Coverage target ≥ 90% on `src/tfex_s50_multi_tf_swing/adapters/` and
  `src/tfex_s50_multi_tf_swing/risk/` (enforced via `--cov-fail-under=90` once those
  modules exist).
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
- **Umbrella system map:** `../../CLAUDE.md`
- **Strategy onboarding contract:** `../../STRATEGY_ONBOARDING.md`
- **Template repo (for code conventions):** `../csm-set/`
