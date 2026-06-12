# Execution mode (`TFEX_S50_MULTI_TF_SWING_EXECUTION_MODE`) — tfex-s50-multi-tf-swing

Strategy-side scope of `feature-execution-engine` **Phase 5.1**: an opt-in,
library-only sim trade loop. Instruction → `NormalizedOrder` → `POST /orders` (via the
gateway proxy) → SSE fill events → local `SimPosition`. No broker code lives in this
repo; the Execution engine is the sole order-routing-credential owner. This is a port
of the reviewed csm-set implementation with TFEX deltas (required `position_effect`,
contract-based sizing, an evolving single-direction position).

## Environment variables

| Var | Default | Meaning |
| --- | --- | --- |
| `TFEX_S50_MULTI_TF_SWING_EXECUTION_MODE` | `off` | `off` \| `sim` \| `live`. |
| `TFEX_S50_MULTI_TF_SWING_EXECUTION_ACCOUNT` | — | Broker account stamped on `NormalizedOrder.account`. Required when mode != `off`. |
| `TFEX_S50_MULTI_TF_SWING_EXECUTION_BROKER` | `sim` | `sim` \| `liberator` \| `settrade`. `live` mode sources the venue from this. |
| `TFEX_S50_MULTI_TF_SWING_GATEWAY_BASE_URL` | `http://quant-api-gateway:8000` | Gateway base URL (reused from the daily-report path). Required (non-empty) when mode != `off`. |
| `TFEX_S50_MULTI_TF_SWING_GATEWAY_API_KEY` | `SecretStr("")` | `X-API-Key` for every order request (reused). Required (non-empty secret) when mode != `off`. |

Validation (`Settings._validate_execution_path`, `mode="after"`):

- `off` → always valid, adds no required env (module-level `Settings()` keeps working).
- mode != `off` → requires a non-empty `GATEWAY_BASE_URL`, a non-empty `GATEWAY_API_KEY`
  secret, and `EXECUTION_ACCOUNT` (each with its own `TFEX_S50_MULTI_TF_SWING_`-prefixed
  error).
- `live` + `PUBLIC_MODE=true` → rejected (public mode is read-only). **`public_mode`
  defaults `True` here**, so `sim` is always allowed under it; only `live` is forbidden.
- `live` + `EXECUTION_BROKER=sim` → rejected (live needs a real venue).

Note: `gateway_api_key` is a `SecretStr` with an **empty-string default**, so "missing
key" means an empty secret value (`get_secret_value() == ""`), not `None`.

## Mode semantics

- **off** — zero-code path. The adapter is never instantiated; no HTTP at all.
- **sim** — `run_sim_loop` builds NormalizedOrders, POSTs them through the gateway to
  the engine `SimAdapter`, and applies the SSE fill stream. Default and only
  implemented mode in Phase 5.1.
- **live** — RESERVED. `run_sim_loop` raises `ExecutionModeError` for any mode other
  than `sim`. Settings already forbids `live` in public mode.

## TFEX deltas vs the csm-set port source

- **`market="TFEX"`** is pinned and **`position_effect` is a required field** (no
  default) — the engine rejects a TFEX order without it. `wire_dump()` always emits
  both `market` and `position_effect` (csm omits `position_effect` for SET).
- **`infer_position_effect(position, direction, contracts)`** — OPEN vs CLOSE against
  the current position:
  - no position / zero-contract position / **same** direction → `OPEN`;
  - **opposite** direction with `contracts <= position.contracts` → `CLOSE`;
  - **opposite** direction with `contracts > position.contracts` → a **flip**, which is
    **unsupported in Phase 5.1** → `SimLoopError`.
- **Contracts, not shares/notional.** Sizing happens upstream (the risk engine's
  `PositionSizeResult`); the loop consumes pre-built `OrderInstruction`s and never
  sizes. `build_order_instruction(signal, contracts, *, symbol)` resolves a
  `SetupSignal` (direction + `trigger_price`) into an instruction.
