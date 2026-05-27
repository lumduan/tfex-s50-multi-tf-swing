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

## Phase 0 — Project Bootstrap & Gateway Onboarding

> Goal: working repo, clean tooling, registered as a strategy under the umbrella
> ingestion contract. After this phase the service is *callable* end-to-end even if
> the data and signal layers are still stubs.

### 0.1 Repository & Tooling

- [x] GitHub repo created and renamed to `lumduan/tfex-s50-multi-tf-swing`
- [x] Local skeleton synced from the Python template (uv, ruff, mypy strict, pytest)
- [x] Initial feature branch `feat/initial-roadmap-and-agent-context`
- [ ] Personalise `pyproject.toml`: name `tfex-s50-multi-tf-swing`, description, package
  path `src/tfex_s50_multi_tf_swing/`
- [ ] `.env.example` with strategy env prefix `TFEX_S50_MULTI_TF_SWING_*`
- [ ] Pre-commit hooks active (`ruff check`, `ruff format`, `mypy`)
- [ ] Verify quality gates on empty project: `uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest`

### 0.2 Roadmap & Agent Context

- [x] `docs/plans/ROADMAP.md` — this document
- [x] `CLAUDE.md` — agent guide mirroring `csm-set/CLAUDE.md`
- [x] `.claude/knowledge/*` — strategy overview, feature engineering, regime detection,
  strategy design, risk engine, ML filter, backtest protocol
- [x] `.claude/playbooks/*` — development workflow, gateway onboarding
- [x] `README.md` rewritten for the strategy

### 0.3 Gateway & DB Registration

- [ ] Add gateway entry in `quant-api-gateway/strategies.json`:
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
- [ ] Database init script in `quant-infra-db/init-scripts/0X_schema_db_tfex_s50_multi_tf_swing.sql`:
  - [ ] `equity_curve` (TimescaleDB hypertable)
  - [ ] `trade_history` (with `side`, `contracts`, `margin_used`)
  - [ ] `backtest_log`
  - [ ] `benchmark_equity_curve` (S50 underlying / SET50 TR)
- [ ] Reserve host port `:8200` to avoid collision with csm-set (`:8100`) and OpenBB (`:8500`)

### 0.4 Adapter Scaffolding

- [ ] `src/tfex_s50_multi_tf_swing/adapters/payload.py` — Pydantic builder for
  `POST /api/v1/ingest/daily-report` (decimal-as-string, UTC tz-aware)
- [ ] `src/tfex_s50_multi_tf_swing/adapters/gateway_client.py` — async `httpx.AsyncClient`
  with retry and idempotency
- [ ] `src/tfex_s50_multi_tf_swing/adapters/hooks.py` — `run_post_refresh_hook` entrypoint
- [ ] Unit tests on adapter modules (≥90% coverage)

### 0.5 Docker

- [ ] `docker-compose.yml` — public-safe defaults, joins external `quant-network`
- [ ] `docker-compose.private.yml` — write-mode override with `env_file`
- [ ] `Dockerfile` parameterised on `TFEX_S50_MULTI_TF_SWING_PUBLIC_MODE`

**Exit criteria:** `docker compose up` starts the service on `quant-network`, gateway
catalog lists the new strategy, an empty daily-report POST round-trips with `202`,
all quality gates pass.

---

## Phase 1 — Data Infrastructure

> Goal: clean, validated OHLCV at 4H / 1H / 5m for S50 futures, stored as Parquet,
> with a back-adjusted continuous contract that survives quarterly rollovers.

### 1.1 OHLCV Ingestion

- [ ] `src/tfex_s50_multi_tf_swing/data/fetcher.py` — TFEX S50 OHLCV loader at 4H, 1H, 5m
  - [ ] Source via `tvkit` (TradingView) or TFEX direct feed
  - [ ] Async batch fetch, retry on transient errors
- [ ] Storage layout:
  - [ ] `data/raw/<contract>/<timeframe>.parquet` (per quarterly contract — H/M/U/Z)
  - [ ] `data/cleaned/<contract>/<timeframe>.parquet`
  - [ ] `data/continuous/<timeframe>.parquet` (back-adjusted)
  - [ ] `data/features/<timeframe>.parquet`
  - [ ] `data/labels/<timeframe>.parquet`

### 1.2 Continuous Futures Contract

- [ ] `src/tfex_s50_multi_tf_swing/data/continuous.py` — back-adjusted continuous series
  - [ ] Roll on volume crossover near expiry (configurable: `5d_before_expiry` default)
  - [ ] Ratio-adjust historical prices to remove rollover gap
  - [ ] Preserve raw per-contract series for execution simulation
- [ ] Unit tests: synthetic two-contract roll, assert post-roll continuity in returns

### 1.3 Session Metadata

- [ ] `src/tfex_s50_multi_tf_swing/data/session.py`
  - [ ] Thai market holiday calendar
  - [ ] Trading session boundaries (morning 09:45–12:30, afternoon 14:30–16:55, night
    18:45–03:00 — verify against TFEX official sessions)
  - [ ] Expiry-week flag, rollover-week flag
  - [ ] Time-of-day buckets: pre-open / open / mid-morning / lunch / afternoon / pre-close / night

### 1.4 Validation Pipeline

- [ ] `src/tfex_s50_multi_tf_swing/data/validator.py`
  - [ ] Missing candle detection per session
  - [ ] Duplicate timestamp removal
  - [ ] Abnormal spread / price-gap flag (>3σ)
  - [ ] Cross-timeframe consistency (5m aggregated → 1H == fetched 1H)
- [ ] Validation report saved to `data/validation/<date>.json`

### 1.5 Data Quality Notebook

