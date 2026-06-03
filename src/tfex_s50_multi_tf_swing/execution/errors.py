"""Execution-layer exception hierarchy (inherits the shared :class:`TfexS50Error` root)."""

from __future__ import annotations

from tfex_s50_multi_tf_swing.adapters.errors import TfexS50Error


class ExecutionError(TfexS50Error):
    """Root exception for the ``execution`` layer."""


class ExecutionInputError(ExecutionError):
    """Raised when a bars frame is malformed or missing required columns."""


__all__: list[str] = ["ExecutionError", "ExecutionInputError"]
