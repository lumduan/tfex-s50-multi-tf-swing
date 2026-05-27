# Feature Engineering

Features are the real edge — not the model. Every feature group below has a defined
purpose and a normalisation rule. New features must be added with a unit test and a
rationale, not by indicator-hunting.

## Conventions

- **Normalisation**: distance-style features are normalised by ATR (regime-invariant).
- **Slopes**: `slope(EMA, n) = (EMA_t − EMA_{t-n}) / n`.
- **Cross-window stats**: z-scored on a trailing window with no look-ahead.
- **Winsorising**: outlier-clip at 1st / 99th percentile per rolling window.
- All features are **tz-aware** and respect the Thai-market session calendar.

## Feature groups

### Trend

| Feature | Formula / notes |
| --- | --- |
| `ema_slope_{n}` | `(EMA_t − EMA_{t−n}) / n`, normalised by ATR |
| `structure` | HH/HL/LH/LL classification from swing pivots (configurable lookback) |
| `dist_from_vwap` | `(price − VWAP_session) / ATR` |

### Volatility

| Feature | Formula / notes |
| --- | --- |
| `atr_ratio` | `ATR_short / ATR_long` (expansion / compression detector) |
| `bollinger_squeeze` | Bollinger-band width vs Keltner-channel width |
| `realised_vol_{h}` | Rolling realised vol at horizon `h` (5m, 15m, 1H, 1D) |

### Time-of-Day (TFEX is the world of repeating Thai-market patterns)

| Feature | Formula / notes |
| --- | --- |
| `opening_range_{w}` | High/low of first `w` minutes after open (15m / 30m / 60m) |
| `lunch_zone_flag` | 1 during 12:00–14:00 (dead-zone) |
| `close_auction_flag` | 1 during last 15m of session |
| `session_phase` | categorical: pre-open / open / mid-morning / lunch / afternoon / pre-close / night |

### Market Structure

| Feature | Formula / notes |
| --- | --- |
| `overnight_gap` | `(open_today − close_yesterday) / ATR` |
| `dist_to_prev_high` | `(price − prev_day_high) / ATR` (and `_low` variant) |
| `initial_balance_high/low` | IB extremes from first hour |
| `liquidity_sweep_flag` | 1 when the bar pierces a recent swing high/low and reverses within `k` bars |

### Regime

| Feature | Formula / notes |
| --- | --- |
| `rv_percentile` | Rolling N-day percentile of realised vol |
| `trend_persistence` | Rolling sign-agreement of returns |
| `range_compression` | low ATR + low ADX flag |
| `volume_expansion` | Volume z-score on session window |

## Pipeline rules

- Combine all features into a panel keyed by `(timestamp, timeframe)`.
- Winsorise then z-score using **trailing windows only**.
- Save features to `data/features/<timeframe>.parquet`, partitioned by date.
- Each feature group lives in its own module under `src/tfex_s50_multi_tf_swing/features/`.

## What NOT to do

- Do not z-score across the whole dataset (look-ahead bias).
- Do not invent features without a hypothesis. Indicator-hunting overfits.
- Do not use future bars in any rolling stat.
- Do not stack features that are near-perfectly correlated — check the correlation
  matrix before adding.
