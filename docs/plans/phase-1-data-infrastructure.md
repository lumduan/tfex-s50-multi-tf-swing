# Phase 1: Data Infrastructure

**Feature:** Multi-timeframe OHLCV data layer for S50 futures
**Branch:** `feature/phase-1-data-infrastructure`
**Created:** 2026-05-28
**Status:** In progress
**Depends On:** Phase 0 (Complete, 2026-05-28)

---

## Table of Contents

1. [Source prompt](#1-source-prompt)
2. [Objective](#2-objective)
3. [Scope (in / out)](#3-scope-in--out)
4. [Architecture sketch](#4-architecture-sketch)
5. [Data model](#5-data-model)
6. [Migrations](#6-migrations)
7. [Data ingestion / adapter contract](#7-data-ingestion--adapter-contract)
8. [Source providers](#8-source-providers)
9. [Configuration & secrets](#9-configuration--secrets)
10. [Local bring-up](#10-local-bring-up)
11. [Tests](#11-tests)
12. [Quality gate](#12-quality-gate)
13. [Risks & mitigations](#13-risks--mitigations)
14. [Acceptance criteria](#14-acceptance-criteria)
15. [Rollback plan](#15-rollback-plan)
16. [Open questions](#16-open-questions)
17. [Outcome](#17-outcome)

---

## 1. Source prompt

```
# Task: Implement Phase 1 — Data Infrastructure for `strategies/tfex-s50-multi-tf-swing/`

You are working inside the umbrella repo at `quant-trading-system/`. Each
sub-directory listed below is its own independent git repo with its own
remote and CI. Do NOT alter umbrella git history when committing inside a
sub-repo, and vice versa.

[… full prompt as supplied by the user on 2026-05-28; see PR description for
the verbatim text. Key points captured below: Parquet primary + TimescaleDB
hypertable mirror; tvkit data source; no Phase 1 gateway POST changes;
quality bar: ruff + ruff format + mypy --strict on adapters/ + risk/ +
data/, pytest with ≥90% coverage on those sub-packages; Conventional
Commits; cross-repo PR sequencing; never force-push, never skip hooks. …]
```

The full prompt was preserved in the task tracking thread for this branch; it
is too long to embed inline without diluting the rest of this document. The
choices it locked are reflected throughout this plan.

## 2. Objective

Deliver a validated, idempotent OHLCV pipeline for S50 futures at 4H / 1H / 5m
for ≥ 5 years of history, including a back-adjusted continuous contract that
survives quarterly rollovers, plus the Thai market session calendar that every
downstream phase (regime gates, strategies A/B/C, risk engine, backtest)
depends on. Parquet is the source of truth; a TimescaleDB hypertable mirror is
written under `db_write_enabled=true` for OpenBB / future SQL consumers.

## 3. Scope (in / out)

**In scope:**

| Component | Description |
| --- | --- |
| `data/fetcher.py` | tvkit-async OHLCV fetcher for per-contract (`S50<code><yyyy>`) and continuous (`S501!`) symbols |
| `data/contracts.py` | Quarterly H/M/U/Z calendar, expiry resolution via TFEX business calendar, TradingView symbol helpers |
| `data/session.py` | TFEX session boundaries, Thai holiday calendar (2024–2026 baseline), time-of-day buckets, lunch dead-zone, expiry/rollover flags |
| `data/validator.py` | Missing-bar (in observed window), duplicate-timestamp, abnormal-spread (>3σ), and cross-timeframe-consistency checks. Plus `S501!` cross-check on continuous output |
| `data/continuous.py` | Back-adjusted continuous series with volume-crossover roll (default 5d before expiry), ratio-adjusted historical prices, raw per-contract series preserved |
| `data/store.py` | Typed PyArrow Parquet I/O for `raw/`, `cleaned/`, `continuous/`, `continuous_reference/`, `validation/` layouts |
| `data/db_writer.py` | asyncpg `INSERT … ON CONFLICT … DO UPDATE` mirror to `ohlcv_raw` + `ohlcv_continuous` hypertables |
| `data/refresh.py` | End-to-end orchestrator: fetch → store → validate → continuous → mirror → report. Idempotent |
| `data/models.py` | Pydantic frozen models for OhlcvBar, ContinuousBar, RollRecord, ValidationReport, ContinuousCrossCheck, ContractSpec, SessionWindow |
| `data/errors.py` | Module-local exceptions rooted at `TfexS50Error` |
| `scripts/refresh_ohlcv.py` | CLI entry-point to the orchestrator |
| `scripts/validate_ohlcv.py` | Re-validate latest Parquet without re-fetching |
| `notebooks/01_data_quality.ipynb` | ROADMAP §1.5 diagnostics: heatmap, return distributions, volume across rolls, spread |

**Out of scope (deferred to later phases):**

* Feature engineering (Phase 2). `data/features/` directory unused.
* Labels for ML (Phase 6). `data/labels/` directory unused.
* Regime / bias / signals / risk / backtest / paper / live.
* Daily-report POST to the gateway — Phase 0 hook stays untouched until Phase 5+ when real P&L exists.
* Flipping `strategies.json:tfex-s50-multi-tf-swing.active` to `true` — gated on Phase 10 live validation.

## 4. Architecture sketch

```
tvkit (TradingView)
  └─→ data.fetcher.fetch_contract / fetch_continuous_reference
        async, retry, concurrency-limited
  └─→ data.store.write_raw   →  data/raw/<contract>/<tf>.parquet
        and optionally → ohlcv_raw (TimescaleDB hypertable)
  └─→ data.validator.validate(...)
        per-session missing, duplicates, abnormal spreads, x-TF consistency
        report → data/validation/<date>.json
  └─→ data.continuous.build_continuous(...)
        volume-crossover roll, back-adjusted, ratio-tracked
        → data/continuous/<tf>.parquet
        and optionally → ohlcv_continuous (TimescaleDB hypertable)
  └─→ data.validator.validate_continuous_against_reference(...)
        cross-check our continuous against TradingView's S501!
```

Phase 1 sits under the existing **Market Data Engine** slot in the engine
catalog. The gateway `/api/v2/engines/*` surfaces are unchanged. The strategy
joins `quant-network` exactly as Phase 0 wired it; the new outbound dependency
is `quant-postgres:5432`, controlled by `TFEX_S50_MULTI_TF_SWING_PG_DSN`.

## 5. Data model

Phase 1 writes two Parquet layouts and two TimescaleDB hypertables.

### 5.1 Parquet layout (source of truth)

Rooted at `Settings.data_dir`:

```
raw/<contract>/<tf>.parquet                  # per-quarterly OHLCV
cleaned/<contract>/<tf>.parquet              # post-validator (reserved; Phase 1 emits same content as raw)
continuous/<tf>.parquet                      # back-adjusted continuous + contract_at_time + adjustment_factor
continuous_reference/<tf>.parquet            # TradingView S501! reference, cross-check input only
validation/<YYYY-MM-DD>.json                 # per-day aggregate ValidationReport
```

PyArrow schemas (declared as constants in `data/store.py`):

| Column | Raw schema | Continuous schema | Reference schema |
| --- | --- | --- | --- |
| `time` | `TIMESTAMP[us, UTC]` | same | same |
| `contract` | `string` | — | — |
| `timeframe` | `string` | `string` | `string` |
| `open/high/low/close/volume` | `decimal(18, 4)` | `decimal(18, 4)` | `decimal(18, 4)` |
| `open_interest` | `decimal(18, 4)` (nullable) | — | — |
| `contract_at_time` | — | `string` | — |
| `adjustment_factor` | — | `decimal(18, 8)` | — |

### 5.2 TimescaleDB mirror

In database `db_tfex_s50_multi_tf_swing`, schema 09 adds two hypertables on
`time` with `INTERVAL '30 days'` chunks and `UNIQUE` natural keys:

* `ohlcv_raw (time, contract, timeframe, OHLCV, volume, open_interest)` — UNIQUE `(time, contract, timeframe)`
* `ohlcv_continuous (time, timeframe, OHLCV, volume, contract_at_time, adjustment_factor)` — UNIQUE `(time, timeframe)`

All money columns are `NUMERIC(18,4)`; `adjustment_factor` is `NUMERIC(18,8)`.
Money never crosses as `float`.

## 6. Migrations

Migrations follow the umbrella's centralised init-script pattern (no
per-strategy alembic). The strategy PR depends on `quant-infra-db` PR #9 which
adds:

* `quant-infra-db/init-scripts/09_schema_db_tfex_s50_multi_tf_swing_ohlcv.sql`

Both new tables are wrapped in `IF NOT EXISTS` and `create_hypertable(...,
if_not_exists => TRUE)`, so re-applying is a no-op. Verified by running the
script twice against an already-initialised DB — second run emits only
`NOTICE: ... already exists, skipping`.

## 7. Data ingestion / adapter contract

Phase 1 does NOT change the `POST /api/v1/ingest/daily-report` contract. The
Phase 0 adapters (`payload`, `gateway_client`, `hooks`) are untouched. The
strategy will only start producing daily-report payloads in Phase 5+ when
trades and P&L exist.

Phase 1's outputs sit purely in:

* The local `data/` tree (Parquet + JSON), gitignored.
* The `db_tfex_s50_multi_tf_swing` hypertables, when `DB_WRITE_ENABLED=true`
  and `PG_DSN` is set.

## 8. Source providers

* **tvkit** (TradingView WebSocket, async). Confirmed dependency, version `>=
  0.11` in `pyproject.toml`. Reuses the same library `csm-set` already
  validates.
* **Symbol conventions** (locked in `data/contracts.py`):
  * Per-contract: `TFEX:S50<H|M|U|Z><yyyy>` — e.g. `TFEX:S50H2026`,
    `TFEX:S50M2026`.
  * Continuous reference: `TFEX:S501!` — TradingView's auto-roll front-month
    series. **Reference only**; the strategy builds its own back-adjusted
    continuous so the roll policy is explicit and reproducible.
* **Auth**: `TFEX_S50_MULTI_TF_SWING_TVKIT_AUTH_TOKEN` is required for >5,000
  bars per symbol — i.e. the 5-year 5m backfill. Anonymous sessions cap at
  5k bars per symbol.

The other listed alternative in ROADMAP §1.1 — a direct TFEX feed — is **not**
wired in Phase 1. It would require new vendor credentials and adds scope
beyond the ROADMAP exit criteria. If the team chooses to add it later, the
fetcher's surface (`fetch_contract` / `fetch_continuous_reference`) is the
extension point.

## 9. Configuration & secrets

New `Settings` fields (all under prefix `TFEX_S50_MULTI_TF_SWING_`):

| Name | Type | Default | Purpose |
| --- | --- | --- | --- |
| `data_dir` | `Path` | `./data` | Root of the Parquet store |
| `tvkit_auth_token` | `SecretStr \| None` | `None` | JSON-encoded TV session cookies; required for >5k bar pulls |
| `data_fetch_concurrency` | `int (≥1, ≤32)` | `4` | tvkit concurrent fetch semaphore |
| `roll_offset_days` | `int (≥0, ≤30)` | `5` | Days before expiry where the continuous-contract roll is allowed |

Phase 0 fields (`public_mode`, `db_write_enabled`, `gateway_base_url`,
`gateway_api_key`, `pg_dsn`) are unchanged.

`.env.example` was updated to document the new keys. The
`db_write_enabled`-vs-`pg_dsn` coupling is enforced at the `OhlcvDbWriter`
construction site (clear error when `db_write_enabled=true` but `pg_dsn` is
unset), not at `Settings` validation time — so Phase 0's hook tests keep
working.

## 10. Local bring-up

From the umbrella root, after the infra-db schema PR is merged:

```bash
cd quant-infra-db        && git pull --ff-only && docker compose up -d
cd ../quant-api-gateway  && docker compose up -d
cd ../strategies/tfex-s50-multi-tf-swing && docker compose up -d
curl -fsS http://localhost:8200/health    # → {"status":"ok",...}

# Owner-mode (.env has DB_WRITE_ENABLED=true + PG_DSN + TVKIT_AUTH_TOKEN):
docker compose exec tfex uv run python scripts/refresh_ohlcv.py \
    --contract S50M2026 --timeframe 5m \
    --start 2026-04-01 --end 2026-05-01

# Re-run to confirm idempotency: counts must be unchanged.
docker compose exec tfex uv run python scripts/refresh_ohlcv.py \
    --contract S50M2026 --timeframe 5m \
    --start 2026-04-01 --end 2026-05-01

docker compose exec quant-postgres psql -U postgres -d db_tfex_s50_multi_tf_swing -c \
    "SELECT contract, timeframe, COUNT(*) FROM ohlcv_raw GROUP BY 1,2 ORDER BY 1,2;"
```

Validation report:

```bash
docker compose exec tfex uv run python scripts/validate_ohlcv.py \
    --as-of 2026-04-30 --contract S50M2026 --timeframe 5m
```

Tear down in reverse order; `docker compose down -v` on infra-db removes the
network.

## 11. Tests

Coverage target: ≥ 90 % on `src/tfex_s50_multi_tf_swing/{adapters,data}/`.
Pytest is configured with `asyncio_mode = "auto"` and
`--import-mode=importlib`. Achieved: **94.09 % overall**, all sub-modules ≥
84 %.

### Unit tests (`tests/unit/data/`)

* `test_session.py` — session boundary minutes (09:45 / 12:30 / 14:30 / 16:55 / 18:45 / 03:00 BKK), holiday lookup, lunch dead-zone, expiry/rollover-week flags, time-of-day buckets, tz handling (UTC + non-BKK).
* `test_contracts.py` — H/M/U/Z calendar, last-business-day expiry resolution (with Thai holidays), TradingView symbol helpers, `S501!` constant, parser rejects malformed codes.
* `test_store.py` — Parquet round-trip preserves Decimal precision + UTC tz, schema enforcement, deduplication, ValidationReport JSON round-trip.
* `test_validator.py` — duplicate detection, missing-bar detection within the observed window, abnormal-spread σ flag, cross-timeframe consistency (5m → 1H), `validate_continuous_against_reference` shape + flagging.
* `test_continuous.py` — empty input rejected, single-contract no-roll path, synthetic two-contract roll asserts ratio direction (far/near) and back-adjusted continuity, fallback to expiry when no volume crossover, calendar-order sorting on out-of-order input.
* `test_fetcher.py` — tvkit mocked at the `OHLCV` boundary, retry on `StreamConnectionError` / `TimeoutError`, terminal on `ValueError`, auth-token JSON parsing, naive-datetime rejection.
* `test_db_writer.py` — pure row builders, fake asyncpg pool exercises `executemany`, `PostgresError` → `DbWriterError`.
* `test_refresh.py` — orchestrator wires fetcher + store + validator + continuous; idempotency proven by two consecutive runs against the same Parquet store.

### Integration tests (`tests/integration/data/`, marker `infra_db`)

* `test_db_writer.py` — connects to live `quant-postgres`; UPSERT twice → 1 row; both `ohlcv_raw` + `ohlcv_continuous` listed in `timescaledb_information.hypertables`. Self-skips when `TFEX_S50_MULTI_TF_SWING_PG_DSN` is unset.

## 12. Quality gate

Match CI exactly. Run from `strategies/tfex-s50-multi-tf-swing/` before every
push (per the user's pre-push checklist memory):

```bash
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest tests/ -v
```

mypy is strict on the full `src/` tree (Phase 0 already enforces this on
`adapters/`; Phase 1 extends it to `data/`).

## 13. Risks & mitigations

| Risk | Mitigation |
| --- | --- |
| **Timezone bugs** (UTC vs Asia/Bangkok) | Every constructed datetime is tz-aware UTC; BKK conversion is explicit at the session-calendar boundary; unit tests at every session edge in both BKK and UTC. |
| **Contract rollover ambiguity** | `roll_offset_days` is config-driven (default 5) and recorded in `RollRecord`. Fallback to expiry if no volume crossover. Roll records are surfaced in `RefreshSummary` so a human can audit. |
| **tvkit anonymous-session 5k-bar cap** | `.env.example` documents the requirement for `TVKIT_AUTH_TOKEN`; the fetcher wraps non-retryable failures (including invalid auth) in `FetcherError` with the original symbol/range/cause. |
| **Schema drift vs `extended_data` discipline** | New tables live entirely in `db_tfex_s50_multi_tf_swing`, never `db_gateway`. Gateway tables / extended_data shape unchanged. |
| **Idempotent backfills** | Postgres `INSERT … ON CONFLICT` on `(time, contract, timeframe)` for raw and `(time, timeframe)` for continuous. Parquet writes deterministic on file path + dedup-on-time. Refresh integration test proves two consecutive runs produce identical state. |
| **Decimal-vs-float drift at the DB boundary** | `_to_decimal` raises `DbWriterError` if a `float` reaches the writer; row builder cast tests exercise this. |
| **Cross-repo coordination** | Strategy PR's integration tests gate on `@pytest.mark.infra_db`, which self-skips. The schema PR must merge first; documented in the PR description. |

## 14. Acceptance criteria

Lifted directly from `docs/plans/ROADMAP.md` Phase 1; tick only after the
corresponding code + verify passes.

- [ ] **1.1 OHLCV Ingestion** — `data/fetcher.py` async tvkit fetch at 4H/1H/5m, retry on transient errors. Storage layout `data/raw/<contract>/<timeframe>.parquet` (H/M/U/Z), plus `data/continuous/<timeframe>.parquet`.
- [ ] **1.2 Continuous Contract** — `data/continuous.py` volume-crossover roll (default `5d_before_expiry`), ratio-adjusted historical prices, raw per-contract series preserved.
- [ ] **1.3 Session Metadata** — `data/session.py` with Thai holiday calendar (2024–2026), session boundaries verified against TFEX official, expiry-week / rollover-week flags, time-of-day buckets.
- [ ] **1.4 Validation Pipeline** — `data/validator.py` covers missing bars (within observed window), duplicate timestamps, abnormal spread (>3σ), cross-timeframe consistency. Report at `data/validation/<date>.json`.
- [ ] **1.5 Data Quality Notebook** — `notebooks/01_data_quality.ipynb` covers heatmap, return-by-year-and-session distribution, volume/OI across rollovers, spread distribution.
- [ ] **Exit** — continuous 4H/1H/5m series for ≥ 5 years of S50 history, < 0.1 % missing candles in the observed window, rollovers visually clean in the back-adjusted series.

The exit criterion's "≥ 5 years" requires the owner to supply a TradingView
auth token (env: `TFEX_S50_MULTI_TF_SWING_TVKIT_AUTH_TOKEN`); without it the
fetch caps at 5,000 bars per symbol. The code is correct; the data window is
operationally gated on auth, not code-gated.

## 15. Rollback plan

* **Strategy PR**: revert the merge commit on `feature/phase-1-data-infrastructure`. `data/` is gitignored, so no orphan artifacts. `docker compose down && docker compose up -d` brings the Phase 0 image back. The post-refresh hook was not touched, so gateway state is unaffected.
* **Schema PR**: tables are additive and idempotent. To roll back, drop them: `DROP TABLE IF EXISTS ohlcv_continuous; DROP TABLE IF EXISTS ohlcv_raw;` against `db_tfex_s50_multi_tf_swing`. The 08-series schema and `db_gateway` are untouched.
* **Umbrella PR**: pure doc changes — revert the merge commit.

## 16. Open questions

1. **TFEX expiry convention** — code uses *last business day of the contract month* per the TFEX S50 spec sheet. The unit tests pin this against known historical contracts (e.g. `S50Z2024` → 2024-12-30, since 2024-12-31 is a Thai market holiday). If the spec is ever revised, this is the single most likely source of off-by-one errors.
2. **TradingView symbols** (resolved by user, 2026-05-28) — continuous front-month is `S501!`; per-contract is `S50<code><yyyy>` (e.g. `S50H2026`). Both pinned in `data/contracts.py` with regression tests.
3. **Thai holiday calendar maintenance** — the embedded list covers 2024–2026; this needs annual refresh from the SET holiday schedule. Documented inline.
4. **Engine catalog registration** — TFEX is already registered in `strategies.json` with `active=false`. Phase 1 does not flip this; that happens in Phase 10 after live validation.
5. **OpenBB consumption** — the new `ohlcv_*` hypertables are written by the strategy, but a future OpenBB `openbb_quant` provider may want to read them via the gateway's v2 surface. That surface is out of scope here; the data is in place for whenever it's added.

## 17. Outcome

* **Completion date:** 2026-05-28
* **Deviations from plan:** none material. The `Settings` model_validator that
  coupled `pg_dsn` to `db_write_enabled` was dropped after Phase 0 hook tests
  broke; the gate now lives at the `OhlcvDbWriter` construction site instead.
* **Test results:**
  * 161 unit tests pass, 5 integration tests pass (against live Postgres +
    TimescaleDB)
  * Coverage on `adapters/` + `data/`: **93.79 %** overall (threshold 90 %)
  * `uv run mypy src tests` — clean, 39 source files, no errors
  * `uv run ruff check .` — clean
  * `uv run ruff format --check .` — clean
  * Smoke test: `docker compose up -d` brings the container up, `curl
    http://localhost:8200/health` returns `{"status":"ok","service":"tfex-s50-multi-tf-swing","version":"0.1.0"}`; the new named volume `tfex-data` mounts at `/app/data` with `app` ownership; `scripts/refresh_ohlcv.py` and `scripts/validate_ohlcv.py` are present in the image.
* **Commit SHAs and PR links:** to be filled by `commit-push-pr` step.

### Problems encountered

* tvkit 0.11.1 ships a stale `__version__ = "0.6.0"` string in its
  `__init__.py` despite the dist-info reporting 0.11.1. Functionally the right
  code is loaded; the version string is the only stale artifact. Not our bug.
* Initial back-adjustment ratio direction was wrong (`near/far` instead of
  `far/near`). Caught by the synthetic two-contract roll test; fixed before
  merge.
* The missing-bar validator originally counted *all* sessions; we narrowed it
  to the observed `[day_min, day_max]` window so tests that fetch only a
  morning slice don't get afternoon+night bars counted as missing.
* `session_of` + `time_of_day_bucket` had to short-circuit on the
  post-midnight night-session tail BEFORE the pre-open branch — otherwise
  01:00 BKK was classified as `pre-open`.
* The empty-frame integration tests need to use `.head(0)` to preserve the
  schema after `_raw_frame(0)` was reduced to an empty row list (which
  Polars happens to produce with no columns).

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Opus 4.7)
**Created:** 2026-05-28
