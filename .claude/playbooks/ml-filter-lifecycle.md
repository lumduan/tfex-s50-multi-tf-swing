# Playbook — ML probability filter lifecycle (train → audit → version → enable)

How to train, evaluate, version, and roll out the Phase-6 ML probability filter. The filter
is **OFF by default**; with it off (or no model artifact present) the strategy behaves exactly
as Phase 5. See `.claude/knowledge/ml-filter.md` and
`docs/plans/phase-6-ml-probability-filter.md`.

> **Data-gated.** A *real* shippable model needs the 5-year TFEX backfill (blocked on a tvkit
> token / engine TFEX data). Until then, train only on the synthetic public-safe demo path.
> Never commit a model binary or a tvkit cookie — `data/models/` and `data/labels/` are gitignored.

## 0. Golden rules

- ML is a **filter, not a strategy** (hard rule #7) — it gates fired setups, never invents trades.
- **Walk-forward only**, never a random split (hard rule #6).
- A model with no economic story does not ship. `trend_continuation` keeps held continuations;
  `fake_breakout` drops failed breakouts.
- Out-of-sample metrics are required to ship; in-sample numbers are not evidence.

## 1. Run the end-to-end demo (synthetic, public-safe)

```bash
uv run python scripts/ml_filter_demo.py   # detect → label → walk-forward train → save → load → filter → A/B backtest
```

Writes a public-safe artifact (counts + R-multiple + OOS metrics only) to
`results/static/ml/filter_demo.json`. Use it as the reference for the owner pipeline below.

## 2. Owner pipeline (private mode, real data — when the backfill lands)

```python
from functools import partial
from pathlib import Path

from tfex_s50_multi_tf_swing.ml import features as feat
from tfex_s50_multi_tf_swing.ml.labels import label_triple_barrier
from tfex_s50_multi_tf_swing.ml.training import walk_forward_train
from tfex_s50_multi_tf_swing.ml.store import save_model, load_bundle
from tfex_s50_multi_tf_swing.ml.filter import filter_signals
from tfex_s50_multi_tf_swing.config.settings import get_settings

# 1. Detect setups on the aligned 5m frame, then label them (triple-barrier).
labels = label_triple_barrier(signals, bars).filter(pl.col("target") == "fake_breakout")
times = labels.get_column("time").to_list()

# 2. Build the fixed feature matrix and walk-forward train (per target).
matrix = feat.build_feature_frame(aligned, times)
result = walk_forward_train(matrix, labels.get_column("label").to_numpy(), times,
                            target="fake_breakout", threshold=0.50, seed=42)
#    walk_forward_train RAISES ImportanceAuditError if one feature dominates (leakage).

# 3. Inspect OOS metrics + importances BEFORE shipping.
print(result.card.oos_metrics, result.importances)

# 4. Version the artifact (text dump + ModelCard JSON) under the gitignored model dir.
save_model(result.model, result.card, Path("data/models"))
```

Repeat per target (`trend_continuation` for A/B, `fake_breakout` for C). Ship a model only
if its OOS expectancy / profit factor beats the unfiltered ruleset on a held-out window and
no regime is worse with the filter on.

## 3. Enable the filter

Set in `.env` (owner mode):

```
TFEX_S50_MULTI_TF_SWING_ML_FILTER_ENABLED=true
TFEX_S50_MULTI_TF_SWING_ML_MODEL_DIR=./data/models
TFEX_S50_MULTI_TF_SWING_ML_THRESHOLD_CONTINUATION=0.55
TFEX_S50_MULTI_TF_SWING_ML_THRESHOLD_FAKE_BREAKOUT=0.50
```

Then bind the config + loaded bundle into the backtest hook:

```python
settings = get_settings()
config = settings.ml_filter_config()
bundle = load_bundle(config.model_dir)
gate = partial(filter_signals, config=config, bundle=bundle)
metrics = run_per_strategy_backtest(detect, aligned, bars, strategy_id="C", ml_filter=gate)
```

## 4. Rollback

Set `TFEX_S50_MULTI_TF_SWING_ML_FILTER_ENABLED=false` (or unset it), or remove the artifacts
from `data/models/`. Either restores Phase-5 behaviour byte-for-byte — no code change, no
migration. There is no gateway / ingestion-contract impact (any future ML telemetry belongs in
`extended_data`, never new gateway columns).

## 5. Quality gate (before any push)

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest
```

`ml/` is in the ≥ 90 % coverage gate. Re-run `ruff format --check` after any post-format edit.
