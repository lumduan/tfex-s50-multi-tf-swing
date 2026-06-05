"""Shared fixtures and builders for the ML probability-filter tests.

The filter and training pipeline read a wide *aligned 1H* frame plus a 1H *bars* frame.
Building them through the full data → features pipeline is slow and brittle, so — exactly
like the signal / bias suites — these helpers hand-build deterministic synthetic frames:

* :func:`aligned_frame` — an aligned frame whose ORB bars fire **Strategy B** in alternating
  directions (enough fired setups to walk forward).
* :func:`bars_frame` — the matching 1H execution bars (a triangle price path so triple-barrier
  labels come out *mixed*, not all one class).
* :class:`ConstantModel` — a stub :class:`ProbabilityModel` returning a fixed probability, so
  gate logic can be tested without a real booster.
* :func:`make_card` / :func:`stub_bundle` — assemble a :class:`ModelBundle` from stubs.

Updated for the 1H-execution migration (2026-06-05): uses 1H bars + 1d_bias_direction +
1d_regime. Strategy B (ORB) replaces the permanently-disabled Strategy C.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import numpy.typing as npt
import polars as pl

from tfex_s50_multi_tf_swing.ml.features import FEATURE_COLUMNS
from tfex_s50_multi_tf_swing.ml.models import ModelBundle, ModelCard, ModelTarget
from tfex_s50_multi_tf_swing.signals import strategy_b
from tfex_s50_multi_tf_swing.signals.models import SetupSignal

T0 = datetime(2026, 1, 5, 3, 0, tzinfo=UTC)

ALIGNED_SCHEMA: dict[str, pl.DataType] = {
    "time": pl.Datetime(time_unit="us", time_zone="UTC"),
    "1d_bias_direction": pl.Utf8(),
    "1d_regime": pl.Utf8(),
    "atr_ratio": pl.Float64(),
    "bollinger_squeeze": pl.Float64(),
    "volume_expansion": pl.Float64(),
    "dist_from_vwap": pl.Float64(),
    "structure": pl.Utf8(),
    "close": pl.Float64(),
    "swing_high": pl.Float64(),
    "swing_low": pl.Float64(),
    "or_high_60": pl.Float64(),
    "or_low_60": pl.Float64(),
    "liquidity_sweep_flag": pl.Int8(),
    "lunch_zone_flag": pl.Int8(),
}

_BARS_SCHEMA: dict[str, pl.DataType] = {
    "time": pl.Datetime(time_unit="us", time_zone="UTC"),
    "open": pl.Float64(),
    "high": pl.Float64(),
    "low": pl.Float64(),
    "close": pl.Float64(),
    "atr": pl.Float64(),
}


def _mid(i: int, n: int) -> float:
    """A triangle price path (up then down) with a tiny wiggle — trend dominates the noise."""
    half = n // 2
    ramp = 0.6 * i if i < half else 0.6 * half - 0.6 * (i - half)
    return 1000.0 + ramp + 0.3 * math.sin(i / 8.0)


def aligned_frame(n: int = 40) -> pl.DataFrame:
    """An aligned 1H frame whose every-third bar fires Strategy B (ORB), alternating long/short."""
    rows: list[dict[str, object]] = []
    for i in range(n):
        t = T0 + timedelta(hours=i)
        mid = _mid(i, n)
        is_long = i % 2 == 0
        # Every third bar fires: close breaks out above or_high (long) or below or_low (short).
        fire = i % 3 == 0
        if fire:
            close_val = mid + 2.0 if is_long else mid - 2.0
        else:
            close_val = mid + (0.6 if is_long else -0.6)
        rows.append(
            {
                "time": t,
                "1d_bias_direction": "long" if is_long else "short",
                "1d_regime": "trend_up",
                "atr_ratio": 0.9,
                "bollinger_squeeze": 0.7,
                "volume_expansion": 1.5,
                "dist_from_vwap": 0.5,
                "structure": "HH" if is_long else "LL",
                "close": close_val,
                "swing_high": mid + 6.0,
                "swing_low": mid - 6.0,
                "or_high_60": mid + 1.0,
                "or_low_60": mid - 1.0,
                "liquidity_sweep_flag": 0,
                "lunch_zone_flag": 0,
            }
        )
    return pl.DataFrame(rows, schema=ALIGNED_SCHEMA)


def bars_frame(n: int = 40) -> pl.DataFrame:
    """1H execution bars matching :func:`aligned_frame` (intrabar range under the barrier)."""
    rows: list[dict[str, object]] = []
    for i in range(n):
        t = T0 + timedelta(hours=i)
        mid = _mid(i, n)
        is_long = i % 2 == 0
        rows.append(
            {
                "time": t,
                "open": mid,
                "high": mid + 0.5,
                "low": mid - 0.5,
                "close": mid + (0.6 if is_long else -0.6),
                "atr": 1.0,
            }
        )
    return pl.DataFrame(rows, schema=_BARS_SCHEMA)


def b_signals(frame: pl.DataFrame) -> list[SetupSignal]:
    """Fire Strategy B on an aligned frame."""
    return strategy_b.to_signals(strategy_b.classify_frame(frame))


def make_signal(
    *,
    strategy_id: str = "B",
    minute: int = 0,
    direction: str = "long",
    regime: str | None = "trend_up",
) -> SetupSignal:
    """A minimal :class:`SetupSignal` at ``T0 + minute`` (for filter unit tests)."""
    return SetupSignal(
        strategy_id=strategy_id,  # type: ignore[arg-type]
        time=T0 + timedelta(minutes=minute),
        direction=direction,  # type: ignore[arg-type]
        trigger_price=Decimal("1000.0"),
        stop_reference=Decimal("994.0"),
        regime=regime,  # type: ignore[arg-type]
        reasons=["test"],
    )


class ConstantModel:
    """A stub :class:`ProbabilityModel` that returns a fixed probability for every row."""

    def __init__(self, probability: float) -> None:
        self._probability = probability

    def predict_proba(self, matrix: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        return np.full((matrix.shape[0],), self._probability, dtype=np.float64)


def make_card(target: ModelTarget, *, threshold: float = 0.5) -> ModelCard:
    """A minimal valid :class:`ModelCard` for ``target``."""
    return ModelCard(
        target=target,
        feature_columns=tuple(FEATURE_COLUMNS),
        threshold=threshold,
        train_window=(T0, T0 + timedelta(minutes=100)),
        oos_metrics={"oos_auc": 0.6},
        seed=42,
        git_sha="deadbeef",
    )


def stub_bundle(
    probability: float, *, target: ModelTarget = "fake_breakout", threshold: float = 0.5
) -> ModelBundle:
    """A :class:`ModelBundle` with a single :class:`ConstantModel` for ``target``."""
    return ModelBundle(
        models={target: ConstantModel(probability)},
        cards={target: make_card(target, threshold=threshold)},
    )
