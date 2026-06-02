"""S50 quarterly contract calendar and TradingView symbol conventions.

Quarterly cycle: H (Mar), M (Jun), U (Sep), Z (Dec). Per the TFEX S50 Futures
contract specification, the **last trading day** is the last business day of
the contract month — _not_ the CME-style third Friday. The helpers in this
module resolve expiry against the Thai market business calendar exposed by
:mod:`tfex_s50_multi_tf_swing.data.session`.

TradingView symbol conventions used by the fetcher:

* Per-contract: ``"S50<code><yyyy>"`` (e.g. ``"S50H2026"``). The fetcher
  prefixes the exchange in :class:`OhlcvFetcher`; this module only emits the
  bare symbol.
* Continuous front-month: ``"S501!"`` — TradingView's auto-roll series. We
  treat it as an external **cross-check reference** for our locally-built
  back-adjusted continuous, not as the source of truth.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from tfex_s50_multi_tf_swing.data.errors import SessionError
from tfex_s50_multi_tf_swing.data.models import ContractSpec

MONTH_CODES: tuple[str, ...] = ("H", "M", "U", "Z")
"""Quarterly month codes in calendar order: Mar / Jun / Sep / Dec."""

_MONTH_CODE_TO_MONTH: dict[str, int] = {"H": 3, "M": 6, "U": 9, "Z": 12}

TV_CONTINUOUS_SYMBOL: str = "S501!"
"""TradingView's auto-roll front-month symbol for SET50 Futures."""

ENGINE_CONTINUOUS_SYMBOL: str = "S501!"
"""Market Data Engine symbol for the front-month continuous (read raw; tfex
back-adjusts locally). Mirrors :data:`TV_CONTINUOUS_SYMBOL` — the engine ingests
via tvkit and stores the bare TradingView symbol."""

_S50_PREFIX: str = "S50"


@dataclass(frozen=True)
class _BusinessCalendar:
    """Minimal callable surface needed for expiry resolution.

    Real callers pass a :class:`tfex_s50_multi_tf_swing.data.session.SessionCalendar`;
    tests can substitute any object exposing ``is_business_day(d)``.
    """

    is_business_day: object  # callable[[date], bool] but kept loose for duck-typing


def tv_symbol_for_contract(code: str) -> str:
    """Return the TradingView symbol for a per-contract code.

    The contract code is the canonical ``S50<month><yyyy>`` string used by the
    rest of the data layer (and the TimescaleDB ``contract`` column). For now
    the TradingView symbol is identical — but this helper exists so the
    fetcher does not embed the format string inline.
    """
    if not code.startswith(_S50_PREFIX):
        raise ValueError(f"contract code must start with {_S50_PREFIX!r}, got {code!r}")
    return code


def engine_symbol_for_contract(code: str) -> str:
    """Return the Market Data Engine symbol for a per-contract code.

    The engine is the canonical OHLCV producer and ingests S50 futures via
    tvkit, so its stored ``symbol`` is the bare TradingView contract code
    (e.g. ``"S50M2026"``) — the same string the data layer uses as the
    ``contract`` key, without the ``TFEX:`` exchange prefix the fetcher adds for
    its own tvkit calls. This is the single localized symbol-mapping choice for
    the ``engine`` OHLCV source; confirm it against engine seed data before the
    first live cutover, and change it here only.
    """
    if not code.startswith(_S50_PREFIX):
        raise ValueError(f"contract code must start with {_S50_PREFIX!r}, got {code!r}")
    return code


def parse_contract_code(code: str) -> tuple[str, int]:
    """Split a code like ``"S50H2026"`` into ``("H", 2026)``.

    Raises:
        ValueError: if the code shape is wrong or the month code is not H/M/U/Z.
    """
    if not code.startswith(_S50_PREFIX):
        raise ValueError(f"contract code must start with {_S50_PREFIX!r}, got {code!r}")
    rest: str = code[len(_S50_PREFIX) :]
    if len(rest) != 5:
        raise ValueError(
            f"contract code must be 'S50<month><yyyy>' (e.g. 'S50H2026'), got {code!r}"
        )
    month_code: str = rest[0]
    year_str: str = rest[1:]
    if month_code not in _MONTH_CODE_TO_MONTH:
        raise ValueError(
            f"unknown quarterly month code {month_code!r}; expected one of {MONTH_CODES!r}"
        )
    try:
        year: int = int(year_str)
    except ValueError as exc:
        raise ValueError(f"contract year must be 4 digits, got {year_str!r}") from exc
    return month_code, year


