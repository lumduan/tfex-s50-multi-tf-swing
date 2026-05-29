"""§2.4 market-structure feature tests (incl. causal liquidity sweep)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import polars as pl

from tfex_s50_multi_tf_swing.features.models import FeatureConfig
from tfex_s50_multi_tf_swing.features.structure import add_structure

from .conftest import intraday_5m, working_frame


def test_prev_day_and_ib_features(small_config: FeatureConfig) -> None:
    df = intraday_5m(days=4)
    out = add_structure(working_frame(df, small_config), small_config, "5m")
    for col in ("overnight_gap", "dist_to_prev_high", "dist_to_prev_low", "ib_high", "ib_low"):
        assert col in out.columns
    # After the first day there is a prior session, so prev-day distances populate.
    later = out.tail(out.height // 2)
    assert later["dist_to_prev_high"].null_count() < later.height


def test_ib_columns_absent_on_4h(small_config: FeatureConfig) -> None:
    df = intraday_5m(days=4)
    out = add_structure(working_frame(df, small_config), small_config, "4h")
    assert "ib_high" not in out.columns and "ib_low" not in out.columns


def test_liquidity_sweep_flag_is_causal(small_config: FeatureConfig) -> None:
    """A pierce-and-reverse is flagged exactly ``k`` bars later, never earlier."""
    k = small_config.liquidity_confirm_bars  # 3
    lookback = small_config.liquidity_lookback  # 10
    # Flat base establishes the recent high near 100; index 12 pierces to 110,
    # then closes revert below 100 over the next k bars -> confirmed sweep.
    highs, lows, closes = [], [], []
    for i in range(40):
        if i == 12:
            highs.append(110.0)
            lows.append(99.0)
            closes.append(109.0)
        elif 13 <= i <= 12 + k:
            highs.append(100.5)
            lows.append(95.0)
            closes.append(96.0)  # reverted below the swept 100 level
        else:
            highs.append(100.5)
            lows.append(99.5)
            closes.append(100.0)
    start = datetime(2026, 1, 5, 2, 45, tzinfo=UTC)
    rows = [
        {
            "time": start + timedelta(minutes=5 * i),
            "open": Decimal(f"{closes[i]:.4f}"),
            "high": Decimal(f"{highs[i]:.4f}"),
            "low": Decimal(f"{lows[i]:.4f}"),
            "close": Decimal(f"{closes[i]:.4f}"),
            "volume": Decimal("1000.0000"),
        }
        for i in range(40)
    ]
    df = pl.DataFrame(rows).with_columns(pl.col("time").dt.replace_time_zone("UTC"))
    out = add_structure(working_frame(df, small_config), small_config, "5m")
    flag = out["liquidity_sweep_flag"].to_list()
    assert flag[12 + k] == 1, "sweep should confirm exactly k bars after the pierce"
    # No leak: the flag must not fire at or before the pierce bar.
    assert all(flag[i] == 0 for i in range(0, 13)), "sweep flagged before confirmation"
    assert lookback < 12  # sanity: recent-high window is established before the pierce
