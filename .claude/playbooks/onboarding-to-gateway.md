# Gateway Onboarding Playbook

Concrete checklist for wiring this strategy into the umbrella `quant-api-gateway`,
specialised from the umbrella's `STRATEGY_ONBOARDING.md` to the values this strategy
uses.

## Canonical names

| Surface | Value |
| --- | --- |
| Slug (folder, repo, `strategy_id`) | `tfex-s50-multi-tf-swing` |
| Module path | `src/tfex_s50_multi_tf_swing/` |
| Strategy type discriminator | `TFEX_DERIVATIVES` |
| Postgres DB name | `db_tfex_s50_multi_tf_swing` |
| Env var prefix | `TFEX_S50_MULTI_TF_SWING_` |
| Docker service name | `quant-tfex-s50-multi-tf-swing` |
| Host port | `:8200` |
| Gateway service URL (inside network) | `http://quant-tfex-s50-multi-tf-swing:8000` |

## Required env vars

```bash
TFEX_S50_MULTI_TF_SWING_PUBLIC_MODE=true        # docker default; flip to false for owner mode
TFEX_S50_MULTI_TF_SWING_DB_WRITE_ENABLED=true
TFEX_S50_MULTI_TF_SWING_DB_TFEX_S50_MULTI_TF_SWING_DSN=postgresql://...
TFEX_S50_MULTI_TF_SWING_GATEWAY_BASE_URL=http://quant-api-gateway:8000
TFEX_S50_MULTI_TF_SWING_GATEWAY_API_KEY=<shared-with-gateway>
```

## Database init script

Add to `quant-infra-db/init-scripts/0X_schema_db_tfex_s50_multi_tf_swing.sql`:

```sql
\c db_tfex_s50_multi_tf_swing;

CREATE TABLE IF NOT EXISTS equity_curve (
    time          TIMESTAMPTZ      NOT NULL,
    strategy_id   TEXT             NOT NULL,
    value         NUMERIC(18, 4)   NOT NULL,
    PRIMARY KEY (time, strategy_id)
);
SELECT create_hypertable('equity_curve', 'time', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS trade_history (
    trade_time    TIMESTAMPTZ      NOT NULL,
    strategy_id   TEXT             NOT NULL,
    symbol        TEXT             NOT NULL,     -- e.g. 'S50Z25'
    side          TEXT             NOT NULL,     -- 'BUY' / 'SELL'
    contracts     INTEGER          NOT NULL,
    price         NUMERIC(18, 4)   NOT NULL,
    margin_used   NUMERIC(18, 4)   NOT NULL,
    pnl           NUMERIC(18, 4),
    PRIMARY KEY (trade_time, strategy_id, symbol, side)
);

CREATE TABLE IF NOT EXISTS backtest_log (
    run_id        TEXT             PRIMARY KEY,
    run_time      TIMESTAMPTZ      NOT NULL,
    metrics       JSONB            NOT NULL
);

CREATE TABLE IF NOT EXISTS benchmark_equity_curve (
    time          TIMESTAMPTZ      NOT NULL,
    benchmark     TEXT             NOT NULL,     -- 'SET50_TR' or 'S50_UNDERLYING'
    value         NUMERIC(18, 4)   NOT NULL,
    PRIMARY KEY (time, benchmark)
);
```

## Gateway registration

In `quant-api-gateway/strategies.json`:

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

Set `active: false` until the service has at least one successful paper-trading
cycle. Flip to `active: true` only when daily reports are flowing cleanly.

## Ingestion contract

Daily report shape (POST to `quant-api-gateway/api/v1/ingest/daily-report`,
header `X-API-Key: $TFEX_S50_MULTI_TF_SWING_GATEWAY_API_KEY`):

```json
{
  "strategy_metadata": {
    "id": "tfex-s50-multi-tf-swing",
    "type": "TFEX_DERIVATIVES",
    "last_updated": "2026-05-27T18:00:00+00:00"
  },
  "performance_metrics": {
    "daily_pnl": "1234.5000",
    "equity_curve": [{"time": "...", "value": "..."}],
    "max_drawdown": "-0.1230",
    "sharpe_ratio": "1.4500"
  },
  "current_exposure": {
    "total_value": "200000.0000",
    "cash_balance": "180000.0000",
    "positions_count": 1
  },
  "extended_data": {
    "report": {
      "margin_usage": "20000.0000",
      "contracts_long": 1,
      "contracts_short": 0,
      "regime": "trend_up"
    },
    "trades": []
  }
}
```

**Wire format requirements**:

- Decimals as strings (no floats anywhere in the payload).
- All timestamps tz-aware UTC (`+00:00`).
- Idempotent — re-posting the same `(strategy_id, date)` is a no-op at the gateway.

## Cross-repo PR sequence (merge in order)

1. `quant-infra-db` — DB init script lands.
2. `quant-api-gateway` — `strategies.json` entry lands (with `active: false`).
3. `tfex-s50-multi-tf-swing` — adapters + Docker compose land.
4. `quant-openbb` — proxy routes for `TFEX_DERIVATIVES` if custom metrics are
   needed.
5. (optional) `quant-dashboard` — adapter, if a custom UI for futures is built.

## Acceptance checklist (Phase 0 done)

- [ ] DB init script merged in `quant-infra-db` and applied
- [ ] `strategies.json` entry merged in `quant-api-gateway`
- [ ] Container builds, joins `quant-network`, `/health` returns 200
- [ ] Empty daily-report POST round-trips with 202 from the gateway
- [ ] Coverage ≥ 90% on `adapters/`
- [ ] All quality gates green: ruff, ruff format, mypy strict, pytest