def expiry_for(code: str, calendar: object | None = None) -> date:
    """Return the expiry (last trading day) for a contract code.

    Per the TFEX S50 specification, the expiry is the **last business day** of
    the contract month. If a ``calendar`` (with ``is_business_day(d) -> bool``)
    is provided, it is used to skip Thai market holidays; otherwise this
    function falls back to a Mon–Fri rule which is a close approximation but
    will be wrong in months whose last weekday is a Thai holiday.

    Args:
        code: Contract code, e.g. ``"S50H2026"``.
        calendar: Optional object exposing ``is_business_day(d: date) -> bool``.
            Pass the project's
            :class:`tfex_s50_multi_tf_swing.data.session.SessionCalendar`.

    Returns:
        The last trading day of the contract month.

    Raises:
        ValueError: if the code is malformed.
    """
    month_code, year = parse_contract_code(code)
    month: int = _MONTH_CODE_TO_MONTH[month_code]

    # Walk back from the last calendar day of the month to the first
    # business day. We bound the loop to 31 days for safety.
    last_day: int = _last_day_of_month(year, month)
    for offset in range(31):
        candidate: date = date(year, month, last_day - offset)
        if candidate.month != month:
            # Walked off the start of the month — should never happen for a
            # valid Gregorian month, but be explicit anyway.
            raise SessionError(f"no business day found in {year}-{month:02d} for expiry resolution")
        if _is_business_day(candidate, calendar):
            return candidate
    raise SessionError(  # pragma: no cover — defensive; loop above always returns.
        f"no business day found in {year}-{month:02d} after 31 iterations"
    )


def next_active_contract(as_of: date, calendar: object | None = None) -> ContractSpec:
    """Return the front-month contract active on a given date.

    A contract is "active" up to and including its expiry; once the expiry
    passes, the next quarterly month takes over.

    Args:
        as_of: The date for which to resolve the active contract.
        calendar: Optional Thai business calendar; see :func:`expiry_for`.
    """
    for spec in iter_contracts(start_year=as_of.year, count=8, calendar=calendar):
        if as_of <= spec.expiry:
            return spec
    raise SessionError(f"no active contract found for {as_of.isoformat()}; ran out of quarters")


def iter_contracts(
    *,
    start_year: int,
    count: int,
    calendar: object | None = None,
) -> Iterable[ContractSpec]:
    """Yield ``count`` :class:`ContractSpec` values starting at ``start_year``-H.

    Iterates strictly in calendar order: H → M → U → Z → next-year H → …
    Useful for the continuous-contract builder which needs the per-quarter
    expiry sequence.
    """
    year: int = start_year
    code_index: int = 0
    emitted: int = 0
    while emitted < count:
        month_code: str = MONTH_CODES[code_index]
        code: str = f"{_S50_PREFIX}{month_code}{year}"
        yield ContractSpec(
            code=code,
            month_code=month_code,  # type: ignore[arg-type]
            year=year,
            expiry=expiry_for(code, calendar=calendar),
        )
        emitted += 1
        code_index += 1
        if code_index == len(MONTH_CODES):
            code_index = 0
            year += 1


def _last_day_of_month(year: int, month: int) -> int:
    """Return the 1-indexed last day of the given month."""
    if month == 12:
        next_first: date = date(year + 1, 1, 1)
    else:
        next_first = date(year, month + 1, 1)
    return (next_first - _ONE_DAY).day


def _is_business_day(d: date, calendar: object | None) -> bool:
    """Use the provided calendar if it offers ``is_business_day``; otherwise weekday check."""
    if calendar is not None:
        is_bd = getattr(calendar, "is_business_day", None)
        if callable(is_bd):
            result = is_bd(d)
            if not isinstance(result, bool):  # pragma: no cover — duck typing guard
                raise TypeError(
                    f"calendar.is_business_day must return bool, got {type(result).__name__}"
                )
            return result
    return d.weekday() < 5  # Mon=0 .. Fri=4


from datetime import timedelta as _td  # noqa: E402

_ONE_DAY = _td(days=1)


__all__: list[str] = [
    "ENGINE_CONTINUOUS_SYMBOL",
    "MONTH_CODES",
    "TV_CONTINUOUS_SYMBOL",
    "engine_symbol_for_contract",
    "expiry_for",
    "iter_contracts",
    "next_active_contract",
    "parse_contract_code",
    "tv_symbol_for_contract",
]
