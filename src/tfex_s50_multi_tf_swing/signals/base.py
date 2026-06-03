"""Shared helpers for the three setup strategies (§5.1–5.3).

Each strategy module follows the bias/regime shape — a vectorised ``classify_frame`` that
appends the output columns below, a scalar ``classify_row`` mirror, and a ``to_signals``
materialiser. This module holds what they share: the output-column names, the regime-whitelist
lookup (reusing the Phase-3 policy), input validation, the reason-string builders (one source of
truth so the frame and row paths emit identical strings), and the frame → ``SetupSignal``
materialiser.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

import polars as pl

from tfex_s50_multi_tf_swing.regime.models import REGIMES, Regime
from tfex_s50_multi_tf_swing.regime.policy import regime_to_strategies
from tfex_s50_multi_tf_swing.signals.errors import SignalInputError
from tfex_s50_multi_tf_swing.signals.inputs import COL_BIAS, COL_REGIME
from tfex_s50_multi_tf_swing.signals.models import (
    NO_SIGNAL,
    SetupDirection,
    SetupSignal,
    StrategyId,
)

# Output columns a ``classify_frame`` appends.
SIGNAL: str = "signal"
REASONS: str = "reasons"
TRIGGER_PRICE: str = "trigger_price"
STOP_REFERENCE: str = "stop_reference"
_OUTPUT_COLUMNS: tuple[str, ...] = (SIGNAL, REASONS, TRIGGER_PRICE, STOP_REFERENCE)


def regimes_allowing(strategy_id: StrategyId) -> list[Regime]:
    """Regimes whose Phase-3 policy whitelists ``strategy_id`` (reuses ``regime_to_strategies``)."""
    return [r for r in REGIMES if strategy_id in regime_to_strategies(r)]


def require_columns(df: pl.DataFrame, required: Sequence[str], *, what: str) -> None:
    """Raise :class:`SignalInputError` if ``df`` is missing any of ``required``."""
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise SignalInputError(f"{what} missing columns: {sorted(missing)}")


def direction_expr(long_gate: pl.Expr, short_gate: pl.Expr) -> pl.Expr:
    """Mutually-exclusive direction column: ``long`` / ``short`` / :data:`NO_SIGNAL`."""
    return (
        pl.when(long_gate)
        .then(pl.lit("long"))
        .when(short_gate)
        .then(pl.lit("short"))
        .otherwise(pl.lit(NO_SIGNAL))
    )


def price_expr(long_gate: pl.Expr, short_gate: pl.Expr, *, on_long: str, on_short: str) -> pl.Expr:
    """Pick a price column per direction (``None`` when no setup fired)."""
    return (
        pl.when(long_gate)
        .then(pl.col(on_long))
        .when(short_gate)
        .then(pl.col(on_short))
        .otherwise(None)
    )


def reasons_expr(strategy_id: StrategyId, long_gate: pl.Expr, short_gate: pl.Expr) -> pl.Expr:
    """Auditable reason list, identical to :func:`row_reasons` for the same inputs.

    Fired rows record ``"<id> <dir> setup"`` + the bias and regime context; non-fired rows
    record a single ``"<id> no setup"`` marker.
    """
    fired = long_gate | short_gate
    return (
        pl.when(fired)
        .then(
            pl.concat_list(
                pl.format(
                    "{} {} setup", pl.lit(strategy_id), direction_expr(long_gate, short_gate)
                ),
                pl.format("bias={}", COL_BIAS),
                pl.format("regime={}", COL_REGIME),
            )
        )
        .otherwise(pl.concat_list(pl.format("{} no setup", pl.lit(strategy_id))))
    )


def row_reasons(
    strategy_id: StrategyId,
    direction: SetupDirection | None,
    *,
    bias: str,
    regime: Regime | None,
) -> list[str]:
    """Scalar mirror of :func:`reasons_expr`."""
    if direction is None:
        return [f"{strategy_id} no setup"]
    return [f"{strategy_id} {direction} setup", f"bias={bias}", f"regime={regime}"]


def to_signals(df: pl.DataFrame, *, strategy_id: StrategyId) -> list[SetupSignal]:
    """Materialise one :class:`SetupSignal` per fired row of a classified frame."""
    require_columns(df, ("time", *_OUTPUT_COLUMNS), what="classified frame")
    signals: list[SetupSignal] = []
    for row in df.iter_rows(named=True):
        direction = row[SIGNAL]
        if direction is None or direction == NO_SIGNAL:
            continue
        signals.append(
            SetupSignal(
                strategy_id=strategy_id,
                time=row["time"],
                direction=direction,
                trigger_price=_to_decimal(row[TRIGGER_PRICE]),
                stop_reference=_to_decimal(row[STOP_REFERENCE]),
                regime=row.get(COL_REGIME),
                reasons=list(row[REASONS]) if row[REASONS] is not None else [],
            )
        )
    return signals


def _to_decimal(value: float | int | Decimal | None) -> Decimal:
    """Cast a Float64 price to Decimal at the model boundary (money rule)."""
    if value is None:
        raise SignalInputError("fired signal has a null trigger/stop price")
    return Decimal(str(value))


# Null-safe scalar comparisons for ``classify_row`` (a ``None`` input always fails its gate).
def le(x: float | None, threshold: float) -> bool:
    """``x <= threshold`` with ``None`` treated as a failed gate."""
    return x is not None and x <= threshold


def ge(x: float | None, threshold: float) -> bool:
    """``x >= threshold`` with ``None`` treated as a failed gate."""
    return x is not None and x >= threshold


def gt(x: float | None, threshold: float) -> bool:
    """``x > threshold`` with ``None`` treated as a failed gate."""
    return x is not None and x > threshold


def lt(x: float | None, threshold: float) -> bool:
    """``x < threshold`` with ``None`` treated as a failed gate."""
    return x is not None and x < threshold


__all__: list[str] = [
    "REASONS",
    "SIGNAL",
    "STOP_REFERENCE",
    "TRIGGER_PRICE",
    "direction_expr",
    "ge",
    "gt",
    "le",
    "lt",
    "price_expr",
    "reasons_expr",
    "regimes_allowing",
    "require_columns",
    "row_reasons",
    "to_signals",
]
