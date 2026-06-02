"""Adapter exception hierarchy.

Every adapter error inherits from :class:`TfexS50Error` so callers can catch
the shared base when they need to (e.g. the post-refresh hook treats every
adapter failure as recoverable). Use the most specific subclass at the
raise site.
"""

from __future__ import annotations


class TfexS50Error(Exception):
    """Root exception for the ``tfex_s50_multi_tf_swing`` package."""


class AdapterError(TfexS50Error):
    """Generic adapter error — superclass for all write-back failures."""


class GatewayClientError(AdapterError):
    """Raised when posting to ``quant-api-gateway`` fails terminally
    (4xx response, or 5xx + transport failures after all retries).
    """


class MarketDataEngineError(AdapterError):
    """Raised when a read from the Market Data Engine fails terminally
    (4xx response, an unparseable body, or 5xx + transport failures after all
    retries). Carries no tvkit credential and never echoes the API key.
    """


__all__: list[str] = [
    "AdapterError",
    "GatewayClientError",
    "MarketDataEngineError",
    "TfexS50Error",
]
