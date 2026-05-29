"""Unit tests for :mod:`tfex_s50_multi_tf_swing.data.contracts`."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tfex_s50_multi_tf_swing.data.contracts import (
    MONTH_CODES,
    TV_CONTINUOUS_SYMBOL,
    expiry_for,
    iter_contracts,
    next_active_contract,
    parse_contract_code,
    tv_symbol_for_contract,
)
from tfex_s50_multi_tf_swing.data.session import SessionCalendar


def test_tv_continuous_symbol_constant() -> None:
    assert TV_CONTINUOUS_SYMBOL == "S501!"


def test_tv_symbol_for_contract_roundtrip() -> None:
    assert tv_symbol_for_contract("S50H2026") == "S50H2026"


def test_tv_symbol_for_contract_rejects_wrong_prefix() -> None:
    with pytest.raises(ValueError):
        tv_symbol_for_contract("XYZH2026")


def test_parse_contract_code_valid() -> None:
    code, year = parse_contract_code("S50H2026")
    assert code == "H"
    assert year == 2026


@pytest.mark.parametrize(
    "bad",
    [
        "S50H26",  # short year
        "S50X2026",  # invalid month
        "S50H202A",  # non-digit year
        "S5H2026",  # wrong prefix
    ],
)
def test_parse_contract_code_invalid(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_contract_code(bad)


def test_expiry_for_basic_weekday_fallback() -> None:
    # No calendar — fall back to last weekday of the month.
    # March 2026: last day is Tue 31. Last weekday = 31.
    assert expiry_for("S50H2026") == date(2026, 3, 31)


def test_expiry_for_skips_thai_holiday() -> None:
    cal = SessionCalendar()
    # Dec 2024 last weekday is Tue 31; Tue 31 IS a Thai holiday → expiry = Mon 30.
    assert expiry_for("S50Z2024", calendar=cal) == date(2024, 12, 30)


def test_expiry_for_returns_last_business_day_when_weekend() -> None:
    cal = SessionCalendar()
    # Sept 2024: last day is Mon 30, which is a business day.
    assert expiry_for("S50U2024", calendar=cal) == date(2024, 9, 30)


def test_next_active_contract_before_expiry() -> None:
    cal = SessionCalendar()
    # Mid-May 2026 → June (M) is the front-month quarterly.
    spec = next_active_contract(date(2026, 5, 15), calendar=cal)
    assert spec.code == "S50M2026"
    assert spec.month_code == "M"
    assert spec.year == 2026


def test_next_active_contract_on_expiry_returns_same() -> None:
    cal = SessionCalendar()
    # On expiry day itself the contract is still active.
    h_expiry = expiry_for("S50H2026", calendar=cal)
    assert next_active_contract(h_expiry, calendar=cal).code == "S50H2026"


def test_next_active_contract_after_expiry_rolls() -> None:
    cal = SessionCalendar()
    h_expiry = expiry_for("S50H2026", calendar=cal)
    day_after = h_expiry + timedelta(days=1)
    assert next_active_contract(day_after, calendar=cal).code == "S50M2026"


def test_iter_contracts_calendar_order() -> None:
    specs = list(iter_contracts(start_year=2025, count=6))
    assert [s.code for s in specs] == [
        "S50H2025",
        "S50M2025",
        "S50U2025",
        "S50Z2025",
        "S50H2026",
        "S50M2026",
    ]


def test_month_codes_constant() -> None:
    assert MONTH_CODES == ("H", "M", "U", "Z")
