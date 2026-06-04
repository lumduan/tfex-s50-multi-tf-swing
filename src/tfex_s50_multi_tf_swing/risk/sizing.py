"""Position sizing + volatility scaling (ROADMAP §7.1 + §7.3).

The sizing formula is::

    position_size = account_risk / (stop_distance × multiplier)

rounded **down** to whole contracts. A sub-1-contract result is **0** (no trade), never a
rounded-up 1 — rounding up would silently breach the per-trade risk budget. Wider stops shrink
size, so sizing is volatility-scaled by construction; §7.3 adds a further regime / percentile
multiplier on top.

The S50 multiplier (200 THB per index point) is the single named constant
:data:`S50_MULTIPLIER` (TFEX hard rule #1) — every consumer imports it; it is never re-typed
inline. All money arithmetic is exact :class:`~decimal.Decimal`.
"""

from __future__ import annotations

import logging
from decimal import ROUND_DOWN, Decimal
from typing import Final

from tfex_s50_multi_tf_swing.regime.models import Regime
from tfex_s50_multi_tf_swing.regime.policy import regime_to_size_multiplier
from tfex_s50_multi_tf_swing.risk.errors import RiskInputError
from tfex_s50_multi_tf_swing.risk.models import (
    PositionSizeRequest,
    PositionSizeResult,
    RiskConfig,
)

logger = logging.getLogger(__name__)

S50_MULTIPLIER: Final[Decimal] = Decimal("200")
"""THB per S50 index point (TFEX contract spec). The single source of this constant."""

_ONE: Final[Decimal] = Decimal("1")


def volatility_scale_factor(
    rv_percentile: float | None,
    regime: Regime | None,
    config: RiskConfig,
) -> Decimal:
    """Return the size multiplier from regime + realised-vol percentile (ROADMAP §7.3).

    Reuses the already-classified ``regime`` (never re-derives it) via
    :func:`~tfex_s50_multi_tf_swing.regime.policy.regime_to_size_multiplier`, and halves size when
    ``rv_percentile`` reaches ``config.high_vol_percentile``. The final factor is the **stricter**
    (minimum) of the two caps. ``panic`` ⇒ 0 (no trade) when ``config.panic_no_trade`` is set —
    deliberately stricter than the regime policy's "≤ 50 % if a clear setup", because the risk
    engine has the final say at the extreme percentile.
    """
    regime_cap = 1.0 if regime is None else regime_to_size_multiplier(regime)
    if regime == "panic" and config.panic_no_trade:
        regime_cap = 0.0

    percentile_cap = 1.0
    if rv_percentile is not None and rv_percentile >= config.high_vol_percentile:
        percentile_cap = config.high_vol_size_factor

    factor = min(regime_cap, percentile_cap)
    return Decimal(str(factor))


def compute_position_size(
    request: PositionSizeRequest,
    config: RiskConfig,
) -> PositionSizeResult:
    """Size a trade in whole S50 contracts (ROADMAP §7.1).

    Raises :class:`RiskInputError` on non-positive equity or a non-positive stop distance (the
    latter would be a divide-by-zero). Otherwise risks ``config.risk_per_trade_pct`` of equity,
    divides by ``stop_distance × S50_MULTIPLIER``, applies the volatility scale factor, and floors
    to whole contracts (``ROUND_DOWN``); a sub-1 result is 0.
    """
    if request.equity <= 0:
        raise RiskInputError(f"equity must be positive, got {request.equity}")
    if request.stop_distance_points <= 0:
        raise RiskInputError(
            f"stop_distance_points must be positive, got {request.stop_distance_points}"
        )

    risk_amount = request.equity * Decimal(str(config.risk_per_trade_pct))
    scale_factor = volatility_scale_factor(request.rv_percentile, request.regime, config)
    denominator = request.stop_distance_points * S50_MULTIPLIER
    raw_contracts = (risk_amount / denominator) * scale_factor
    contracts = int(raw_contracts.quantize(_ONE, rounding=ROUND_DOWN))

    reasons: list[str] = [f"risk_amount={risk_amount}"]
    if scale_factor != _ONE:
        reasons.append(f"scale_factor={scale_factor}")
    if contracts == 0:
        reasons.append("sub-1-contract → no trade")

    logger.debug(
        "sized %d contract(s): equity=%s stop=%s scale=%s raw=%s",
        contracts,
        request.equity,
        request.stop_distance_points,
        scale_factor,
        raw_contracts,
    )
    return PositionSizeResult(
        contracts=contracts,
        risk_amount=risk_amount,
        scale_factor=scale_factor,
        raw_contracts=raw_contracts,
        reasons=reasons,
    )


__all__: list[str] = [
    "S50_MULTIPLIER",
    "compute_position_size",
    "volatility_scale_factor",
]
