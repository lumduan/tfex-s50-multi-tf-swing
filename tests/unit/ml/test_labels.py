"""Tests for triple-barrier labelling: TP / SL / time branches, skips, persistence."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

import polars as pl
import pytest

from tfex_s50_multi_tf_swing.ml.errors import LabelError
from tfex_s50_multi_tf_swing.ml.labels import LABEL_SCHEMA, label_triple_barrier, save_labels
from tfex_s50_multi_tf_swing.ml.models import TripleBarrierConfig

from .conftest import T0, make_signal

_CFG = TripleBarrierConfig(tp_atr_mult=1.0, sl_atr_mult=1.0, horizon_bars=2)


def _bars(rows: Sequence[tuple[float, float, float, float, float]]) -> pl.DataFrame:
    """Build a bars frame from ``(open, high, low, close, atr)`` tuples, one per 5m bar."""
    return pl.DataFrame(
        [
            {
                "time": T0 + timedelta(minutes=5 * i),
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "atr": a,
            }
            for i, (o, h, lo, c, a) in enumerate(rows)
        ],
        schema={
            "time": pl.Datetime(time_unit="us", time_zone="UTC"),
            "open": pl.Float64(),
            "high": pl.Float64(),
            "low": pl.Float64(),
            "close": pl.Float64(),
            "atr": pl.Float64(),
        },
    )


def test_tp_first_long_continuation_label_1() -> None:
    # Strategy A → trend_continuation; a long that hits TP before SL is a held continuation.
    bars = _bars([(100, 100, 100, 100, 1.0), (100, 102, 100, 101, 1.0), (101, 101, 101, 101, 1.0)])
    out = label_triple_barrier([make_signal(strategy_id="A", direction="long")], bars, config=_CFG)
    assert out["outcome"].to_list() == ["tp"]
    assert out["target"].to_list() == ["trend_continuation"]
    assert out["label"].to_list() == [1]


def test_sl_first_long_continuation_0_but_fake_1() -> None:
    falling = [(100, 100, 100, 100, 1.0), (100, 100, 98, 99, 1.0), (99, 99, 99, 99, 1.0)]
    a_out = label_triple_barrier(
        [make_signal(strategy_id="A", direction="long")], _bars(falling), config=_CFG
    )
    assert a_out["outcome"].to_list() == ["sl"]
    assert a_out["label"].to_list() == [0]  # continuation failed

    c_out = label_triple_barrier(
        [make_signal(strategy_id="C", direction="long")], _bars(falling), config=_CFG
    )
    assert c_out["target"].to_list() == ["fake_breakout"]
    assert c_out["label"].to_list() == [1]  # the breakout faked


def test_short_tp_first() -> None:
    # A short hits TP when price falls below entry − atr.
    bars = _bars([(100, 100, 100, 100, 1.0), (100, 100, 98, 99, 1.0), (99, 99, 99, 99, 1.0)])
    out = label_triple_barrier([make_signal(strategy_id="A", direction="short")], bars, config=_CFG)
    assert out["outcome"].to_list() == ["tp"]
    assert out["label"].to_list() == [1]


def test_time_exit_positive_and_negative() -> None:
    flat_up = [(100, 100, 100, 100, 1.0)] + [(100, 100.5, 99.5, 100.5, 1.0)] * 4
    out = label_triple_barrier(
        [make_signal(strategy_id="A", direction="long")], _bars(flat_up), config=_CFG
    )
    assert out["outcome"].to_list() == ["time"]
    assert out["label"].to_list() == [1]  # positive time-exit → continuation held

    flat_down = [(100, 100, 100, 100, 1.0)] + [(100, 100.5, 99.5, 99.5, 1.0)] * 4
    out2 = label_triple_barrier(
        [make_signal(strategy_id="A", direction="long")], _bars(flat_down), config=_CFG
    )
    assert out2["outcome"].to_list() == ["time"]
    assert out2["label"].to_list() == [0]


def test_skip_signal_with_no_entry_bar() -> None:
    bars = _bars([(100, 100, 100, 100, 1.0), (100, 100, 100, 100, 1.0)])
    # Signal on the last bar → no next-bar entry → dropped.
    sig = make_signal(strategy_id="A", direction="long", minute=5)
    assert label_triple_barrier([sig], bars, config=_CFG).height == 0


def test_skip_signal_with_bad_atr() -> None:
    bars = _bars([(100, 100, 100, 100, 1.0), (100, 102, 100, 101, 0.0)])
    sig = make_signal(strategy_id="A", direction="long")
    assert label_triple_barrier([sig], bars, config=_CFG).height == 0


def test_missing_columns_raise() -> None:
    bars = _bars([(100, 100, 100, 100, 1.0)]).drop("atr")
    with pytest.raises(LabelError, match="missing columns"):
        label_triple_barrier([make_signal(strategy_id="A")], bars, config=_CFG)


def test_empty_signals_yields_empty_frame() -> None:
    out = label_triple_barrier([], _bars([(100, 100, 100, 100, 1.0)]))
    assert out.height == 0
    assert set(out.schema) == set(LABEL_SCHEMA)


def test_save_labels_writes_per_target(tmp_path: Path) -> None:
    rows = [(100, 100, 100, 100, 1.0), (100, 102, 100, 101, 1.0), (101, 101, 101, 101, 1.0)]
    frame = label_triple_barrier(
        [make_signal(strategy_id="A", direction="long")], _bars(rows), config=_CFG
    )
    written = save_labels(frame, tmp_path)
    assert written
    assert (tmp_path / "trend_continuation.parquet").is_file()
    reloaded = pl.read_parquet(tmp_path / "trend_continuation.parquet")
    assert reloaded.height == frame.height
