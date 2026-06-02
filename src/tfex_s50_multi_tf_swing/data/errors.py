"""Exception hierarchy for the ``data`` sub-package.

Roots at :class:`tfex_s50_multi_tf_swing.adapters.errors.TfexS50Error` so the
shared base catches every package-level failure. Use the most specific subclass
at the raise site.
"""

from __future__ import annotations

from tfex_s50_multi_tf_swing.adapters.errors import TfexS50Error


class DataError(TfexS50Error):
    """Generic data-pipeline failure."""


class FetcherError(DataError):
    """Raised when fetching OHLCV from an upstream provider fails terminally."""


class ValidationError(DataError):
    """Raised when an OHLCV frame fails a hard validation check."""


class ContinuousContractError(DataError):
    """Raised when the back-adjusted continuous series cannot be built."""


class SessionError(DataError):
    """Raised when a session-calendar lookup is asked something nonsensical."""


class StoreError(DataError):
    """Raised when Parquet read/write fails or the on-disk schema is wrong."""


class DbWriterError(DataError):
    """Raised when the TimescaleDB mirror write fails."""


class EngineTimeframeUnavailableError(DataError):
    """Raised when the ``engine`` OHLCV source is asked for a timeframe the
    Market Data Engine read API does not serve.

    Currently this is ``'4h'``: the engine exposes only ``1d | 1h | 5m`` and a
    ``cagg_ohlcv_4h`` continuous aggregate exists but is not yet routed. Per
    Decision D10 coarser timeframes must come from continuous aggregates, never
    a local rollup — so the engine path declines 4h rather than rolling it up.
    """


__all__: list[str] = [
    "ContinuousContractError",
    "DataError",
    "DbWriterError",
    "EngineTimeframeUnavailableError",
    "FetcherError",
    "SessionError",
    "StoreError",
    "ValidationError",
]
