"""Capital-deployment ladder (ROADMAP §7.5) as a runtime guard.

The ladder caps the maximum contracts by deployment stage:

==============  ==================  =====================================================
Stage           Max contracts       Required evidence
==============  ==================  =====================================================
``paper``       0                   none — validate logic only
``micro_live``  1                   strategy passed the paper window
``validated``   2                   ≥ ``validated_min_months_live`` live + stable expectancy
                                    + drawdown within budget
``scale``       step up carefully   ≥ ``scale_min_months_live`` live + stable expectancy
                                    + drawdown within budget
==============  ==================  =====================================================

**Scale only on statistical evidence, never on confidence.** A requested stage whose evidence is
not met is **capped down** to the highest rung the evidence supports — the guard never grants a
size the data does not justify. The real evidence inputs are produced by Phase 9 (paper) /
Phase 10 (live); they are data-gated today, so an unproven strategy stays at micro-live.
"""

from __future__ import annotations

import logging

from tfex_s50_multi_tf_swing.risk.models import (
    DeploymentStage,
    LadderEvidence,
    RiskConfig,
)

logger = logging.getLogger(__name__)


def _meets(evidence: LadderEvidence, min_months: float) -> bool:
    """True when live duration + expectancy + drawdown evidence clears ``min_months``."""
    return (
        evidence.months_live >= min_months
        and evidence.expectancy_stable
        and evidence.drawdown_within_budget
    )


def max_contracts_for_stage(
    stage: DeploymentStage,
    evidence: LadderEvidence,
    config: RiskConfig,
) -> int:
    """Return the max contracts permitted at ``stage`` given ``evidence``.

    ``paper`` ⇒ 0, ``micro_live`` ⇒ ``micro_live_max_contracts``. ``validated`` / ``scale`` grant
    their cap only when the evidence clears the corresponding ``*_min_months_live`` threshold (plus
    stable expectancy and drawdown within budget); otherwise the cap falls back to the highest rung
    the evidence supports.
    """
    if stage == "paper":
        return 0
    if stage == "micro_live":
        return config.micro_live_max_contracts

    validated_ok = _meets(evidence, config.validated_min_months_live)
    if stage == "validated":
        cap = config.validated_max_contracts if validated_ok else config.micro_live_max_contracts
        if not validated_ok:
            logger.info("validated stage requested without evidence; capping to micro-live")
        return cap

    # stage == "scale"
    if _meets(evidence, config.scale_min_months_live):
        return config.scale_max_contracts
    if validated_ok:
        logger.info("scale requested with only validated-level evidence; capping to validated")
        return config.validated_max_contracts
    logger.info("scale stage requested without evidence; capping to micro-live")
    return config.micro_live_max_contracts


__all__: list[str] = ["max_contracts_for_stage"]
