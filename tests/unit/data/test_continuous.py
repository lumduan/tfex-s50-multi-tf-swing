"""Unit tests for :class:`tfex_s50_multi_tf_swing.data.continuous.ContinuousBuilder`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import polars as pl
import pytest

from tfex_s50_multi_tf_swing.data.continuous import ContinuousBuilder
from tfex_s50_multi_tf_swing.data.errors import ContinuousContractError


def _per_contract_frame(
    *,
    start: datetime,
    days: int,
    close_base: float,
    volume_curve: list[int],
) -> pl.DataFrame:
    """Build a daily frame for one contract.

    ``volume_curve`` has length ``days`` and gives the per-day volume so
    rolls can be triggered by configuring the near/far volume profiles.
    """
    rows: list[dict[str, object]] = []
    for i in range(days):
        t = start + timedelta(days=i)
        c = Decimal(f"{close_base + i * 0.1:.4f}")
        rows.append(
            {
                "time": t,
                "open": c,
                "high": Decimal(f"{close_base + i * 0.1 + 0.5:.4f}"),
                "low": Decimal(f"{close_base + i * 0.1 - 0.5:.4f}"),
                "close": c,
                "volume": Decimal(f"{volume_curve[i]:.4f}"),
            }
        )
    return pl.DataFrame(rows).with_columns(pl.col("time").dt.replace_time_zone("UTC"))


def test_build_rejects_empty() -> None:
    builder = ContinuousBuilder()
    with pytest.raises(ContinuousContractError):
        builder.build(per_contract={}, timeframe="4h")


def test_build_single_contract_no_rolls() -> None:
    builder = ContinuousBuilder()
    near = _per_contract_frame(
        start=datetime(2026, 3, 1, tzinfo=UTC),
        days=10,
        close_base=800.0,
        volume_curve=[1000] * 10,
    )
    cont, rolls = builder.build(per_contract={"S50M2026": near}, timeframe="4h")
    assert rolls == []
    assert cont.height == 10
    # All bars carry the single contract code.
    assert set(cont["contract_at_time"].to_list()) == {"S50M2026"}
    # No adjustment for a single contract.
    assert set(cont["adjustment_factor"].to_list()) == {Decimal("1.00000000")}


def test_build_two_contract_roll_back_adjusts_history() -> None:
    """Synthetic two-contract roll; assert post-roll continuity in returns.

    Setup: H expires 2026-03-31. M is the far contract. We give M progressively
    larger volume in the roll window so the volume crossover triggers near the
    end of the window. After back-adjustment, the close-to-close return at the
    roll boundary should be very close to the natural return that would have
    been observed without the contract gap.
    """
    builder = ContinuousBuilder(roll_offset_days=5)

    # H series: 30 days ending at the expiry day (2026-03-31), high volume early
    # then declining.
    h_start = datetime(2026, 3, 2, tzinfo=UTC)
    h = _per_contract_frame(
        start=h_start,
        days=30,
        close_base=800.0,
        volume_curve=[2000] * 25 + [1500, 1200, 900, 600, 300],
    )

    # M series: 30 days starting before H expiry by ~3 days; volume builds.
    m_start = datetime(2026, 3, 28, tzinfo=UTC)
    m = _per_contract_frame(
        start=m_start,
        days=30,
        close_base=820.0,  # 20-point premium → ratio < 1
        volume_curve=[100, 200, 400] + [1500] * 27,
    )

    cont, rolls = builder.build(per_contract={"S50H2026": h, "S50M2026": m}, timeframe="4h")

    # Exactly one roll record produced.
    assert len(rolls) == 1
    rec = rolls[0]
    assert rec.from_contract == "S50H2026"
    assert rec.to_contract == "S50M2026"
    # Ratio = M/H ≈ 1.025 (back-adjust H historicals UP to the M scale).
    assert Decimal("1.00") < rec.ratio < Decimal("1.10")

    # Historical (pre-roll) bars must have been scaled by the roll ratio.
    pre_roll_close = (
        cont.filter(pl.col("time") < rec.roll_time).sort("time").tail(1)["close"].to_list()[0]
    )
    # Expected = raw H close at last pre-roll bar × ratio
    raw_h_close = (
        h.filter(pl.col("time") < rec.roll_time).sort("time").tail(1)["close"].to_list()[0]
    )
    expected = (Decimal(str(raw_h_close)) * rec.ratio).quantize(Decimal("0.0001"))
    actual = Decimal(str(pre_roll_close))
    # Compare to within 1 cent — Float64 conversion in continuous.py costs precision.
    assert abs(actual - expected) < Decimal("0.01")


def test_build_falls_back_to_expiry_when_no_volume_crossover() -> None:
    builder = ContinuousBuilder(roll_offset_days=5)
    h = _per_contract_frame(
        start=datetime(2026, 3, 2, tzinfo=UTC),
        days=30,
        close_base=800.0,
        volume_curve=[5000] * 30,  # Always dominant
    )
    m = _per_contract_frame(
        start=datetime(2026, 3, 28, tzinfo=UTC),
        days=30,
        close_base=820.0,
        volume_curve=[100] * 30,  # Never crosses over
    )
    cont, rolls = builder.build(per_contract={"S50H2026": h, "S50M2026": m}, timeframe="4h")
    assert len(rolls) == 1


def test_build_rejects_missing_columns() -> None:
    builder = ContinuousBuilder()
    bad = pl.DataFrame({"time": [datetime(2026, 3, 1, tzinfo=UTC)]})
    with pytest.raises(ContinuousContractError):
        builder.build(per_contract={"S50H2026": bad}, timeframe="4h")


def test_constructor_rejects_negative_offset() -> None:
    with pytest.raises(ValueError):
        ContinuousBuilder(roll_offset_days=-1)


def test_orders_contracts_by_calendar() -> None:
    """Out-of-order input must be sorted by quarterly month order.

    Each contract's frame extends past the next contract's expiry so the
    roll window has overlap data. M expiry ≈ 2026-06-30, U ≈ 2026-09-30.
    """
    builder = ContinuousBuilder(roll_offset_days=2)
    m = _per_contract_frame(
        start=datetime(2026, 6, 20, tzinfo=UTC),
        days=15,
        close_base=820.0,
        volume_curve=[2000] * 8 + [500] * 7,
    )
    u = _per_contract_frame(
        start=datetime(2026, 6, 25, tzinfo=UTC),
        days=100,  # covers through end-Sep
        close_base=830.0,
        volume_curve=[200] * 5 + [600] * 95,
    )
    z = _per_contract_frame(
        start=datetime(2026, 9, 25, tzinfo=UTC),
        days=20,
        close_base=850.0,
        volume_curve=[100] * 5 + [800] * 15,
    )
    # Note Z passed before M in the dict — builder must still sort properly.
    cont, rolls = builder.build(
        per_contract={"S50Z2026": z, "S50M2026": m, "S50U2026": u}, timeframe="4h"
    )
    assert [r.from_contract for r in rolls] == ["S50M2026", "S50U2026"]
    assert [r.to_contract for r in rolls] == ["S50U2026", "S50Z2026"]
    # Final segment is the latest contract (Z).
    last_contract = cont.sort("time").tail(1)["contract_at_time"].to_list()[0]
    assert last_contract == "S50Z2026"
