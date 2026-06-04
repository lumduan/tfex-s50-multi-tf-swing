"""Capital-deployment ladder tests (ROADMAP §7.5)."""

from __future__ import annotations

import pytest

from tfex_s50_multi_tf_swing.risk.ladder import max_contracts_for_stage
from tfex_s50_multi_tf_swing.risk.models import DEPLOYMENT_STAGES, LadderEvidence, RiskConfig

CFG = RiskConfig()
FULL_VALIDATED = LadderEvidence(
    months_live=6.0, expectancy_stable=True, drawdown_within_budget=True
)
FULL_SCALE = LadderEvidence(months_live=12.0, expectancy_stable=True, drawdown_within_budget=True)
NO_EVIDENCE = LadderEvidence()


def test_paper_is_zero() -> None:
    assert max_contracts_for_stage("paper", FULL_SCALE, CFG) == 0


def test_micro_live_is_one() -> None:
    assert max_contracts_for_stage("micro_live", NO_EVIDENCE, CFG) == 1


def test_validated_with_evidence() -> None:
    assert max_contracts_for_stage("validated", FULL_VALIDATED, CFG) == 2


@pytest.mark.parametrize(
    "evidence",
    [
        LadderEvidence(months_live=3.0, expectancy_stable=True, drawdown_within_budget=True),
        LadderEvidence(months_live=6.0, expectancy_stable=False, drawdown_within_budget=True),
        LadderEvidence(months_live=6.0, expectancy_stable=True, drawdown_within_budget=False),
    ],
)
def test_validated_without_evidence_caps_to_micro(evidence: LadderEvidence) -> None:
    assert max_contracts_for_stage("validated", evidence, CFG) == 1


def test_scale_with_full_evidence() -> None:
    assert max_contracts_for_stage("scale", FULL_SCALE, CFG) == 4


def test_scale_with_only_validated_evidence_caps_to_validated() -> None:
    assert max_contracts_for_stage("scale", FULL_VALIDATED, CFG) == 2


def test_scale_without_evidence_caps_to_micro() -> None:
    assert max_contracts_for_stage("scale", NO_EVIDENCE, CFG) == 1


def test_every_stage_is_covered() -> None:
    for stage in DEPLOYMENT_STAGES:
        assert max_contracts_for_stage(stage, FULL_SCALE, CFG) >= 0
