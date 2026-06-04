# Backtest Protocol

A backtest is a hypothesis test against history. Treat it as evidence, not as proof.

## Cardinal rule: no random splits, ever

Use **anchored walk-forward** windows. Example schedule:

```
train: 2016 – 2021   →   test: 2022
train: 2017 – 2022   →   test: 2023
train: 2018 – 2023   →   test: 2024
```

Random splits and k-fold leak future information into past decisions. They produce
beautiful backtests and unprofitable live systems.

## Cost realism

Every backtest must simulate **all** of:

- Commission (per-contract fee + clearing fee)
- Slippage — ATR-scaled and worse on illiquid sessions (night session, around lunch)
- Spread (tick-based)
- Margin requirement and overnight financing where applicable

A backtest without costs is a marketing exercise.

## Success metrics

| Metric | Why it matters |
| --- | --- |
| Expectancy (R per trade) | Measures real edge — must be positive after costs |
| Max drawdown (depth, duration, recovery) | Measures survivability |
| Profit factor | Quality of winners vs losers |
| Regime-stratified expectancy | Robustness — fails if one regime carries everything |
| Sharpe / Sortino (per period) | Risk-adjusted return |
| Turnover / cost as % of return | Edge vs friction ratio |

## Anti-patterns

- Picking the best-performing parameter set on a single window — that is overfitting.
- Re-using the test window for parameter tuning — leakage.
- Hiding negative regimes by aggregating across the whole sample.
- Smoothing the equity curve with implausible execution assumptions.
- "Just one more feature" until the backtest looks good — stop and walk away when
  the hypothesis breaks.

## Reporting expectations

Every backtest run produces:

- An equity curve (NAV indexed to 100), benchmarked against S50 buy-and-hold.
- A drawdown chart with regime overlay.
- A regime-stratified PnL table.
- A trade-distribution histogram (R per trade).
- A sensitivity sweep on the two or three most influential parameters.

Saved under `results/static/backtest/` (public-safe — no raw OHLCV).

## Phase 8 implementation (the concrete harness)

The protocol above is realised by the `backtest/` leaf package (shipped 2026-06-04):

- **Harness** — `backtest/walk_forward.py`. `generate_windows` is deterministic (anchored default,
  `train_end ≤ test_start`, no RNG / wall-clock). `drive_costed_trades` is the **only place
  `risk.decision.evaluate_entry` is driven**: it sizes each trade, skips the disallowed ones (kill
  switch / session halt / no-trade regime / sub-1 contract), and folds **net** R into the session.
  The combined A+B+C run shares **one** daily `SessionRiskState`; per-strategy runs are isolated.
  **The capital ladder caps `paper` to 0 contracts — a backtest runs at `micro_live`+.**
- **Cost model** — `backtest/costs.py`. `CostModel` (frozen): `commission_per_contract` +
  `clearing_fee_per_contract` (`Decimal`, round-trip per contract), `slippage_atr_mult` +
  `illiquid_session_mult` (float), `tick_size` (`Decimal`) + `spread_ticks` (float). `apply_costs`
  folds every cost into **points per contract**:
  `cost_points = slippage_atr_mult·atr·(illiquid? mult) + spread_ticks·tick_size +
  (commission+clearing)/S50_MULTIPLIER`. Illiquid = night session or the 12:00–14:00 lunch edge
  (`data/session.py`). `CostedTrade.net_trade` re-exposes a `Trade` with net PnL so every existing
  R-multiple metric runs unchanged.
- **Metrics** — `backtest/metrics.py` adds `drawdown_profile` (depth + time-underwater + recovery),
  `sharpe` / `sortino` / `period_ratios` (per-period net-R, float), and `regime_concentration`
  (fails loudly when one regime's share of total |expectancy contribution| exceeds the threshold).
- **Artifact contract** — `results/static/backtest/walk_forward.json` carries the config summary,
  the combined + per-strategy results (counts, R-metrics, profit factor, drawdown profile,
  Sharpe/Sortino, regime concentration, NAV index), and per-window summaries. **Never** the equity
  curve array (it would trip the >400-numeric-array heuristic and is rebuilt in the notebook) and
  **never** any OHLCV column. The public-data-boundary test enforces both.
- **Data source** — `backtest/data_source.py` reads the engine's offline Parquet snapshot
  (`ParquetStore`), never tvkit; raises `WalkForwardDataError` when a frame is missing/empty.
- **The exit-criteria magnitudes are data-gated** on the 5-year TFEX backfill + engine TFEX data —
  the harness + a synthetic demonstration ship now; never fake a backtest or a magnitude claim.
