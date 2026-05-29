"""Multi-timeframe causal alignment tests.

The central guarantee: a higher-timeframe bar stamped (open) at time ``T`` must
not appear on any base bar before ``T + bar_duration`` — i.e. before it closes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from tfex_s50_multi_tf_swing.features.align import align_timeframes
from tfex_s50_multi_tf_swing.features.errors import AlignmentError


def _panel(*, timeframe: str, interval_minutes: int, n: int, start: datetime) -> pl.DataFrame:
    times = [start + timedelta(minutes=interval_minutes * i) for i in range(n)]
    return pl.DataFrame(
        {
            "time": times,
            "timeframe": [timeframe] * n,
            "feat": [float(i) for i in range(n)],
        }
    ).with_columns(pl.col("time").dt.replace_time_zone("UTC"))


def test_htf_feature_only_visible_after_bar_closes() -> None:
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    base = _panel(timeframe="5m", interval_minutes=5, n=200, start=start)
    htf = _panel(timeframe="4h", interval_minutes=240, n=10, start=start)
    aligned = align_timeframes(base, base_timeframe="5m", higher={"4h": htf})

    assert "4h_feat" in aligned.columns
    # The first 4h bar opens at start and closes at start+240m. Any base bar
    # strictly before the close must NOT see that bar's feature (value 0.0).
    before_close = aligned.filter(pl.col("time") < start + timedelta(minutes=240))
    assert before_close["4h_feat"].drop_nulls().is_empty()
    # The base bar exactly at the close sees the just-closed first 4h bar (feat 0.0).
    at_close = aligned.filter(pl.col("time") == start + timedelta(minutes=240))
    assert at_close["4h_feat"].to_list() == [0.0]
    # Just before the second 4h bar closes (start+480m) we still see only feat 0.0.
    mid = aligned.filter(pl.col("time") == start + timedelta(minutes=475))
    assert mid["4h_feat"].to_list() == [0.0]


def test_no_future_value_ever_leaks() -> None:
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    base = _panel(timeframe="5m", interval_minutes=5, n=300, start=start)
    htf = _panel(timeframe="1h", interval_minutes=60, n=30, start=start)
    aligned = align_timeframes(base, base_timeframe="5m", higher={"1h": htf})
    # For every base row, the attached 1h feat index must correspond to a bar
    # that already closed: htf_open + 60m <= base_time.
    for t, feat in zip(aligned["time"].to_list(), aligned["1h_feat"].to_list(), strict=True):
        if feat is None:
            continue
        htf_open = start + timedelta(minutes=60 * int(feat))
        assert htf_open + timedelta(minutes=60) <= t


def test_rejects_non_coarser_timeframe() -> None:
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    base = _panel(timeframe="5m", interval_minutes=5, n=10, start=start)
    same = _panel(timeframe="5m", interval_minutes=5, n=10, start=start)
    with pytest.raises(AlignmentError):
        align_timeframes(base, base_timeframe="5m", higher={"5m": same})


def test_explicit_column_subset_is_brought_across() -> None:
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    base = _panel(timeframe="5m", interval_minutes=5, n=120, start=start)
    htf = _panel(timeframe="4h", interval_minutes=240, n=6, start=start)
    aligned = align_timeframes(base, base_timeframe="5m", higher={"4h": htf}, columns=["feat"])
    assert "4h_feat" in aligned.columns


def test_rejects_base_without_time_column() -> None:
    bad = pl.DataFrame({"timeframe": ["5m"], "feat": [1.0]})
    with pytest.raises(AlignmentError):
        align_timeframes(bad, base_timeframe="5m", higher={})


def test_rejects_missing_requested_column() -> None:
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    base = _panel(timeframe="5m", interval_minutes=5, n=10, start=start)
    htf = _panel(timeframe="4h", interval_minutes=240, n=4, start=start)
    with pytest.raises(AlignmentError):
        align_timeframes(base, base_timeframe="5m", higher={"4h": htf}, columns=["nope"])
