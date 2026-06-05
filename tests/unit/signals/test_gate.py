"""Entry-gate tests — enabled-strategy selection + regime gating (risk mitigation)."""

from __future__ import annotations

import polars as pl
import pytest

from tfex_s50_multi_tf_swing.signals.base import SIGNAL
from tfex_s50_multi_tf_swing.signals.errors import SignalInputError
from tfex_s50_multi_tf_swing.signals.gate import apply_regime_gate, build_detect_map
from tfex_s50_multi_tf_swing.signals.inputs import COL_REGIME
from tfex_s50_multi_tf_swing.signals.models import NO_SIGNAL, SignalConfig

from .conftest import LONG_BASE, SHORT_BASE, frame, to_row


def _classified(regimes: list[str | None], signals: list[str]) -> pl.DataFrame:
    """A minimal classified frame carrying just the regime + signal (what the gate reads)."""
    return pl.DataFrame(
        {COL_REGIME: regimes, SIGNAL: signals},
        schema={COL_REGIME: pl.Utf8(), SIGNAL: pl.Utf8()},
    )


# ---------------------------------------------------------------------------
# apply_regime_gate — vectorised demotion of fired bars outside the allow-set
# ---------------------------------------------------------------------------


def test_regime_gate_blocks_disallowed_keeps_allowed() -> None:
    df = _classified(["trend_up", "trend_down", "range_high_vol"], ["long", "short", "long"])
    gated = apply_regime_gate(df, allowed_regimes=frozenset({"trend_up"}), strategy_id="B")
    # Only the trend_up bar survives; trend_down / range_high_vol are demoted to No-Trade.
    assert gated.get_column(SIGNAL).to_list() == ["long", NO_SIGNAL, NO_SIGNAL]


def test_regime_gate_treats_null_regime_as_blocked() -> None:
    df = _classified([None], ["long"])
    gated = apply_regime_gate(df, allowed_regimes=frozenset({"trend_up"}), strategy_id="B")
    assert gated.get_column(SIGNAL).to_list() == [NO_SIGNAL]


def test_regime_gate_leaves_already_no_signal_rows() -> None:
    df = _classified(["trend_down"], [NO_SIGNAL])
    gated = apply_regime_gate(df, allowed_regimes=frozenset({"trend_up"}), strategy_id="B")
    assert gated.get_column(SIGNAL).to_list() == [NO_SIGNAL]


def test_regime_gate_raises_on_missing_columns() -> None:
    df = pl.DataFrame({"time": [1, 2]})  # neither regime nor signal column
    with pytest.raises(SignalInputError):
        apply_regime_gate(df, allowed_regimes=frozenset({"trend_up"}), strategy_id="B")


def test_regime_gate_allows_multiple_regimes() -> None:
    df = _classified(["trend_up", "range_low_vol"], ["long", "long"])
    gated = apply_regime_gate(
        df, allowed_regimes=frozenset({"trend_up", "range_low_vol"}), strategy_id="B"
    )
    assert gated.get_column(SIGNAL).to_list() == ["long", "long"]


# ---------------------------------------------------------------------------
# build_detect_map — config-driven active pool + regime-gated emission
# ---------------------------------------------------------------------------


def test_build_detect_map_default_is_orb_only() -> None:
    detect = build_detect_map(SignalConfig(), enabled=frozenset({"B"}))
    assert set(detect) == {"B"}


def test_build_detect_map_can_re_enable_a_and_b() -> None:
    # Strategy C is permanently removed from the registry (1H-execution migration).
    # Enabling all valid strategy IDs only activates A and B.
    detect = build_detect_map(SignalConfig(), enabled=frozenset({"A", "B"}))
    assert set(detect) == {"A", "B"}


def test_build_detect_map_empty_when_nothing_enabled() -> None:
    detect = build_detect_map(SignalConfig(), enabled=frozenset())
    assert detect == {}


def test_orb_fires_in_trend_up() -> None:
    detect = build_detect_map(SignalConfig(), enabled=frozenset({"B"}))
    signals = detect["B"](frame([to_row(LONG_BASE)]))
    assert len(signals) == 1
    assert signals[0].strategy_id == "B"
    assert signals[0].direction == "long"


def test_orb_blocked_in_trend_down_by_gate() -> None:
    # SHORT_BASE is a clean Strategy-B short whose 1H regime is trend_down — the policy whitelists B
    # there, but the trend_up-only gate demotes it to No-Trade.
    detect = build_detect_map(SignalConfig(), enabled=frozenset({"B"}))
    assert detect["B"](frame([to_row(SHORT_BASE)])) == []


def test_widening_gate_lets_trend_down_through() -> None:
    cfg = SignalConfig(allowed_regimes=frozenset({"trend_up", "trend_down"}))
    detect = build_detect_map(cfg, enabled=frozenset({"B"}))
    signals = detect["B"](frame([to_row(SHORT_BASE)]))
    assert len(signals) == 1
    assert signals[0].direction == "short"


def test_sweep_strategy_permanently_disabled() -> None:
    # Strategy C is permanently removed from the active registry (1H-execution migration).
    # The default pool (B only) excludes it.
    detect = build_detect_map(SignalConfig(), enabled=frozenset({"B"}))
    assert "C" not in detect
    # Building a detect map with only C (or including C) silently skips it — C is not
    # in the _CLASSIFY / _TO_SIGNALS registries, so no detect function is built for it.
    detect_with_c = build_detect_map(SignalConfig(), enabled=frozenset({"A", "B", "C"}))
    assert "C" not in detect_with_c
    assert set(detect_with_c) == {"A", "B"}
