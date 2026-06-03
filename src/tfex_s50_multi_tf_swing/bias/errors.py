"""Bias-layer exception hierarchy.

Every bias error inherits from :class:`TfexS50Error` (the package root, defined in
:mod:`tfex_s50_multi_tf_swing.adapters.errors`) so callers can catch the shared base.
Use the most specific subclass at the raise site.
"""

from __future__ import annotations

from tfex_s50_multi_tf_swing.adapters.errors import TfexS50Error


class BiasError(TfexS50Error):
    """Generic bias-layer error — superclass for all bias failures."""


class BiasInputError(BiasError):
    """Raised when a frame/feature input violates the classifier contract
    (missing columns, wrong dtype, empty frame).
    """


__all__: list[str] = [
    "BiasError",
    "BiasInputError",
]
