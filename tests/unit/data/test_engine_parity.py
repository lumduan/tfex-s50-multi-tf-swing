"""Parity: the ``engine`` source yields the same bars as the ``mirror`` path.

For identical underlying bars over the same dates/timeframes, ``EngineOhlcvFetcher``
must produce a raw frame whose shared ``time, open, high, low, close, volume``
columns are byte-for-byte equal to what the tvkit ``OhlcvFetcher`` builds via its
``_bars_to_frame`` transform — and the locally-built continuous must match too.
Values are chosen to be exact at 4 dp so the float→Decimal (mirror) and
string→Decimal (engine) paths converge.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from tvkit.api.chart.models.ohlcv import OHLCVBar

from tfex_s50_multi_tf_swing.adapters.market_data_engine_client import (
    EngineOHLCVBar,
    EngineOHLCVResponse,
)
from tfex_s50_multi_tf_swing.data import engine_fetcher
from tfex_s50_multi_tf_swing.data.continuous import ContinuousBuilder
from tfex_s50_multi_tf_swing.data.engine_fetcher import EngineOhlcvFetcher
from tfex_s50_multi_tf_swing.data.fetcher import _bars_to_frame
from tfex_s50_multi_tf_swing.data.models import Timeframe
from tfex_s50_multi_tf_swing.data.session import SessionCalendar

_SHARED_COLS = ["time", "open", "high", "low", "close", "volume"]

# (epoch_seconds, open, high, low, close, volume) — all exact at 4 dp.
_CANON: list[tuple[float, str, str, str, str, str]] = [
    (1772679600.0, "812.1000", "813.5000", "811.0000", "812.9000", "1500.0000"),
    (1772683200.0, "812.9000", "814.0000", "812.5000", "813.7000", "1700.0000"),
    (1772766000.0, "813.7000", "815.2000", "813.0000", "814.8000", "1600.0000"),
]
_START = datetime(2026, 3, 1, tzinfo=UTC)
_END = datetime(2026, 3, 10, tzinfo=UTC)


def _engine_bars() -> list[EngineOHLCVBar]:
    return [
        EngineOHLCVBar(
            ts=datetime.fromtimestamp(ts, tz=UTC),
            open=Decimal(o),
            high=Decimal(h),
            low=Decimal(low),
            close=Decimal(c),
            volume=Decimal(v),
            open_interest=Decimal("1000.0000"),
        )
        for ts, o, h, low, c, v in _CANON
    ]


def _tvkit_bars() -> list[OHLCVBar]:
    return [
        OHLCVBar(
            timestamp=ts,
            open=float(o),
            high=float(h),
            low=float(low),
            close=float(c),
            volume=float(v),
        )
        for ts, o, h, low, c, v in _CANON
    ]


def _install_fake(monkeypatch: pytest.MonkeyPatch, bars: list[EngineOHLCVBar]) -> None:
    response = EngineOHLCVResponse(symbol="S50M2026", timeframe="5m", adjusted=False, bars=bars)

    class _FakeClient:
        def __init__(self, **_kw: object) -> None: ...

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def get_ohlcv(self, *_a: object, **_kw: object) -> EngineOHLCVResponse:
            return response

    monkeypatch.setattr(engine_fetcher, "MarketDataEngineClient", _FakeClient)


@pytest.mark.parametrize("timeframe", ["5m", "1h"])
async def test_engine_frame_matches_mirror_frame(
    monkeypatch: pytest.MonkeyPatch, timeframe: Timeframe
) -> None:
    _install_fake(monkeypatch, _engine_bars())
    engine_df = await EngineOhlcvFetcher(base_url="http://engine").fetch_contract(
        contract_code="S50M2026", timeframe=timeframe, start=_START, end=_END
    )
    mirror_df = _bars_to_frame(_tvkit_bars(), start=_START, end=_END)

    # The mirror path has no open_interest column; compare the shared columns.
    assert engine_df.select(_SHARED_COLS).equals(mirror_df.select(_SHARED_COLS))


async def test_continuous_build_is_identical(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(monkeypatch, _engine_bars())
    engine_df = await EngineOhlcvFetcher(base_url="http://engine").fetch_contract(
        contract_code="S50M2026", timeframe="5m", start=_START, end=_END
    )
    mirror_df = _bars_to_frame(_tvkit_bars(), start=_START, end=_END)

    builder = ContinuousBuilder(calendar=SessionCalendar(roll_offset_days=5))
    engine_cont, engine_rolls = builder.build(per_contract={"S50M2026": engine_df}, timeframe="5m")
    mirror_cont, mirror_rolls = builder.build(per_contract={"S50M2026": mirror_df}, timeframe="5m")

    assert engine_rolls == mirror_rolls
    assert engine_cont.equals(mirror_cont)


def test_canonical_values_are_exact_at_4dp() -> None:
    # Guards the parity premise: float formatting and Decimal strings agree.
    for _ts, o, _h, _low, _c, _v in _CANON:
        assert Decimal(f"{float(o):.4f}") == Decimal(o)
