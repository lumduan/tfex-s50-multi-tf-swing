"""Manual end-to-end verification of the Phase 5.1 sim trade loop.

Submits an ENTRY then an EXIT through the gateway proxy to the Execution engine
SimAdapter in **one invocation** (two instructions against the evolving position),
and prints the resulting outcomes + final sim position. Public-safe: no secret is
ever printed.

The two legs exercise both position effects in a single run:

1. ENTRY  — a ``long`` order for ``contracts`` → ``position_effect=OPEN``, opening
   a long position of ``contracts`` at ``price``.
2. EXIT   — a ``short`` order for ``contracts`` → ``position_effect=CLOSE``, closing
   the long position back to flat.

Prerequisites (env):

    TFEX_S50_MULTI_TF_SWING_EXECUTION_MODE=sim
    TFEX_S50_MULTI_TF_SWING_EXECUTION_ACCOUNT=SIM-...
    TFEX_S50_MULTI_TF_SWING_GATEWAY_BASE_URL=http://localhost:8080
    TFEX_S50_MULTI_TF_SWING_GATEWAY_API_KEY=<shared internal key>

Example:

    uv run python scripts/verify_execution_sim.py --symbol S50Z2026 --contracts 1 \
        --price 970.0

Exit code 0 only when **both** legs reach FILLED, the entry leg fills exactly
``contracts`` at ``price`` (the intermediate long position), and the final position
is flat (``None``).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from decimal import Decimal

from tfex_s50_multi_tf_swing.config.settings import Settings
from tfex_s50_multi_tf_swing.execution.models import OrderInstruction
from tfex_s50_multi_tf_swing.execution.sim_loop import run_sim_loop

logger: logging.Logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the Phase 5.1 sim trade loop (TFEX).")
    parser.add_argument("--symbol", required=True, help="Dated TFEX contract, e.g. S50Z2026")
    parser.add_argument("--contracts", required=True, type=int, help="Number of S50 contracts")
    parser.add_argument("--price", required=True, help="Limit price (decimal string)")
    parser.add_argument(
        "--timeout", type=float, default=30.0, help="Per-order terminal-state timeout (s)"
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    if settings.execution_mode != "sim":
        logger.error(
            "TFEX_S50_MULTI_TF_SWING_EXECUTION_MODE must be 'sim' for this script (got %r)",
            settings.execution_mode,
        )
        return 2

    price = Decimal(args.price)
    entry = OrderInstruction(
        symbol=args.symbol, direction="long", contracts=args.contracts, limit_price=price
    )
    exit_ = OrderInstruction(
        symbol=args.symbol, direction="short", contracts=args.contracts, limit_price=price
    )

    result = await run_sim_loop(
        [entry, exit_],
        settings=settings,
        position=None,
        order_timeout_seconds=args.timeout,
    )

    if len(result.outcomes) != 2:
        logger.error("expected exactly two outcomes (entry + exit), got %d", len(result.outcomes))
        return 1
    entry_out, exit_out = result.outcomes
    for label, out in (("entry", entry_out), ("exit", exit_out)):
        logger.info("--- %s leg ---", label)
        logger.info("client_order_id : %s", out.client_order_id)
        logger.info("position_effect : %s", out.position_effect)
        logger.info("final_state     : %s", out.final_state)
        logger.info("filled_qty      : %d", out.filled_qty)
        logger.info("avg_fill_price  : %s", out.avg_fill_price)
        if out.rejected:
            logger.info("reject_code     : %s", out.reject_code)
            logger.info("reject_message  : %s", out.reject_message)

    final = result.position
    logger.info(
        "final position  : %s",
        "flat"
        if final is None
        else f"{final.direction} contracts={final.contracts} avg={final.avg_entry}",
    )

    entry_ok = (
        entry_out.position_effect == "OPEN"
        and entry_out.final_state == "FILLED"
        and entry_out.filled_qty == args.contracts
        and entry_out.avg_fill_price == price
    )
    exit_ok = exit_out.position_effect == "CLOSE" and exit_out.final_state == "FILLED"
    flat_ok = final is None

    if entry_ok and exit_ok and flat_ok:
        logger.info(
            "VERIFY OK: entry OPEN→FILLED (long %d @ %s), exit CLOSE→FILLED, position flat.",
            args.contracts,
            price,
        )
        return 0
    logger.error(
        "VERIFY FAILED: entry_ok=%s exit_ok=%s flat_ok=%s",
        entry_ok,
        exit_ok,
        flat_ok,
    )
    return 1


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
