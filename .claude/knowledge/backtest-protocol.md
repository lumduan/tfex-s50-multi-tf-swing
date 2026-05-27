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

Saved under `results/backtest/` (public-safe — no raw OHLCV).
