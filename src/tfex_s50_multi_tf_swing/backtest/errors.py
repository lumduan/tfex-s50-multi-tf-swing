"""Backtest-layer exception hierarchy (inherits the shared :class:`TfexS50Error` root)."""

from __future__ import annotations

from tfex_s50_multi_tf_swing.adapters.errors import TfexS50Error


class BacktestError(TfexS50Error):
    """Root exception for the ``backtest`` layer."""


class WalkForwardDataError(BacktestError):
    """The walk-forward harness could not obtain OHLCV from the engine / Parquet snapshot.

    Raised by :mod:`tfex_s50_multi_tf_swing.backtest.data_source` when a required continuous
    frame is missing or empty (engine / gateway unavailable and no local snapshot to fall back
    to). The harness never falls back to a per-strategy tvkit fetch — that boundary is hard.
    """


__all__: list[str] = ["BacktestError", "WalkForwardDataError"]
