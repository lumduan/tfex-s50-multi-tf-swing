# Phase 0 — Project Bootstrap & Gateway Onboarding

**Strategy:** `tfex-s50-multi-tf-swing` (first implementation of `feature-tfex-integration`)
**Branch:** `feat/phase-0-bootstrap-gateway-onboarding`
**Created:** 2026-05-28
**Status:** In progress
**Depends On:** Sub-phases 0.1 (repo skeleton) and 0.2 (roadmap + agent context) complete as of 2026-05-27

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Design Decisions](#design-decisions)
5. [Implementation Steps](#implementation-steps)
6. [File Changes](#file-changes)
7. [Success Criteria](#success-criteria)
8. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 0 produces a callable, gateway-registered, Docker-runnable headless service for the
TFEX S50 multi-timeframe swing strategy. After this phase, the umbrella `quant-api-gateway`
lists the new strategy in its registry, `quant-infra-db` has provisioned
`db_tfex_s50_multi_tf_swing` with the four required tables, and the strategy container
exposes `/health` on host port `:8200` and can POST an idempotent daily report — all
without any signal, data-fetch, or trading code, which lands in Phase 1+.

This phase touches **four repos** in coordinated PRs:

| Repo | Branch | Purpose |
| --- | --- | --- |
| `quant-infra-db` | `feat/register-tfex-s50-multi-tf-swing` | Add `init-scripts/08_schema_db_tfex_s50_multi_tf_swing.sql` |
| `quant-api-gateway` | `feat/register-tfex-s50-multi-tf-swing` | Append TFEX entry to `strategies.json` (active: false) |
| `tfex-s50-multi-tf-swing` | `feat/phase-0-bootstrap-gateway-onboarding` | This repo — tooling, adapters, Docker |
| `quant-trading-system` (umbrella) | `docs/tfex-s50-phase-0-onboarding` | "Phase 0 complete" knowledge note |

### Parent Plan Reference

- `docs/plans/ROADMAP.md` — Phase 0 (sub-phases 0.1, 0.3, 0.4, 0.5; 0.2 already complete).
- Umbrella feature: `../../../plans/feature-tfex-integration/ROADMAP.md` (read-only from this repo).

### Key Deliverables

1. **`pyproject.toml`** — personalised name, package mapping, runtime + dev deps, ruff/mypy/pytest blocks (mirroring csm-set conventions).
2. **`src/tfex_s50_multi_tf_swing/`** — proper package namespace; template `src/main.py` removed.
3. **`src/tfex_s50_multi_tf_swing/config/settings.py`** — `pydantic-settings` config with `env_prefix="TFEX_S50_MULTI_TF_SWING_"`.
4. **`src/tfex_s50_multi_tf_swing/adapters/`** — `errors.py`, `payload.py` (Pydantic), `gateway_client.py` (httpx + manual retry/backoff), `hooks.py` (no-op when `db_write_enabled=False`).
5. **`api/main.py`** — minimal FastAPI app exposing `GET /health`.
6. **`Dockerfile`** + `docker-compose.yml` + `docker-compose.private.yml` — multi-stage uv build, non-root, host port `:8200`, joins external `quant-network`.
7. **`tests/unit/adapters/*`** — payload / gateway-client / hooks unit tests at ≥ 90% coverage on `adapters/`.
8. **`init-scripts/08_schema_db_tfex_s50_multi_tf_swing.sql`** in `quant-infra-db` — DB + four tables (`equity_curve`, `trade_history`, `backtest_log`, `benchmark_equity_curve`) using `NUMERIC(18,4)` for money.
9. **`strategies.json`** entry in `quant-api-gateway` — `active: false` until paper trading lands.

---

## AI Prompt

The following prompt was used to generate this phase:

```
You are implementing Phase 0 — Project Bootstrap & Gateway Onboarding for the
`tfex-s50-multi-tf-swing` strategy inside the `quant-trading-system` umbrella.

Working root: quant-trading-system

==========================================================================
STEP 0 — READ FIRST (do NOT skip; do NOT skim)
==========================================================================
Read these in order and hold them in working memory:

  1. CLAUDE.md                                                # umbrella system map
  2. STRATEGY_ONBOARDING.md                                   # contract + naming rules
  3. quant-api-gateway/CLAUDE.md                              # ingest contract details
  4. quant-infra-db/CLAUDE.md                                 # init-scripts conventions
  5. strategies/csm-set/CLAUDE.md                             # reference implementation
  6. strategies/csm-set/src/csm/adapters/                     # reference adapter code
  7. strategies/csm-set/docker-compose.yml + .private.yml + Dockerfile
  8. strategies/csm-set/docs/plans/examples/phase1-sample.md  # plan-doc format
  9. strategies/tfex-s50-multi-tf-swing/CLAUDE.md             # TFEX-specific hard rules
 10. strategies/tfex-s50-multi-tf-swing/docs/plans/ROADMAP.md # FOCUS on Phase 0 (lines 20-84)
 11. strategies/tfex-s50-multi-tf-swing/.claude/playbooks/onboarding-to-gateway.md
 12. quant-api-gateway/strategies.json                        # current registry
 13. quant-infra-db/init-scripts/03_schema_csm_set.sql        # schema template

Treat the ROADMAP Phase 0 checkboxes (0.1, 0.3, 0.4, 0.5; 0.2 is already
complete) as the authoritative scope. Do NOT expand into Phase 1+ work.

==========================================================================
STEP 1 — PLAN BEFORE CODE
==========================================================================
Create exactly one file:

  strategies/tfex-s50-multi-tf-swing/docs/plans/phase-0-bootstrap-and-gateway-onboarding.md

Mirror the structure of strategies/csm-set/docs/plans/examples/phase1-sample.md
exactly: Overview, AI Prompt (paste THIS prompt verbatim inside a fenced
block), Scope (in/out), Design Decisions, Implementation Steps,
File Changes (table covering ALL three sub-repos + umbrella), Success
Criteria (checkbox list), Completion Notes (filled in at the end).

Commit this plan file FIRST, on the strategy branch, before any other code.

==========================================================================
STEP 2 — BRANCHES (one per repo; do not work on main)
==========================================================================
  strategies/tfex-s50-multi-tf-swing/   git checkout -b feat/phase-0-bootstrap-gateway-onboarding
  quant-api-gateway/                    git checkout -b feat/register-tfex-s50-multi-tf-swing
  quant-infra-db/                       git checkout -b feat/register-tfex-s50-multi-tf-swing
  (umbrella, last)                      git checkout -b docs/tfex-s50-phase-0-onboarding

==========================================================================
STEP 3 — IMPLEMENT (in this order)
==========================================================================
A) Sub-phase 0.1 — Tooling (strategy repo)
   - pyproject.toml: name = "tfex-s50-multi-tf-swing", description, packages
     under src/tfex_s50_multi_tf_swing/, ruff + mypy strict + pytest config
     copied/adapted from csm-set.
   - Move existing src/* into src/tfex_s50_multi_tf_swing/ (create __init__.py).
   - .env.example with TFEX_S50_MULTI_TF_SWING_* keys (PUBLIC_MODE,
     DB_WRITE_ENABLED, GATEWAY_BASE_URL, GATEWAY_API_KEY, PG_DSN).
   - .pre-commit-config.yaml wiring ruff check, ruff format, mypy.
   - Run and prove clean:
       uv sync --all-groups
       uv run ruff check . && uv run ruff format --check . \
         && uv run mypy src tests && uv run pytest

B) Sub-phase 0.3 — Gateway + DB registration
   - quant-api-gateway/strategies.json: append exactly:
       {
         "id": "tfex-s50-multi-tf-swing",
         "name": "TFEX S50 Multi-Timeframe Swing",
         "type": "TFEX_DERIVATIVES",
         "service_url": "http://quant-tfex-s50-multi-tf-swing:8000",
         "capital_weight": 1.0,
         "active": false
       }
     Preserve csm-set entry; valid JSON; trailing newline.
   - quant-infra-db/init-scripts/08_schema_db_tfex_s50_multi_tf_swing.sql:
     CREATE DATABASE db_tfex_s50_multi_tf_swing; \connect; then create
     equity_curve (TimescaleDB hypertable on time TIMESTAMPTZ),
     trade_history (includes side, contracts INT, margin_used NUMERIC(18,4)),
     backtest_log, benchmark_equity_curve. NUMERIC(18,4) for money, fractional
     NUMERIC(8,4) for percentages, UNIQUE on natural keys so ingest is
     idempotent. Mirror 03_schema_csm_set.sql conventions exactly.
   - Reserve host port :8200 (document in plan + tfex CLAUDE.md if missing).

C) Sub-phase 0.4 — Adapter scaffolding (strategy repo)
   Under src/tfex_s50_multi_tf_swing/adapters/:
   - errors.py: TfexS50Error base + AdapterError + GatewayClientError.
   - payload.py: Pydantic models for the POST /api/v1/ingest/daily-report
     payload (strategy_metadata, performance_metrics, current_exposure,
     extended_data). Monetary fields typed Decimal and serialized as
     strings. Timestamps tz-aware UTC. extended_data.report.margin_usage
     MUST be present (TFEX hard rule).
   - gateway_client.py: async httpx.AsyncClient wrapper. 5s default timeout.
     Sends X-API-Key. Retries 5xx + transient network errors with exponential
     backoff (tenacity is fine). POSTing same payload twice must be safe.
   - hooks.py: async def run_post_refresh_hook(...). No-op when
     TFEX_S50_MULTI_TF_SWING_DB_WRITE_ENABLED is false. Structured logging
     using % formatting via logger = logging.getLogger(__name__).
   - tests/unit/adapters/ to ≥90% coverage on these four modules. Use respx
     to fake httpx in client tests. Cover: payload Decimal-as-string
     serialization, reject float; client retry/backoff, auth header,
     idempotency, error mapping; hook no-op path.

D) Sub-phase 0.5 — Docker (strategy repo)
   - Dockerfile: ARG TFEX_S50_MULTI_TF_SWING_PUBLIC_MODE=true, multi-stage
     uv build, non-root user, HEALTHCHECK hitting /health.
   - docker-compose.yml: container_name: quant-tfex-s50-multi-tf-swing,
     ports: "8200:8000", networks: [quant-network] with external: true.
     No secrets baked in.
   - docker-compose.private.yml: env_file: .env, writable volumes for data/.
   - Provide a minimal /health endpoint returning {"status": "ok"} ONLY if
     no API entrypoint exists yet. Do not build out a full API surface.

==========================================================================
STEP 4 — VERIFY END-TO-END
==========================================================================
From the umbrella root, in this order:
  cd quant-infra-db        && docker compose up -d
  cd ../quant-api-gateway  && docker compose up -d
  cd ../strategies/tfex-s50-multi-tf-swing && docker compose up -d

Capture exit code + body for each, paste into Completion Notes (date 2026-05-28):
  curl -s -o - -w "\n%{http_code}\n" http://localhost:8200/health
  curl -s -o - -w "\n%{http_code}\n" http://localhost:8000/api/v2/engines/catalog
  # Build a minimal valid daily-report payload (zero PnL, no positions,
  # margin_usage="0.00", UTC tz-aware timestamp) and POST twice:
  curl -s -o - -w "\n%{http_code}\n" -X POST \
       http://localhost:8000/api/v1/ingest/daily-report \
       -H "X-API-Key: $INTERNAL_API_KEY" \
       -H "Content-Type: application/json" \
       -d @/tmp/tfex_min_payload.json
  # repeat the same POST; expect idempotent 202/200, no duplicate row.

==========================================================================
STEP 5 — DOCS / MEMORY / KNOWLEDGE
==========================================================================
Only after Step 4 is green:

- Tick the ROADMAP boxes for 0.1, 0.3, 0.4, 0.5 in
  strategies/tfex-s50-multi-tf-swing/docs/plans/ROADMAP.md and update the
  "Current Status" block (completion date 2026-05-28; note any blockers).
- Update strategies/tfex-s50-multi-tf-swing/README.md and CLAUDE.md only
  where new files / :8200 reservation / gateway registration change observable
  behaviour. Do not add aspirational text.
- Update umbrella .claude/knowledge/feature-tfex-integration.md: add a
  "Phase 0 complete (2026-05-28)" note linking the four PRs.
- Append the phase plan to the strategy-onboarding playbook only if a real,
  reusable insight emerged ("Verified 2026-05-28" check-mark, not narrative).
- Memory: if a non-obvious convention worth remembering across sessions
  surfaced (e.g. host-port allocation scheme, mandatory margin_usage field,
  the public/private docker overlay layout), add or update a single-purpose
  memory file under
  /home/batt/.claude/projects/-home-batt-docker-quant-trading-system/memory/
  and add one ≤150-char line to MEMORY.md. Do NOT save ephemeral state.

==========================================================================
STEP 6 — COMMIT + PR (per repo, Conventional Commits)
==========================================================================
  infra-db   -> feat: add tfex-s50-multi-tf-swing schema
  gateway    -> feat: register tfex-s50-multi-tf-swing strategy
  strategy   -> feat: phase 0 bootstrap & gateway onboarding
  umbrella   -> docs: tfex-s50-multi-tf-swing phase 0 complete

Each PR body must:
  - link the other PRs in the set,
  - state merge order: infra-db -> gateway -> strategy -> umbrella docs,
  - include the curl verification output captured in Step 4.

Return all four PR URLs at the end.

==========================================================================
HARD CONSTRAINTS (violation = revert)
==========================================================================
- Always `uv run`; never bare python/pip/poetry/conda.
- `from __future__ import annotations` on every src/ module.
- Pydantic at all boundaries; Decimal-as-string for money on the wire.
- httpx.AsyncClient only; no `requests`.
- Tz-aware UTC timestamps; never tz-naive.
- No secrets committed; no edits to .gitignore to hide files.
- Do NOT flip `active: true` in strategies.json (stays false until paper
  trading is verified in a later phase).
- Do NOT touch Phase 1+ scope: no data fetchers, no signals, no continuous
  contract code, no scheduler, no broker integration.
- Do NOT modify the umbrella main branch directly; use the docs branch.
- Do NOT operate inside any sub-repo from the umbrella; cd into the sub-repo
  for git operations so each commit lands in the correct remote.
- If a quality gate fails, fix the root cause; never --no-verify, never
  weaken types, never lower coverage targets.

Begin with Step 0. Confirm understanding to yourself, then write the plan
file, then proceed.
```

---

## Scope

### In Scope (Phase 0)

| Component | Description | Sub-phase |
| --- | --- | --- |
| `pyproject.toml` | Personalised project metadata, deps, ruff/mypy/pytest config | 0.1 |
| `src/tfex_s50_multi_tf_swing/` package | New namespace; template `src/main.py` removed | 0.1 |
| `.env.example` | `TFEX_S50_MULTI_TF_SWING_*` keys | 0.1 |
| `.pre-commit-config.yaml` | ruff + mypy hooks | 0.1 |
| `init-scripts/08_…sql` (infra-db) | DB + 4 tables, NUMERIC(18,4) | 0.3 |
| `strategies.json` (gateway) | TFEX entry, `active: false` | 0.3 |
| Host port `:8200` reservation | Documented (already in umbrella + tfex CLAUDE.md) | 0.3 |
| `config/settings.py` (pydantic-settings) | Env-var loader | 0.4 |
| `adapters/errors.py` | `TfexS50Error` → `AdapterError` → `GatewayClientError` | 0.4 |
| `adapters/payload.py` | Pydantic models for ingest payload | 0.4 |
| `adapters/gateway_client.py` | httpx async + manual retry loop | 0.4 |
| `adapters/hooks.py` | `run_post_refresh_hook` (no-op when `db_write_enabled=False`) | 0.4 |
| `tests/unit/adapters/*` | ≥ 90% coverage on adapters | 0.4 |
| `api/main.py` | Minimal FastAPI with `/health` | 0.5 |
| `Dockerfile` | Multi-stage uv, non-root, HEALTHCHECK | 0.5 |
| `docker-compose.yml` + `.private.yml` | Public-default + owner overlay, port 8200, `quant-network` | 0.5 |

### Out of Scope (Phase 1+)

- Any data-fetcher, continuous-contract, feature-engineering, regime, signal, risk, backtest, paper, or live-broker code (Phase 1–10 in ROADMAP).
- Flipping `active: true` in `strategies.json` (gated on Phase 10 paper validation).
- Building out non-`/health` API endpoints (e.g. `/api/v1/signals`, `/api/v1/portfolio`).
- Migrating csm-set's `DOUBLE PRECISION` columns to `NUMERIC` (separate PR if needed).
- TFEX-specific gateway/dashboard adapters in the dashboard / OpenBB extension (separate feature work).

---

## Design Decisions

### 1. Manual retry loop in `gateway_client.py`, not tenacity

The original AI prompt allowed tenacity. Inspecting `strategies/csm-set/src/csm/adapters/gateway_client.py`
shows csm-set uses a **manual `for attempt in range(max_attempts)` loop with `asyncio.sleep(backoff[i])`**.
Mirroring that pattern keeps both strategy adapters operationally identical (same retry semantics,
same log lines, no extra dep) and removes a runtime dependency. tenacity is dropped from runtime
deps. Adapter behaviour: 2xx → success; 4xx → terminal `GatewayClientError`; 5xx + `httpx.HTTPError` →
retry up to `max_attempts` with backoff sequence `(1.0, 2.0, 4.0)`.

### 2. Pydantic models on the wire, but dict on POST

Per the AI prompt's explicit "Pydantic models for the POST" requirement (stronger than csm-set's
plain-dict builder), `payload.py` defines `StrategyMetadata`, `EquityPoint`, `PerformanceMetrics`,
`CurrentExposure`, `ExtendedDataReport`, `StrategyPayload` mirroring `quant-api-gateway/src/schemas/strategy.py`.
Money fields are `Decimal(max_digits=18, decimal_places=4)`; percentage fields
`Decimal(max_digits=8, decimal_places=4)`. `last_updated` validated UTC. `model_dump(mode="json")` is
used at POST time so Decimals serialise as strings (lossless on the gateway's `Decimal` re-parse).

### 3. NUMERIC, not DOUBLE PRECISION, in the new schema

`03_schema_csm_set.sql` uses `DOUBLE PRECISION`; the new TFEX schema uses `NUMERIC(18, 4)` for money
and `NUMERIC(8, 4)` for percentages/ratios. This is mandated by:
- the AI prompt verbatim,
- TFEX `CLAUDE.md` hard rule #2 ("Floats are forbidden across the gateway boundary"),
- the umbrella rule ("Monetary values are `Decimal` at the gateway boundary; never `float`").
A header comment in the new SQL file flags the divergence. Backfilling `db_csm_set` is out of scope.

### 4. `active: false` in `strategies.json`

Per HARD CONSTRAINTS — flipping to `true` is gated on Phase 10 paper-trading validation. While
`active: false` the gateway's portfolio aggregator won't include this strategy in `weighted_return`
or auto-emit `portfolio_snapshot` rows for it. The catalog/registry endpoints still list the entry.

### 5. No gateway code change for `TFEX_DERIVATIVES`

Confirmed by reading `quant-api-gateway/src/schemas/registry.py` and `strategy.py`: `StrategyConfig.type`
and `StrategyMetadata.type` are both free-form `str` (not enums). Adding `"type": "TFEX_DERIVATIVES"`
is a pure JSON registry edit.

### 6. Init-script applied via `docker exec`, not `down -v`

`quant-postgres` is already running with live csm-set + gateway data. Postgres init-scripts only auto-apply
on first volume init. After the infra-db PR merges, the schema is applied once via:
```
docker exec -i quant-postgres psql -U postgres -f /docker-entrypoint-initdb.d/08_schema_db_tfex_s50_multi_tf_swing.sql
```
The init-scripts directory is bind-mounted; the new file is visible inside the container without a rebuild.
All statements are idempotent: `CREATE DATABASE` via `\gexec`, `CREATE TABLE IF NOT EXISTS`,
`SELECT create_hypertable(..., if_not_exists => TRUE)`.

### 7. API entrypoint at repo-root `api/`, not under `src/`

Mirrors csm-set's `api/main.py` layout and the TFEX `CLAUDE.md` one-way rule (`src/ → api/`). Phase 0
only ships `GET /health`; richer endpoints land in later phases when there's actual state to expose.

### 8. INTERNAL_API_KEY sourced from `quant-api-gateway/.env` for verification

Read at runtime via `grep -E '^INTERNAL_API_KEY=' quant-api-gateway/.env | cut -d= -f2-`. Never
copied into commits or PR bodies. Only HTTP status codes + non-secret response bodies are pasted into
Completion Notes.

---

## Implementation Steps

Branch protocol: `cd` into each sub-repo for git operations so each commit lands on the correct
remote. Never operate on a sub-repo from the umbrella.

### Step A — Strategy repo, sub-phase 0.1 (tooling)
1. Branch `feat/phase-0-bootstrap-gateway-onboarding`.
2. Write this plan file as the **first** commit.
3. Personalise `pyproject.toml`: name `tfex-s50-multi-tf-swing`, package mapping
   `packages = ["src/tfex_s50_multi_tf_swing"]`, runtime deps (`httpx`, `pydantic>=2`,
   `pydantic-settings`, `fastapi`, `uvicorn[standard]`), dev deps (`respx`, `pytest-cov`,
   `pytest-asyncio`, `pre-commit`), ruff/mypy/pytest blocks mirroring csm-set, coverage
   config scoped to `src/tfex_s50_multi_tf_swing/adapters` with `fail_under = 90`.
4. Create `src/tfex_s50_multi_tf_swing/__init__.py`; delete unscoped `src/__init__.py` and
   `src/main.py` (template noise).
5. Write `.env.example`.
6. Write `.pre-commit-config.yaml` (ruff + mypy).
7. Quality gate green: `uv sync --all-groups && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest`.

### Step B — infra-db, sub-phase 0.3 (schema)
1. Branch `feat/register-tfex-s50-multi-tf-swing` in `quant-infra-db`.
2. Write `init-scripts/08_schema_db_tfex_s50_multi_tf_swing.sql`:
   - Idempotent `CREATE DATABASE db_tfex_s50_multi_tf_swing` via `\gexec`.
   - `\connect db_tfex_s50_multi_tf_swing`, `CREATE EXTENSION IF NOT EXISTS timescaledb`.
   - `equity_curve(time TIMESTAMPTZ, strategy_id TEXT, value NUMERIC(18,4))` → hypertable + UNIQUE.
   - `trade_history(id SERIAL PK, time TIMESTAMPTZ, strategy_id TEXT, symbol TEXT, side TEXT CHECK IN ('BUY','SELL'), contracts INTEGER, price NUMERIC(18,4), margin_used NUMERIC(18,4), commission NUMERIC(18,4) DEFAULT 0, pnl NUMERIC(18,4))` → UNIQUE (strategy_id, time, symbol, side).
   - `backtest_log(id SERIAL PK, run_id TEXT UNIQUE, strategy_id, started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ, config JSONB, summary JSONB)`.
   - `benchmark_equity_curve(time TIMESTAMPTZ, benchmark TEXT, value NUMERIC(18,4))` → hypertable + UNIQUE.
3. Quality gate (Python repo): `uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest`.

### Step C — Gateway, sub-phase 0.3 (registry)
1. Branch `feat/register-tfex-s50-multi-tf-swing` in `quant-api-gateway`.
2. Edit `strategies.json` to append the TFEX entry (preserve csm-set; valid JSON; trailing newline).
3. Optionally extend the registry test to assert the new entry parses through `StrategyRegistry.model_validate`.
4. Quality gate green.

### Step D — Strategy repo, sub-phase 0.4 (adapters)
On the same branch as Step A:
1. Create `src/tfex_s50_multi_tf_swing/config/{__init__.py,settings.py}` (pydantic-settings).
2. Create `src/tfex_s50_multi_tf_swing/adapters/{__init__.py,errors.py,payload.py,gateway_client.py,hooks.py}`.
3. Write `tests/unit/adapters/{test_payload.py,test_gateway_client.py,test_hooks.py}` covering:
   - payload Decimal-as-string serialization, UTC enforcement, margin_usage presence, float rejection,
   - gateway client X-API-Key header, 2xx success, 4xx terminal, 5xx retry to exhaustion, transport-error retry, idempotent repeat-POST,
   - hooks no-op when `db_write_enabled=False`; happy-path mocks `GatewayClient`.
4. Coverage on `src/tfex_s50_multi_tf_swing/adapters/` ≥ 90%.

### Step E — Strategy repo, sub-phase 0.5 (Docker)
On the same branch:
1. `api/__init__.py` + `api/main.py` (FastAPI + `/health`).
2. Rewrite `Dockerfile` (multi-stage uv, non-root, `ARG TFEX_S50_MULTI_TF_SWING_PUBLIC_MODE=true`, HEALTHCHECK, `uvicorn api.main:app` CMD).
3. `docker-compose.yml` (public defaults, `:8200`, external `quant-network`).
4. `docker-compose.private.yml` (env_file overlay, writable volumes).

### Step F — End-to-end verification
1. Apply schema 08 via `docker exec -i quant-postgres psql -U postgres -f /docker-entrypoint-initdb.d/08_schema_db_tfex_s50_multi_tf_swing.sql`.
2. `docker compose up -d --build` in strategy repo.
3. Source `INTERNAL_API_KEY` from gateway `.env`.
4. Build minimal payload at `/tmp/tfex_min_payload.json` (zero PnL, single equity point, tz-aware UTC, `extended_data.report.margin_usage="0.0000"`).
5. Capture status codes + bodies for `/health`, `/api/v2/engines/catalog`, and two consecutive POSTs to `/api/v1/ingest/daily-report`.
6. Paste captured output into the Completion Notes section below.

### Step G — Docs / memory / knowledge
1. Tick ROADMAP 0.1/0.3/0.4/0.5 boxes; update Current Status (2026-05-28).
2. Update strategy `README.md` and `CLAUDE.md` only where observable behaviour changed.
3. Umbrella branch `docs/tfex-s50-phase-0-onboarding`; append "Phase 0 complete (2026-05-28)" + four PR links to `.claude/knowledge/feature-tfex-integration.md`.
4. Add a single-purpose memory file for the host-port allocation scheme (csm-set :8100, tfex :8200, openbb :8500). One ≤150-char line in MEMORY.md.

### Step H — Commits + 4 PRs
Conventional Commits per repo; PR bodies link the other three and state merge order: **infra-db → gateway → strategy → umbrella docs**. PR bodies include the curl verification output. Return all four PR URLs.

---

## File Changes

| Repo | File | Action | Sub-phase |
| --- | --- | --- | --- |
| strategy | `docs/plans/phase-0-bootstrap-and-gateway-onboarding.md` | CREATE | 0 (this doc) |
| strategy | `pyproject.toml` | MODIFY | 0.1 |
| strategy | `src/tfex_s50_multi_tf_swing/__init__.py` | CREATE | 0.1 |
| strategy | `src/__init__.py`, `src/main.py` | DELETE | 0.1 |
| strategy | `.env.example` | CREATE | 0.1 |
| strategy | `.pre-commit-config.yaml` | CREATE | 0.1 |
| strategy | `src/tfex_s50_multi_tf_swing/config/{__init__.py,settings.py}` | CREATE | 0.4 |
| strategy | `src/tfex_s50_multi_tf_swing/adapters/{__init__.py,errors.py,payload.py,gateway_client.py,hooks.py}` | CREATE | 0.4 |
| strategy | `tests/unit/adapters/{__init__.py,test_payload.py,test_gateway_client.py,test_hooks.py}` | CREATE | 0.4 |
| strategy | `api/{__init__.py,main.py}` | CREATE | 0.5 |
| strategy | `Dockerfile` | MODIFY (rewrite) | 0.5 |
| strategy | `docker-compose.yml`, `docker-compose.private.yml` | CREATE | 0.5 |
| strategy | `docs/plans/ROADMAP.md` | MODIFY (tick boxes, status) | G |
| strategy | `README.md`, `CLAUDE.md` | MODIFY (only where behaviour changed) | G |
| `quant-infra-db` | `init-scripts/08_schema_db_tfex_s50_multi_tf_swing.sql` | CREATE | 0.3 |
| `quant-api-gateway` | `strategies.json` | MODIFY (append) | 0.3 |
| `quant-api-gateway` | registry-related test (optional) | MODIFY | 0.3 |
| umbrella | `.claude/knowledge/feature-tfex-integration.md` | MODIFY (append) | G |
| memory | new file + 1-line `MEMORY.md` entry | CREATE | G |

---

## Success Criteria

- [ ] Plan file is the **first** commit on `feat/phase-0-bootstrap-gateway-onboarding`
- [ ] Strategy `pyproject.toml` personalised; quality gate green
- [ ] `src/tfex_s50_multi_tf_swing/` package created; template `src/main.py` removed
- [ ] `.env.example` and `.pre-commit-config.yaml` in place
- [ ] `strategies.json` lists new strategy entry (active: false); gateway tests green
- [ ] `init-scripts/08_schema_db_tfex_s50_multi_tf_swing.sql` created + applied to live `quant-postgres`
- [ ] `equity_curve`, `trade_history` (`side`, `contracts INT`, `margin_used NUMERIC(18,4)`), `backtest_log`, `benchmark_equity_curve` present with UNIQUE constraints
- [ ] Adapters implemented (errors / payload / gateway_client / hooks)
- [ ] Adapter unit tests ≥ 90% coverage; respx-based gateway-client tests pass
- [ ] Dockerfile rewritten (multi-stage uv, non-root, HEALTHCHECK)
- [ ] `docker-compose.yml` binds host `:8200`; joins external `quant-network`; `.private.yml` overlay separate
- [ ] `GET /health` → `200 {"status":"ok"}` from inside container
- [ ] `GET /api/v2/engines/catalog` lists `tfex-s50-multi-tf-swing`
- [ ] Idempotent POST round-trip green (POST x2, no duplicate row)
- [ ] ROADMAP boxes 0.1/0.3/0.4/0.5 ticked; Current Status updated (2026-05-28)
- [ ] Four PRs opened with verification output + cross-links + stated merge order

---

## Completion Notes

_To be filled in after Step F passes. Will record: status codes, response bodies
(no secrets), schema verification output, four PR URLs, any deviations encountered
during execution._
