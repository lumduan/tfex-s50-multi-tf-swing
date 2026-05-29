"""Exception hierarchy for the ``features`` sub-package.

Roots at :class:`tfex_s50_multi_tf_swing.adapters.errors.TfexS50Error` so the
shared base catches every package-level failure. Use the most specific subclass
at the raise site. Features fail loudly on malformed or insufficient input
rather than silently emitting NaN-filled columns.
"""

from __future__ import annotations

from tfex_s50_multi_tf_swing.adapters.errors import TfexS50Error


class FeatureError(TfexS50Error):
    """Generic feature-engineering failure."""


class FeatureInputError(FeatureError):
    """Raised when an input OHLCV frame violates the feature input contract.

    Covers tz-naive / non-UTC timestamps, non-monotonic or duplicate
    timestamps, and missing required columns.
    """


class InsufficientLookbackError(FeatureError):
    """Raised when a frame is shorter than the largest configured window.

    Leading rows with insufficient lookback are emitted as ``null`` by design;
    this error fires only when the *entire* frame is too short to compute any
    well-defined value for a feature group.
    """


class FeatureSchemaError(FeatureError):
    """Raised when a produced panel does not match the registered schema."""


class AlignmentError(FeatureError):
    """Raised when a multi-timeframe alignment request is inconsistent."""


__all__: list[str] = [
    "AlignmentError",
    "FeatureError",
    "FeatureInputError",
    "FeatureSchemaError",
    "InsufficientLookbackError",
]
