"""Regime → strategy / size policy (ROADMAP §3.4).

Encodes the policy table from ``.claude/knowledge/regime-detection.md``:

==================  =========================================  ============
Regime              Strategies allowed                         Size
==================  =========================================  ============
``trend_up``        A (pullback), B (opening-range) — long      full (1.0)
``trend_down``      A, B — short                                full (1.0)
``range_high_vol``  C (liquidity-sweep reversal)                full (1.0)
``range_low_vol``   none — no trade                             0.0
``panic``           none by default; ≤ 50 % if a clear setup    0.5
==================  =========================================  ============

The 12:00–14:00 lunch dead-zone is a no-trade *condition* layered on top of the regime
(see :func:`is_no_trade`), not a sixth regime — the five-label taxonomy stays intact.
"""

from __future__ import annotations

from tfex_s50_multi_tf_swing.regime.errors import UnknownRegimeError
from tfex_s50_multi_tf_swing.regime.models import REGIMES, Regime, RegimePolicy

_POLICY: dict[Regime, RegimePolicy] = {
    "trend_up": RegimePolicy(
        regime="trend_up",
        allowed_strategies=frozenset({"A", "B"}),
        size_multiplier=1.0,
        direction="long",
    ),
    "trend_down": RegimePolicy(
        regime="trend_down",
        allowed_strategies=frozenset({"A", "B"}),
        size_multiplier=1.0,
        direction="short",
    ),
    "range_high_vol": RegimePolicy(
        regime="range_high_vol",
        allowed_strategies=frozenset({"C"}),
        size_multiplier=1.0,
        direction="both",
    ),
    "range_low_vol": RegimePolicy(
        regime="range_low_vol",
        allowed_strategies=frozenset(),
        size_multiplier=0.0,
        direction="none",
    ),
    "panic": RegimePolicy(
        regime="panic",
        allowed_strategies=frozenset(),
        size_multiplier=0.5,
        direction="none",
    ),
}


def regime_policy(regime: Regime) -> RegimePolicy:
    """Return the full :class:`RegimePolicy` for ``regime``.

    Raises :class:`UnknownRegimeError` for any label outside :data:`REGIMES`.
    """
    try:
        return _POLICY[regime]
    except KeyError as exc:
        raise UnknownRegimeError(
            f"no policy for regime {regime!r}; expected one of {REGIMES}"
        ) from exc


def regime_to_strategies(regime: Regime) -> frozenset[str]:
    """Return the set of strategy ids allowed to trade in ``regime``."""
    return regime_policy(regime).allowed_strategies


def regime_to_size_multiplier(regime: Regime) -> float:
    """Return the position-size multiplier for ``regime`` (1.0 full, 0.0 no-trade)."""
    return regime_policy(regime).size_multiplier


def is_no_trade(regime: Regime, *, lunch_zone: bool = False) -> bool:
    """Return ``True`` when no new entries are allowed.

    No-trade when the lunch dead-zone is active, when the regime whitelists no
    strategy, or when its size multiplier is zero.
    """
    if lunch_zone:
        return True
    policy = regime_policy(regime)
    return not policy.allowed_strategies or policy.size_multiplier == 0.0


__all__: list[str] = [
    "is_no_trade",
    "regime_policy",
    "regime_to_size_multiplier",
    "regime_to_strategies",
]
