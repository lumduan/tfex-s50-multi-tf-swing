# tfex-s50-multi-tf-swing

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![uv](https://img.shields.io/badge/managed%20by-uv-purple)](https://docs.astral.sh/uv/)
[![Type Safety](https://img.shields.io/badge/type%20safety-mypy%20strict-green)](pyproject.toml)
[![Docker](https://img.shields.io/badge/docker-ready-blue)](Dockerfile)

โครงการนี้ใช้กลยุทธ์ Multi-Timeframe Swing-Intraday บน **SET50 Index Futures (S50)** ของ TFEX
โดยแยกชั้นเวลาเป็น 4H (regime), 1H (setup), และ 5m (execution) เพื่อหา setup ที่ expectancy
สูง ภายใต้กรอบ regime + risk management ที่เคร่งครัด

**Multi-timeframe swing-intraday quant system for TFEX SET50 Index Futures (S50).**
Headless data engine that reports daily snapshots to the umbrella `quant-api-gateway`
under the standard ingestion contract.

---

> **⚠️ Disclaimer**
>
> โปรเจกต์นี้จัดทำขึ้นเพื่อการศึกษาเท่านั้น ไม่ถือเป็นคำแนะนำการลงทุนในทุกกรณี
> ผลการทดสอบย้อนหลัง (backtest) ไม่ได้รับประกันผลตอบแทนในอนาคต โดยเฉพาะอย่างยิ่งใน
> ตลาดอนุพันธ์ (TFEX) ที่มี leverage สูง การขาดทุนเกินทุนตั้งต้นเป็นไปได้
> ผู้พัฒนาไม่รับผิดชอบต่อความเสียหายหรือผลกำไรขาดทุนใดๆ ที่เกิดจากการนำโปรเจกต์นี้ไปใช้งาน
>
> **This project is for educational purposes only. It does not constitute investment
> advice. Futures trading on TFEX uses leverage; losses can exceed initial capital.
> Past backtest results do not guarantee future returns. The developer assumes no
> responsibility for any losses arising from use of this project.**

---

## Table of Contents

- [What this project does](#what-this-project-does)
- [Why start from S50](#why-start-from-s50)
- [Architecture](#architecture)
- [Project status](#project-status)
- [Quick start](#quick-start)
- [Configuration reference](#configuration-reference)
- [Stack](#stack)
- [Project structure](#project-structure)
- [Development](#development)
- [Hard rules](#hard-rules)
- [References](#references)
- [License](#license)

---

## What this project does

- **Multi-timeframe pipeline**: 4H regime + bias → 1H setup detection → 5m execution.
- **Three core strategies**:
  - A — Pullback Continuation (primary)
  - B — Opening Range Breakout
  - C — Liquidity Sweep Reversal
- **Regime-aware**: classifies bars into `trend_up`, `trend_down`, `range_low_vol`,
  `range_high_vol`, `panic` and turns strategies on or off accordingly. "No trade"
  is a feature.
- **ML probability filter**: LightGBM gates rule-based signals via
  `P(trend_continuation)` and `P(fake_breakout)`. ML is a filter, not an oracle.
- **Risk engine first**: ATR-scaled position sizing, daily loss limit, volatility
  scaling, kill switch.
- **Reports to gateway** via the umbrella's `POST /api/v1/ingest/daily-report`
  contract, mirroring the `csm-set` pattern.

## Why start from S50

The hardest problem in quant trading is not "finding markets to trade" but
**managing complexity**. Starting from a single instrument is the hedge-fund path:
single market → single instrument → single strategy. S50 is the right place to start
on TFEX because behaviour patterns (opening volatility, lunch slowdown, gap fill,
foreign flow) are stable, liquidity is adequate, and the research cycle is fast.

The system is engineered to **survive across regimes**, not to look pretty in a
backtest. Edge comes from regime awareness + cost efficiency + risk management +
execution quality — not from a secret indicator.

## Architecture

Five layers, top-down:

```
┌──────────────────────────────────────────────┐
│  Raw Market Data (multi-TF OHLCV)             │
│  4H → Regime / Macro Bias                     │
│  1H → Main Setup Detection                    │
│  5m → Execution & Risk Optimisation           │
├──────────────────────────────────────────────┤
│  Data Layer                                   │
│  Continuous Futures · Features · Validation   │
├──────────────────────────────────────────────┤
│  Intelligence Layer                           │
│  Regime · HTF Bias · ML Probability Filter    │
├──────────────────────────────────────────────┤
│  Execution Layer                              │
│  Setups (A/B/C) · 5m Execution · Risk Engine  │
├──────────────────────────────────────────────┤
│  Validation & Deployment                      │
│  Walk-Forward · Paper · Live                  │
└──────────────────────────────────────────────┘
```

Reporting follows the umbrella's contract: daily snapshots POST to
`quant-api-gateway`, which aggregates with other strategies (e.g. `csm-set`) and
serves the unified surface to OpenBB.

## Project status

| Phase | Status |
| --- | --- |
| 0 — Project Bootstrap & Gateway Onboarding | **Complete** (2026-05-28) |
| 1 — Data Infrastructure | **Code complete** (2026-05-28) — pending 5-year backfill |
| 2 — Feature Engineering | **Complete** (2026-05-29) |
| 3 — Regime Detection | **Rule baseline + policy complete** (2026-05-29) — §3.2 clustering / §3.3 LightGBM deferred |
| 4 — Higher-TF Bias Engine | **§4.1 filter + §4.2 output complete** (2026-06-03) — §4.3 backtest deferred to Phase 5; `4h` mirror-only |
| 5 — Setup Detection & Signals | **§5.1–§5.4 + §5.5 harness complete** (2026-06-03) — Strategies A/B/C + 5m execution engine + per-strategy backtest (`signals/`, `execution/`, `backtest/`); positive-expectancy exit metric + ML filter deferred (data / Phase 6) |
| 6 — ML Probability Filter | Not started |
| 7 — Risk Engine | Not started |
| 8 — Walk-Forward Backtest | Not started |
| 9 — Paper Trading | Not started |
| 10 — Live Deployment | Not started |
| 11 — Adaptive Evolution | Future |

Full plan, exit criteria, and dependencies live in
[`docs/plans/ROADMAP.md`](docs/plans/ROADMAP.md).

## Quick start

Prerequisites: Python 3.11+, [uv](https://docs.astral.sh/uv/), Docker (optional but
recommended).

```bash
git clone https://github.com/lumduan/tfex-s50-multi-tf-swing
cd tfex-s50-multi-tf-swing

# Install all dependencies
uv sync --all-groups

# Run quality gates (mirrors CI)
uv run ruff check . \
  && uv run ruff format --check . \
  && uv run mypy src tests \
  && uv run pytest
```

Phase 0 is complete — the service is launchable via Docker (public mode by
default, host port `:8200`, joins the umbrella `quant-network`):

```bash
docker compose up -d                                            # public mode
docker compose -f docker-compose.yml -f docker-compose.private.yml up -d   # owner mode
curl http://localhost:8200/health
# → {"status":"ok","service":"tfex-s50-multi-tf-swing","version":"0.1.0"}
```

### Phase 1 — Data refresh (owner mode)

OHLCV is source-selected by `TFEX_S50_MULTI_TF_SWING_OHLCV_SOURCE = mirror | engine`
(default `mirror`):

- **`mirror`** (default, shown below): the legacy Phase-1 pipeline — TradingView (tvkit) →
  Parquet (`data/raw/`, `data/continuous/`) → optional TimescaleDB mirror in
  `db_tfex_s50_multi_tf_swing`. This is the only path that uses the tvkit cookie.
- **`engine`**: reads the canonical **Market Data Engine** (`quant-marketdata-engine`) via
  the gateway proxy `/api/v2/engines/market-data/*` — **no tvkit cookie**; the continuous is
  back-adjusted locally and the `09` mirror becomes a derived cache. The default flip to
  `engine` is pending verification. See the ROADMAP's
  [Market data source](docs/plans/ROADMAP.md#market-data-source--the-market-data-engine).

Required env when running the **`mirror`** source in owner mode:

```bash
TFEX_S50_MULTI_TF_SWING_DB_WRITE_ENABLED=true
TFEX_S50_MULTI_TF_SWING_PG_DSN=postgresql://postgres:<pass>@quant-postgres:5432/db_tfex_s50_multi_tf_swing
# Required for the 5-year backfill (anonymous tvkit caps at 5,000 bars per symbol):
TFEX_S50_MULTI_TF_SWING_TVKIT_AUTH_TOKEN={"sessionid":"...","sessionid_sign":"..."}
```

Refresh:

```bash
uv run python scripts/refresh_ohlcv.py \
    --contract S50M2026 --contract S50U2026 --contract S50Z2026 \
    --timeframe 5m --timeframe 1h --timeframe 4h \
    --start 2026-04-01 --end 2026-05-01
# Re-run is idempotent — same rows in / out.
```

Validate a stored Parquet snapshot without re-fetching:

```bash
uv run python scripts/validate_ohlcv.py --as-of 2026-04-30 \
    --contract S50M2026 --timeframe 5m
```

Plan reference: [`docs/plans/phase-1-data-infrastructure.md`](docs/plans/phase-1-data-infrastructure.md).

### Phase 2 — Feature engineering

Phase 2 turns the back-adjusted continuous OHLCV into a causal, multi-timeframe
**feature panel** (trend / volatility / time-of-day / market-structure / regime).
Features are Polars-native, look-ahead-free, and persisted as Float64 under
`data/features/` (never Decimal — features never reach the gateway).

Build the panels from existing continuous Parquet (`data/continuous/<tf>.parquet`):

```bash
uv run python scripts/build_features.py \
    --timeframe 5m --timeframe 1h --timeframe 4h --base-timeframe 5m
# writes data/features/<tf>.parquet (per timeframe)
#    and data/features/aligned_5m.parquet (5m widened with causally-aligned HTF features)
```

Inspect a panel programmatically:

```python
from tfex_s50_multi_tf_swing.features import FeatureStore, FeatureConfig

store = FeatureStore("./data", FeatureConfig())
panel = store.read_panel("5m")        # per-timeframe features
aligned = store.read_aligned("5m")    # + 1h_/4h_ columns, no look-ahead
```

**Look-ahead guarantee:** trailing-only windows, confirmation-lagged pivots/sweeps,
strictly-prior session references, trailing-window normalisation, and
availability-shifted (`time + bar_duration`) as-of joins across timeframes. A
prefix-equals-full regression test proves appending future bars never changes a past
feature value.

Plan reference: [`docs/plans/phase-2-feature-engineering.md`](docs/plans/phase-2-feature-engineering.md).

### Phase 3 — Regime detection

Phase 3 classifies every bar into one of five regimes — `trend_up`, `trend_down`,
`range_low_vol`, `range_high_vol`, `panic` — and maps each to the strategies and
position-size it permits. It is a pure offline library layer (`regime/`); there is **no
new endpoint and no change to the gateway ingestion contract** this phase. The signals API
(Phase 5) and `risk/` wiring (Phase 7) will consume `regime/policy.py` later.

```python
from tfex_s50_multi_tf_swing.regime import (
    build_regime_inputs, classify_frame, regime_policy, is_no_trade,
)

inputs = build_regime_inputs(continuous_4h, "4h")   # un-normalised feature panel + EMA diff
labelled = classify_frame(inputs)                    # adds a `regime` column
policy = regime_policy("trend_up")                   # -> allowed strategies, size, direction
blocked = is_no_trade("range_low_vol")               # True (no-trade regime)
```

Thresholds default to the values in `.claude/knowledge/regime-detection.md` and are
overridable via the `TFEX_S50_MULTI_TF_SWING_REGIME_*` env vars (see the config table).
The LightGBM classifier (§3.3) and clustering notebook (§3.2) are deferred until a
hand-labelled regime dataset exists.

Plan reference: [`docs/plans/phase-3-regime-detection.md`](docs/plans/phase-3-regime-detection.md).

### Phase 4 — Higher-timeframe bias

Phase 4 materialises **one directional bias per 4H bar** (`long` / `short` / `neutral`) to
**veto** counter-trend trades. It **only filters — it never generates trades.** It is a pure
offline library leaf (`bias/`) consuming the un-normalised feature panel + the Phase 3 regime
label; **no endpoint, no gateway change.** Composition is conservative unanimity: a directional
bias needs every gate (EMA cross, slope, structure, VWAP) to agree **and** a healthy regime —
`panic` / `range_low_vol` veto to `neutral`.

```python
from tfex_s50_multi_tf_swing.bias import build_bias_inputs, classify_frame, to_signals

inputs = build_bias_inputs(continuous_4h, "4h")   # un-normalised panel + regime label
labelled = classify_frame(inputs)                  # adds `bias_direction` + `bias_reasons`
signals = to_signals(labelled)                     # one BiasSignal per 4H bar
```

Deadbands default to a strict sign test and are overridable via
`TFEX_S50_MULTI_TF_SWING_BIAS_*` (see the config table). **`4h` is mirror-only** until the
Market Data Engine ships a `4h` route — `bias/` is source-agnostic and never fetches tvkit.
§4.3 (the ≥ 30% counter-trend-reduction backtest) is deferred to Phase 5; a demonstration ships
in `scripts/bias_counter_trend_demo.py`. Visualise with `scripts/visualise_bias.py` /
`notebooks/04_htf_bias.ipynb`.

Plan reference: [`docs/plans/phase-4-htf-bias-engine.md`](docs/plans/phase-4-htf-bias-engine.md).

## Configuration reference

Environment variables (prefix `TFEX_S50_MULTI_TF_SWING_*`, loaded via
`pydantic-settings`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `TFEX_S50_MULTI_TF_SWING_PUBLIC_MODE` | `true` | Read-only mode; flips off scheduler and writes. |
| `TFEX_S50_MULTI_TF_SWING_DB_WRITE_ENABLED` | `false` | Whether to mirror to Postgres. |
| `TFEX_S50_MULTI_TF_SWING_PG_DSN` | — | DSN for `db_tfex_s50_multi_tf_swing` (required when `DB_WRITE_ENABLED=true`). |
| `TFEX_S50_MULTI_TF_SWING_GATEWAY_BASE_URL` | `http://quant-api-gateway:8000` | Umbrella gateway base URL. |
| `TFEX_S50_MULTI_TF_SWING_GATEWAY_API_KEY` | — | Shared key for ingestion auth. |
| `TFEX_S50_MULTI_TF_SWING_REGIME_PANIC_RV` | `0.95` | `panic` when realised-vol percentile exceeds this. |
| `TFEX_S50_MULTI_TF_SWING_REGIME_PANIC_VOLUME_Z` | `3.0` | `panic` when trailing volume z-score exceeds this. |
| `TFEX_S50_MULTI_TF_SWING_REGIME_RANGE_LOW_RV` | `0.30` | `range_low_vol` rv-percentile upper bound. |
| `TFEX_S50_MULTI_TF_SWING_REGIME_RANGE_HIGH_RV` | `0.70` | `range_high_vol` rv-percentile reference. |
| `TFEX_S50_MULTI_TF_SWING_REGIME_TREND_PERSIST_MIN` | `0.30` | min `\|trend_persistence\|` to call a tape trending. |
| `TFEX_S50_MULTI_TF_SWING_BIAS_SLOPE_DEADBAND` | `0.0` | Noise band the 4H EMA slope must exceed before the bias votes directionally. |
| `TFEX_S50_MULTI_TF_SWING_BIAS_VWAP_DEADBAND` | `0.0` | Noise band the VWAP distance must exceed before the bias votes directionally. |

Never commit a real `.env` — copy `.env.example` and fill values locally.

## Stack

- **Python 3.11+** with `uv` for dependency management.
- **Polars** / **DuckDB** for in-memory and on-disk analytics.
- **PyArrow / Parquet** as the durable tabular store.
- **LightGBM** for the ML probability filter (XGBoost / CatBoost as alternates).
- **FastAPI** for the headless service surface (Phase 0+).
- **Pydantic v2** at every boundary.
- **Docker** with multi-stage builds, joining the external `quant-network`.

## Project structure

```
.
├── .claude/                       # AI agent context & playbooks
│   ├── knowledge/                 # Strategy overview, features, regimes, etc.
│   ├── playbooks/                 # Dev workflow, gateway onboarding
│   ├── memory/                    # Local memory index
│   ├── agents/                    # (reserved)
│   └── templates/                 # (reserved)
├── .github/                       # CI/CD, issue & PR templates
│   └── workflows/                 # ci.yml, docker-publish.yml, security.yml
├── docs/
│   ├── overview.md
│   └── plans/
│       └── ROADMAP.md             # Canonical phase plan
├── src/
│   └── tfex_s50_multi_tf_swing/   # (to be populated in Phase 1+)
├── tests/                         # unit + integration
├── data/                          # (gitignored) raw / cleaned / continuous / features / labels
├── results/                       # (committed) public-safe summaries
├── Dockerfile
├── docker-compose.yml
├── docker-compose.private.yml     # (Phase 0)
├── pyproject.toml
├── uv.lock
├── CLAUDE.md                      # Agent guide
└── README.md
```

## Development

Always use `uv` — never bare `python` / `pip` / `poetry` / `conda`.

```bash
uv sync --all-groups
uv run ruff check . --fix
uv run ruff format .
uv run mypy src tests
uv run pytest --cov=src --cov-report=term-missing
```

Pre-commit hooks (`ruff-check`, `ruff-format`, `mypy`) install via:

```bash
uv run pre-commit install
```

Conventional Commits: `feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`.

## Hard rules

The non-negotiable rules for this project:

1. **Position sizing in contracts.** S50 multiplier = 200 THB per index point.
2. **No averaging down.** A losing trade is a wrong idea.
3. **Regime gates trading.** `range_low_vol` and the 12:00–14:00 lunch dead zone
   are no-trade.
4. **Walk-forward only.** No random splits, ever.
5. **ML is a filter, not a strategy.**
6. **Decimals as strings** across the gateway boundary; never `float`.
7. **Timezones tz-aware UTC** at storage, `Asia/Bangkok` at display.
8. **No secrets in repo** — `.env` is local and gitignored.

Full rationale in [`CLAUDE.md`](CLAUDE.md) and the `.claude/knowledge/` files.

## References

- Umbrella system map — [`../../CLAUDE.md`](../../CLAUDE.md)
- Strategy onboarding contract — [`../../STRATEGY_ONBOARDING.md`](../../STRATEGY_ONBOARDING.md)
- Template / reference strategy — [`../csm-set/`](../csm-set/)
- Project agent guide — [`CLAUDE.md`](CLAUDE.md)
- Phase plan — [`docs/plans/ROADMAP.md`](docs/plans/ROADMAP.md)

## License

MIT — see [LICENSE](LICENSE) for details.
