"""Entry-gate tests — enabled-strategy selection + directional regime gating (risk mitigation)."""

from __future__ import annotations

import polars as pl
import pytest

from tfex_s50_multi_tf_swing.regime.models import Regime
from tfex_s50_multi_tf_swing.signals.base import SIGNAL
from tfex_s50_multi_tf_swing.signals.errors import SignalInputError
from tfex_s50_multi_tf_swing.signals.gate import apply_regime_gate, build_detect_map
from tfex_s50_multi_tf_swing.signals.inputs import COL_REGIME
from tfex_s50_multi_tf_swing.signals.models import NO_SIGNAL, SignalConfig

from .conftest import LONG_BASE, SHORT_BASE, frame, to_row

_LONG_UP: frozenset[Regime] = frozenset({"trend_up"})
_SHORT_DOWN: frozenset[Regime] = frozenset({"trend_down"})
_NONE: frozenset[Regime] = frozenset()


def _classified(regimes: list[str | None], signals: list[str]) -> pl.DataFrame:
    """A minimal classified frame carrying just the regime + signal (what the gate reads)."""
    return pl.DataFrame(
        {COL_REGIME: regimes, SIGNAL: signals},
        schema={COL_REGIME: pl.Utf8(), SIGNAL: pl.Utf8()},
    )


# ---------------------------------------------------------------------------
# apply_regime_gate — directional demotion (long↔long_regimes, short↔short_regimes)
# ---------------------------------------------------------------------------


def test_long_only_keeps_long_up_blocks_others() -> None:
    df = _classified(["trend_up", "trend_down", "range_high_vol"], ["long", "short", "long"])
    # long_regimes={trend_up}, short_regimes=∅ (long-only): only the trend_up long survives.
    gated = apply_regime_gate(df, long_regimes=_LONG_UP, short_regimes=_NONE, strategy_id="B")
    assert gated.get_column(SIGNAL).to_list() == ["long", NO_SIGNAL, NO_SIGNAL]


def test_dual_direction_keeps_long_up_and_short_down() -> None:
    df = _classified(["trend_up", "trend_down", "trend_up"], ["long", "short", "short"])
    # Dual: long@trend_up kept, short@trend_down kept, short@trend_up blocked (not in short set).
    gated = apply_regime_gate(df, long_regimes=_LONG_UP, short_regimes=_SHORT_DOWN, strategy_id="B")
    assert gated.get_column(SIGNAL).to_list() == ["long", "short", NO_SIGNAL]


def test_short_only_blocks_longs() -> None:
    df = _classified(["trend_up", "trend_down"], ["long", "short"])
    # Short-only: long_regimes=∅ blocks the long; short@trend_down survives.
    gated = apply_regime_gate(df, long_regimes=_NONE, short_regimes=_SHORT_DOWN, strategy_id="B")
    assert gated.get_column(SIGNAL).to_list() == [NO_SIGNAL, "short"]


def test_long_blocked_in_trend_down() -> None:
    df = _classified(["trend_down"], ["long"])
    gated = apply_regime_gate(df, long_regimes=_LONG_UP, short_regimes=_SHORT_DOWN, strategy_id="B")
    assert gated.get_column(SIGNAL).to_list() == [NO_SIGNAL]


def test_regime_gate_treats_null_regime_as_blocked() -> None:
    df = _classified([None], ["long"])
    gated = apply_regime_gate(df, long_regimes=_LONG_UP, short_regimes=_SHORT_DOWN, strategy_id="B")
    assert gated.get_column(SIGNAL).to_list() == [NO_SIGNAL]


def test_regime_gate_leaves_already_no_signal_rows() -> None:
    df = _classified(["trend_down"], [NO_SIGNAL])
    gated = apply_regime_gate(df, long_regimes=_LONG_UP, short_regimes=_SHORT_DOWN, strategy_id="B")
    assert gated.get_column(SIGNAL).to_list() == [NO_SIGNAL]


def test_regime_gate_raises_on_missing_columns() -> None:
    df = pl.DataFrame({"time": [1, 2]})  # neither regime nor signal column
    with pytest.raises(SignalInputError):
        apply_regime_gate(df, long_regimes=_LONG_UP, short_regimes=_SHORT_DOWN, strategy_id="B")


def test_long_gate_allows_multiple_regimes() -> None:
    df = _classified(["trend_up", "range_low_vol"], ["long", "long"])
    gated = apply_regime_gate(
        df,
        long_regimes=frozenset({"trend_up", "range_low_vol"}),
        short_regimes=_NONE,
        strategy_id="B",
    )
    assert gated.get_column(SIGNAL).to_list() == ["long", "long"]


# ---------------------------------------------------------------------------
# build_detect_map — config-driven active pool + directional regime gating
# ---------------------------------------------------------------------------


def test_build_detect_map_default_is_orb_only() -> None:
    detect = build_detect_map(SignalConfig(), enabled=frozenset({"B"}))
    assert set(detect) == {"B"}


def test_build_detect_map_can_re_enable_a_and_b() -> None:
    # Strategy C is permanently removed from the registry (1H-execution migration).
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


def test_short_blocked_by_default_long_only() -> None:
    # SHORT_BASE is a clean Strategy-B short in trend_down; the default config has an empty short
    # allow-set (long-only), so the directional gate demotes it to No-Trade.
    detect = build_detect_map(SignalConfig(), enabled=frozenset({"B"}))
    assert detect["B"](frame([to_row(SHORT_BASE)])) == []


def test_short_fires_when_short_allowed_regimes_set() -> None:
    # Enabling short_allowed_regimes={trend_down} (dual-direction / hedging) lets the short through.
    cfg = SignalConfig(short_allowed_regimes=_SHORT_DOWN)
    detect = build_detect_map(cfg, enabled=frozenset({"B"}))
    signals = detect["B"](frame([to_row(SHORT_BASE)]))
    assert len(signals) == 1
    assert signals[0].direction == "short"


def test_short_only_override_blocks_long() -> None:
    # Explicit short-only override: long set empty, short set {trend_down}. LONG_BASE is blocked.
    detect = build_detect_map(
        SignalConfig(), enabled=frozenset({"B"}), long_regimes=_NONE, short_regimes=_SHORT_DOWN
    )
    assert detect["B"](frame([to_row(LONG_BASE)])) == []
    assert len(detect["B"](frame([to_row(SHORT_BASE)]))) == 1


def test_dual_direction_keeps_both() -> None:
    detect = build_detect_map(
        SignalConfig(), enabled=frozenset({"B"}), long_regimes=_LONG_UP, short_regimes=_SHORT_DOWN
    )
    assert len(detect["B"](frame([to_row(LONG_BASE)]))) == 1
    assert len(detect["B"](frame([to_row(SHORT_BASE)]))) == 1


def test_sweep_strategy_permanently_disabled() -> None:
    # Strategy C is permanently removed from the active registry (1H-execution migration).
    detect = build_detect_map(SignalConfig(), enabled=frozenset({"B"}))
    assert "C" not in detect
    detect_with_c = build_detect_map(SignalConfig(), enabled=frozenset({"A", "B", "C"}))
    assert "C" not in detect_with_c
    assert set(detect_with_c) == {"A", "B"}
