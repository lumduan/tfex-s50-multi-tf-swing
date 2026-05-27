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
| 0 — Project Bootstrap & Gateway Onboarding | **In progress** |
| 1 — Data Infrastructure | Not started |
| 2 — Feature Engineering | Not started |
| 3 — Regime Detection | Not started |
| 4 — Higher-TF Bias Engine | Not started |
| 5 — Setup Detection & Signals | Not started |
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

Once Phase 0 is complete, the service will be launchable via Docker (public mode by
default, host port 8200):

```bash
docker compose up
```

## Configuration reference

Environment variables (prefix `TFEX_S50_MULTI_TF_SWING_*`, loaded via
`pydantic-settings`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `TFEX_S50_MULTI_TF_SWING_PUBLIC_MODE` | `true` | Read-only mode; flips off scheduler and writes. |
| `TFEX_S50_MULTI_TF_SWING_DB_WRITE_ENABLED` | `false` | Whether to mirror to Postgres. |
| `TFEX_S50_MULTI_TF_SWING_DB_TFEX_S50_MULTI_TF_SWING_DSN` | — | DSN for `db_tfex_s50_multi_tf_swing` |
| `TFEX_S50_MULTI_TF_SWING_GATEWAY_BASE_URL` | `http://quant-api-gateway:8000` | Umbrella gateway base URL. |
| `TFEX_S50_MULTI_TF_SWING_GATEWAY_API_KEY` | — | Shared key for ingestion auth. |

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
