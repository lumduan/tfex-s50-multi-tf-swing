"""Execution-layer exception hierarchy (inherits the shared :class:`TfexS50Error` root)."""

from __future__ import annotations

from tfex_s50_multi_tf_swing.adapters.errors import TfexS50Error


class ExecutionError(TfexS50Error):
    """Root exception for the ``execution`` layer."""


class ExecutionInputError(ExecutionError):
    """Raised when a bars frame is malformed or missing required columns."""


# --- Phase 5.1 — engine adapter + sim trade loop -----------------------------


class EngineAdapterError(ExecutionError):
    """Base class for Execution-engine adapter failures (HTTP/SSE transport)."""


class OrderRejectedError(EngineAdapterError):
    """Raised when the engine returns a typed rejection envelope (terminal, never retried).

    Attributes:
        code: The engine ``error.code`` (e.g. ``stage_rejected``, ``risk_rejected``,
            ``kill_switch_engaged``).
        message: The engine ``error.message``.
        client_order_id: The rejected order id, if the envelope carried one.
        status_code: The HTTP status code that carried the rejection.
    """

    def __init__(
        self,
        *,
        code: str,
        message: str,
        client_order_id: str | None = None,
        status_code: int,
    ) -> None:
        self.code: str = code
        self.message: str = message
        self.client_order_id: str | None = client_order_id
        self.status_code: int = status_code
        super().__init__(f"order rejected ({status_code} {code}): {message}")


class StreamError(EngineAdapterError):
    """Raised when the SSE order-update stream fails after exhausting reconnects."""


class StreamResetError(StreamError):
    """Raised when the engine emits ``event: resync_required`` on the stream.

    Attributes:
        after_seq: The sequence number after which the consumer must re-read state.
    """

    def __init__(self, *, after_seq: int) -> None:
        self.after_seq: int = after_seq
        super().__init__(f"stream resync required after seq={after_seq}")


class OrderTimeoutError(EngineAdapterError):
    """Raised/logged when an order does not reach a terminal state in time."""


class ExecutionModeError(ExecutionError):
    """Raised when the sim loop is invoked under an unsupported execution mode."""


class SimLoopError(ExecutionError):
    """Raised on an invalid sim-loop input or state (e.g. unsupported position flip)."""


__all__: list[str] = [
    "EngineAdapterError",
    "ExecutionError",
    "ExecutionInputError",
    "ExecutionModeError",
    "OrderRejectedError",
    "OrderTimeoutError",
    "SimLoopError",
    "StreamError",
    "StreamResetError",
]
