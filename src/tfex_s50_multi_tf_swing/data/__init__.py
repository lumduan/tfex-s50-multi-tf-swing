"""Phase 1 data infrastructure.

Public surface (re-exports the most commonly imported symbols so callers
don't need to know the sub-module layout).
"""

from __future__ import annotations

from tfex_s50_multi_tf_swing.data.continuous import ContinuousBuilder
from tfex_s50_multi_tf_swing.data.contracts import (
    ENGINE_CONTINUOUS_SYMBOL,
    TV_CONTINUOUS_SYMBOL,
    engine_symbol_for_contract,
    expiry_for,
    iter_contracts,
    next_active_contract,
    tv_symbol_for_contract,
)
from tfex_s50_multi_tf_swing.data.db_writer import OhlcvDbWriter
from tfex_s50_multi_tf_swing.data.engine_fetcher import EngineOhlcvFetcher, engine_timeframe
from tfex_s50_multi_tf_swing.data.errors import (
    ContinuousContractError,
    DataError,
    DbWriterError,
    EngineTimeframeUnavailableError,
    FetcherError,
    SessionError,
    StoreError,
    ValidationError,
)
from tfex_s50_multi_tf_swing.data.fetcher import OhlcvFetcher
from tfex_s50_multi_tf_swing.data.models import (
    TIMEFRAMES,
    ContinuousBar,
    ContinuousCrossCheck,
    ContractSpec,
    OhlcvBar,
    RollRecord,
    SessionWindow,
    Timeframe,
    ValidationIssue,
    ValidationReport,
)
from tfex_s50_multi_tf_swing.data.refresh import FetcherProtocol, RefreshSummary, refresh_all
from tfex_s50_multi_tf_swing.data.session import SessionCalendar
from tfex_s50_multi_tf_swing.data.sources import build_ohlcv_fetcher
from tfex_s50_multi_tf_swing.data.store import ParquetStore
from tfex_s50_multi_tf_swing.data.validator import Validator

__all__: list[str] = [
    "ENGINE_CONTINUOUS_SYMBOL",
    "TIMEFRAMES",
    "TV_CONTINUOUS_SYMBOL",
    "ContinuousBar",
    "ContinuousBuilder",
    "ContinuousContractError",
    "ContinuousCrossCheck",
    "ContractSpec",
    "DataError",
    "DbWriterError",
    "EngineOhlcvFetcher",
    "EngineTimeframeUnavailableError",
    "FetcherError",
    "FetcherProtocol",
    "OhlcvBar",
    "OhlcvDbWriter",
    "OhlcvFetcher",
    "ParquetStore",
    "RefreshSummary",
    "RollRecord",
    "SessionCalendar",
    "SessionError",
    "SessionWindow",
    "StoreError",
    "Timeframe",
    "ValidationError",
    "ValidationIssue",
    "ValidationReport",
    "Validator",
    "build_ohlcv_fetcher",
    "engine_symbol_for_contract",
    "engine_timeframe",
    "expiry_for",
    "iter_contracts",
    "next_active_contract",
    "refresh_all",
    "tv_symbol_for_contract",
]
