"""Risk-engine exception hierarchy (Phase 7).

Every risk error inherits from :class:`TfexS50Error` (the package root, defined in
:mod:`tfex_s50_multi_tf_swing.adapters.errors`) so a caller can catch the shared base. Use
the most specific subclass at the raise site.

These exceptions are reserved for genuine input / configuration / rule violations. A
kill-switch *trip* and a session *halt* are not errors — they are modelled as typed state
(:class:`~tfex_s50_multi_tf_swing.risk.models.KillSwitchState` /
:class:`~tfex_s50_multi_tf_swing.risk.models.SessionRiskState`), because halting is the
engine working as designed, not failing.
"""

from __future__ import annotations

from tfex_s50_multi_tf_swing.adapters.errors import TfexS50Error


class RiskError(TfexS50Error):
    """Generic risk-layer error — superclass for all risk failures."""


class RiskInputError(RiskError):
    """Raised when a sizing input violates the contract.

    Zero / negative equity and a zero / negative stop distance are the canonical cases:
    the latter would be a divide-by-zero in the sizing formula, so it is rejected loudly
    *before* any arithmetic.
    """


class RiskLimitError(RiskError):
    """Raised when an action breaks a hard trading rule.

    Covers averaging down into a losing position (TFEX hard rule #4) and widening a stop
    after entry ("never widen a stop after entry"). These are *forbidden actions*, distinct
    from a session halt (which is expressed as :class:`SessionRiskState.halted`).
    """


class RiskConfigError(RiskError):
    """Raised when a risk configuration is internally inconsistent at use time."""


__all__: list[str] = [
    "RiskConfigError",
    "RiskError",
    "RiskInputError",
    "RiskLimitError",
]