- **Sequential against an evolving position.** Instructions are processed strictly one
  at a time — submit, await terminal, apply to the position, then convert the next — so
  each `position_effect` reflects every prior fill. `side` = BUY for `long`, SELL for
  `short`. The S50 book is single-direction; a flat book is represented as `None`.
- **`broker_order_id` stays `str`** end-to-end even when it arrives as a numeric string
  (e.g. a Settrade TFEX `order_no` like `"123456789"`).
- Exceptions are rooted at the **existing** `ExecutionError(TfexS50Error)` here.

## Adapter (`engine_adapter.py`)

- `STRATEGY_ID = "tfex-s50-multi-tf-swing"`, sent as `X-Strategy-Id` on every request.
- `submit_order`: 200/201 → result (200 = idempotent resend, identical handling). Any
  typed `{"error": {code, message, ...}}` envelope — including an enveloped 503 like
  `kill_switch_engaged` — is **terminal** → `OrderRejectedError` with the original
  code/message (never retried). Bare 5xx (no envelope) and `httpx.HTTPError` → retry the
  **same** cid with backoff, then `EngineAdapterError`.
- `get_order`: same envelope handling; used for residual reconcile.
- `stream_updates`: hand-rolled SSE over `aiter_lines` inside `client.stream(...)`,
  `httpx.Timeout(t, read=None)` (keep-alives ~15 s). Default filters on `strategy_id`.
  `event: resync_required` → `StreamResetError(after_seq)`; `event: gap` → log +
  continue; `:` comments ignored. Client-side seq watermark (skip `seq <= cursor`);
  reconnect sends `Last-Event-ID: <cursor>`. Stream-open typed envelope →
  `OrderRejectedError` (no reconnect); mid-stream drop / clean EOF → backoff +
  reconnect, exhausted → `StreamError`.

## Loop invariants (`sim_loop.py`)

- **Subscribe-before-submit** — the stream-consumer task starts before the first POST,
  inside one `asyncio.TaskGroup`; one stream connection serves the whole run.
- **Single-source fills** — the evolving position moves **only** from stream `fill`
  events; the POST ack never updates it. This kills the ack-already-FILLED + replay
  double-count class (the engine `SimAdapter` can return a FILLED ack and also stream
  the fill).
- **Seq watermark** — the adapter dedupes reconnect replays so a replayed fill is never
  applied twice.
- **VWAP avg_fill_price** — `applied_cost / applied_qty` over the applied fills, never
  the event's top-level `price` (which on the wire is the replace/amend price).
- **Residual reconcile** — on per-order timeout or a degraded (reset) stream,
  `GET /orders/{cid}` and apply only `filled_qty − applied_qty` at `avg_fill_price`. A
  still-non-terminal order records `final_state=None` and the loop completes without
  crashing.
- **Reject mid-batch continues** — a rejected order is recorded (the position is
  unchanged — rejected orders never fill) and the remaining instructions still process.
- **Position roll** — OPEN raises the weighted-average entry + contract count; CLOSE
  reduces the count (avg unchanged); a position at zero contracts becomes flat (`None`).

## Verify runbook

```bash
export TFEX_S50_MULTI_TF_SWING_EXECUTION_MODE=sim
export TFEX_S50_MULTI_TF_SWING_EXECUTION_ACCOUNT=SIM-1
export TFEX_S50_MULTI_TF_SWING_GATEWAY_BASE_URL=http://localhost:8080   # gateway host port
export TFEX_S50_MULTI_TF_SWING_GATEWAY_API_KEY=<shared internal key>
uv run python scripts/verify_execution_sim.py --symbol S50Z2026 --contracts 1 --price 970.0
```

The script runs an **ENTRY then an EXIT in one invocation** (two instructions): a
`long` open (`position_effect=OPEN`) then a `short` close (`position_effect=CLOSE`).
Exit 0 only when both legs reach FILLED, the entry fills exactly `--contracts` at
`--price` (the intermediate long position), and the final position is flat (`None`).
The engine must be in owner-mode sim (`stage: sim, public_mode: false`) for the POST to
be accepted; public mode (`:8400` default) returns 403. The consolidated live e2e
runbook lives in the umbrella plan (`now-i-have-lucky-toucan.md`, step 4).
