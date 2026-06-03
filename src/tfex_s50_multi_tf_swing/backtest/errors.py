"""Backtest-layer exception hierarchy (inherits the shared :class:`TfexS50Error` root)."""

from __future__ import annotations

from tfex_s50_multi_tf_swing.adapters.errors import TfexS50Error


class BacktestError(TfexS50Error):
    """Root exception for the ``backtest`` layer."""


__all__: list[str] = ["BacktestError"]
