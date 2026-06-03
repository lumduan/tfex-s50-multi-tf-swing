"""Signal-layer exception hierarchy.

Every signal error inherits from :class:`TfexS50Error` (the shared package root) so a caller
can catch the base when it needs to. Use the most specific subclass at the raise site.
"""

from __future__ import annotations

from tfex_s50_multi_tf_swing.adapters.errors import TfexS50Error


class SignalError(TfexS50Error):
    """Root exception for the ``signals`` layer."""


class SignalInputError(SignalError):
    """Raised when a signal-input frame is malformed or missing required columns."""


__all__: list[str] = ["SignalError", "SignalInputError"]
