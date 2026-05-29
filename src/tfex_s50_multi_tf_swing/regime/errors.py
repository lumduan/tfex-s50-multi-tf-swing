"""Regime-layer exception hierarchy.

Every regime error inherits from :class:`TfexS50Error` (the package root, defined
in :mod:`tfex_s50_multi_tf_swing.adapters.errors`) so callers can catch the shared
base. Use the most specific subclass at the raise site.
"""

from __future__ import annotations

from tfex_s50_multi_tf_swing.adapters.errors import TfexS50Error


class RegimeError(TfexS50Error):
    """Generic regime-layer error — superclass for all regime failures."""


class RegimeInputError(RegimeError):
    """Raised when a frame/feature input violates the classifier contract
    (missing columns, wrong dtype, empty frame).
    """


class RegimePolicyError(RegimeError):
    """Raised when a regime → strategy policy cannot be resolved."""


class UnknownRegimeError(RegimePolicyError):
    """Raised when a label outside :data:`tfex_s50_multi_tf_swing.regime.models.REGIMES`
    is passed to a policy lookup.
    """


__all__: list[str] = [
    "RegimeError",
    "RegimeInputError",
    "RegimePolicyError",
    "UnknownRegimeError",
]