- [ ] `notebooks/01_data_quality.ipynb`
  - [ ] Missing-candle heatmap per session
  - [ ] Return distribution by year, by session
  - [ ] Volume / open-interest evolution across rollovers
  - [ ] Spread distribution

**Exit criteria:** continuous 4H / 1H / 5m series for ≥ 5 years of S50 history,
validation report shows < 0.1% missing candles, rollovers visually clean in the
back-adjusted series.

---

## Phase 2 — Feature Engineering

> Goal: a feature panel covering trend, volatility, time-of-day, market structure,
> and regime — this is where the real edge lives, not in any single model.

### 2.1 Trend Features

- [ ] `src/tfex_s50_multi_tf_swing/features/trend.py`
  - [ ] `ema_slope`: `(EMA_t - EMA_{t-n}) / n`, normalised by ATR
  - [ ] `structure`: HH/HL/LH/LL classification from swing pivots
  - [ ] `dist_from_vwap`: `(price - VWAP) / ATR` per session
- [ ] Unit tests against hand-computed values on synthetic series

### 2.2 Volatility Features

- [ ] `src/tfex_s50_multi_tf_swing/features/volatility.py`
  - [ ] `atr_ratio`: `ATR_short / ATR_long` (expansion / compression detector)
  - [ ] `bollinger_squeeze`: Bollinger band width vs Keltner channel
  - [ ] `realised_vol`: rolling realised volatility, multiple horizons
- [ ] Unit tests: ATR expansion detection on known squeeze → expansion sequence

### 2.3 Time-of-Day Features

- [ ] `src/tfex_s50_multi_tf_swing/features/time_of_day.py`
  - [ ] `opening_range`: high/low of first 15m (and 30m, 60m variants)
  - [ ] `lunch_zone_flag`: 12:00–14:00 dead-zone indicator
  - [ ] `close_auction_flag`: last 15m of session
- [ ] Repeatable Thai-market patterns documented in feature comments

### 2.4 Market Structure Features

- [ ] `src/tfex_s50_multi_tf_swing/features/structure.py`
  - [ ] `overnight_gap`: gap vs prior session close
  - [ ] `prev_day_high_low`: distance to previous day's H/L in ATR units
  - [ ] `initial_balance_range`: IB high/low from first hour
  - [ ] `liquidity_levels`: swept-high / swept-low markers

### 2.5 Regime Features

- [ ] `src/tfex_s50_multi_tf_swing/features/regime.py`
  - [ ] `realised_vol_percentile` (rolling N-day rank)
  - [ ] `trend_persistence` (rolling sign agreement)
  - [ ] `range_compression` (low ATR + low ADX flag)
  - [ ] `volume_expansion`

### 2.6 Feature Pipeline

- [ ] `src/tfex_s50_multi_tf_swing/features/pipeline.py`
  - [ ] Combine into panel keyed by `(timestamp, timeframe)`
  - [ ] Winsorise outliers at 1st / 99th percentile
  - [ ] z-score normalise on a trailing window (no look-ahead)
- [ ] Unit test: no data leakage across rolling windows

**Exit criteria:** feature panel materialised under `data/features/`, all features
have unit tests, feature stability notebook shows no breakdown across rollovers.

---

## Phase 3 — Regime Detection

> Goal: classify every bar into one of five regimes so downstream strategies can
> turn themselves on or off. Regime awareness is the single largest source of edge.

### 3.1 Rule-Based Baseline

- [ ] `src/tfex_s50_multi_tf_swing/regime/rules.py`
  - [ ] Classify into `trend_up`, `trend_down`, `range_low_vol`, `range_high_vol`, `panic`
  - [ ] Rule set documented in `.claude/knowledge/regime-detection.md`
- [ ] Unit tests on labelled synthetic series

### 3.2 Clustering Step (optional intermediate)

- [ ] `notebooks/03_regime_clustering.ipynb` — KMeans / Gaussian Mixture on regime
  feature vector; visual comparison against rule-based labels

### 3.3 LightGBM Classifier

- [ ] `src/tfex_s50_multi_tf_swing/regime/model.py`
  - [ ] LightGBM multi-class classifier
  - [ ] Trained on rule-based labels as weak supervision, then refined with
    hand-curated regime windows
  - [ ] Walk-forward retrain schedule (quarterly)
- [ ] Confusion matrix and regime transition stability notebook

### 3.4 Regime-to-Strategy Mapping

- [ ] `src/tfex_s50_multi_tf_swing/regime/policy.py` — `regime_to_strategies()` returning
  the allowed strategy set per regime:
  - [ ] `trend_up / trend_down` → A (pullback continuation), B (opening-range breakout)
  - [ ] `range_high_vol` → C (liquidity sweep reversal)
  - [ ] `range_low_vol` → no trade
  - [ ] `panic` → reduced size (50%) or no trade
- [ ] Unit test: every regime maps to a defined policy

**Exit criteria:** regime classifier with > 70% agreement vs hand-labelled regimes
on a held-out year; "no trade" regimes correctly suppress signals; regime-to-strategy
policy table green-flagged.

---

## Phase 4 — Higher-Timeframe Bias Engine (4H)

> Goal: reduce bad trades by enforcing alignment with the dominant 4H trend before
> any setup is considered. The bias engine *vetoes* trades; it does not generate them.

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
  - [ ] Consumes live 5m bars
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

- **Active phase:** Phase 0 — Project Bootstrap & Gateway Onboarding
- **Completed sub-phases:** 0.1 (repo + tooling) and 0.2 (roadmap + agent context)
  as of 2026-05-27.
- **Blocked by:** nothing. Next: Phase 0.3 (gateway / DB registration) requires
  coordinated PRs in `quant-api-gateway` and `quant-infra-db`.

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
