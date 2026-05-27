# Strategy Overview — TFEX S50 Multi-TF Swing Intraday Quant System

## Why start from S50 (single instrument)

The hardest problem in quant trading is not "finding markets to trade" but **managing
complexity**. Starting from a single instrument is the well-trodden hedge-fund path:
single market → single instrument → single strategy → expand only with evidence.

| Reason | Detail |
| --- | --- |
| Stable behavioural patterns | S50 has repeating intraday patterns — opening volatility, lunch slowdown, gap fills, foreign-flow impact — that suit statistical learning. |
| Adequate liquidity | No impact-cost / liquidity-trap problems like in small-cap equities. |
| Tractable feature engineering | Multi-asset too early creates synchronisation, timezone, alignment, and correlation-instability problems we cannot debug yet. |
| Fast research cycle | One instrument means we can iterate: hypothesis → test → retrain → deploy → evaluate quickly. |

## Core thesis

A good TFEX quant system "doesn't trade often" — it is boring, conservative, and built
to survive across regimes. Real edge comes from:

1. **Regime awareness** — knowing which regime we are in and which trades to skip.
2. **Cost efficiency** — minimising commission, slippage, and spread leakage.
3. **Risk management** — surviving the worst sequences, not maximising the best.
4. **Execution quality** — entries and exits aligned with structure and volatility.

It does **not** come from a "secret indicator" or an AI that "predicts the next
candle with 95% accuracy." Anyone who tells you otherwise is selling something.

**Scale only on statistical evidence, never on confidence.**

## System architecture (5 layers)

```
┌──────────────────────────────────────────────┐
│  Raw Market Data (multi-TF OHLCV)             │
│  4H → Regime / Macro Bias                     │
│  1H → Main Setup Detection                    │
│  5m → Execution & Risk Optimisation           │
└─────────────────────┬────────────────────────┘
                      │
┌─────────────────────▼────────────────────────┐
│  Data Layer                                   │
│  - Continuous Futures Contract                │
│  - Feature Engineering                        │
│  - Validation Pipeline                        │
└─────────────────────┬────────────────────────┘
                      │
┌─────────────────────▼────────────────────────┐
│  Intelligence Layer                           │
│  - Regime Detection                           │
│  - Higher-TF Bias Engine                      │
│  - ML Probability Filter                      │
└─────────────────────┬────────────────────────┘
                      │
┌─────────────────────▼────────────────────────┐
│  Execution Layer                              │
│  - Setup Detection (Strategies A / B / C)     │
│  - Execution Engine (5m)                      │
│  - Risk Engine                                │
└─────────────────────┬────────────────────────┘
                      │
┌─────────────────────▼────────────────────────┐
│  Validation & Deployment                      │
│  - Walk-Forward Backtest                      │
│  - Paper Trading                              │
│  - Live Trading                               │
└──────────────────────────────────────────────┘
```

## System goal

The system does not predict the next candle. It hunts for **setups with positive
expectancy**, gated by:

- Higher-timeframe alignment.
- Volatility context.
- Execution optimisation.
- Probability filtering (ML).

A "no trade" decision is a feature. Discipline > activity.

## Cross-references

- Phase plan — [`docs/plans/ROADMAP.md`](../../docs/plans/ROADMAP.md)
- Feature panel — [`feature-engineering.md`](feature-engineering.md)
- Regimes — [`regime-detection.md`](regime-detection.md)
- Strategies — [`strategy-design.md`](strategy-design.md)
- Risk — [`risk-engine.md`](risk-engine.md)
- ML filter — [`ml-filter.md`](ml-filter.md)
- Backtest protocol — [`backtest-protocol.md`](backtest-protocol.md)
