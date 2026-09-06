"""Phase-I CANDIDATE-0001 postmortem: research/experiment_validator.py's
NEEDS_HUMAN_APPROVAL vs. ERROR distinction, and the queue/execution gates
that must still block on missing approval regardless. No LLM call anywhere
in this file."""

from __future__ import annotations

import pytest

from research import operational_state
from research.experiment_spec import SCHEMA_VERSION, ExperimentProposal, ExperimentSpec
from research.experiment_validator import is_queue_eligible, validate
from research.llm.structured_output import ProposalResponse


def _proposal(**overrides) -> ExperimentProposal:
    defaults = dict(
        schema_version=SCHEMA_VERSION,
        experiment_id="EXP-9001",
        title="t",
        family="threshold_postprocessing",
        hypothesis="h",
        motivation="m",
        research_question="rq",
        baseline_run_id="RUN-20260904-002",
        independent_variables=("x",),
        dependent_variables=("person.recall",),
        control_condition="c",
        baseline_comparison="RUN-20260904-002",
        success_criteria={"primary_metric": "person.recall", "min_meaningful_delta": 0.03},
    )
    defaults.update(overrides)
    return ExperimentProposal(**defaults)


class TestMacIphoneRequiredNeedsApprovalNotError:
    def test_scientifically_valid_but_unapproved_device_work_is_valid_not_error(self):
        proposal = _proposal(family="temporal_pipeline", mac_iphone_required=True)
        result = validate(ExperimentSpec(proposal=proposal))
        assert result.is_valid is True
        assert any(i.code == "UNAPPROVED_MAC_IPHONE_DEPLOYMENT" for i in result.needs_human_approval)
        assert not any(i.code == "UNAPPROVED_MAC_IPHONE_DEPLOYMENT" for i in result.errors)

    def test_device_execution_blocked_via_queue_gate(self):
        proposal = _proposal(family="temporal_pipeline", mac_iphone_required=True)
        result = validate(ExperimentSpec(proposal=proposal))
        assert is_queue_eligible(result) is False

    def test_approving_it_makes_it_queue_eligible(self):
        proposal = _proposal(family="temporal_pipeline", mac_iphone_required=True, mac_iphone_deployment_approved=True)
        result = validate(ExperimentSpec(proposal=proposal))
        assert is_queue_eligible(result) is True


class TestTrainingRequiredNeedsApprovalNotError:
    def test_training_family_unapproved_is_valid_not_error(self):
        proposal = _proposal(family="training_data")
        result = validate(ExperimentSpec(proposal=proposal))
        assert result.is_valid is True
        assert any(i.code == "UNAPPROVED_NEW_TRAINING" for i in result.needs_human_approval)

    def test_training_blocked_via_queue_gate(self):
        proposal = _proposal(family="training_data")
        result = validate(ExperimentSpec(proposal=proposal))
        assert is_queue_eligible(result) is False

    def test_approved_training_is_queue_eligible(self):
        proposal = _proposal(family="training_data", new_training_approved=True)
        result = validate(ExperimentSpec(proposal=proposal))
        assert is_queue_eligible(result) is True


class TestExternalDataRequiredNeedsApprovalNotError:
    def test_external_api_unapproved_is_valid_not_error(self):
        proposal = _proposal(external_api_required=True)
        result = validate(ExperimentSpec(proposal=proposal))
        assert result.is_valid is True
        assert any(i.code == "UNAPPROVED_EXTERNAL_API" for i in result.needs_human_approval)

    def test_external_data_acquisition_blocked_via_queue_gate(self):
        proposal = _proposal(external_api_required=True)
        result = validate(ExperimentSpec(proposal=proposal))
        assert is_queue_eligible(result) is False


class TestProductionModificationNeedsApprovalNotError:
    def test_production_impact_unapproved_is_valid_not_error(self):
        proposal = _proposal(production_impact=True, production_impact_description="x")
        result = validate(ExperimentSpec(proposal=proposal))
        assert result.is_valid is True
        assert any(i.code == "UNAPPROVED_PRODUCTION_IMPACT" for i in result.needs_human_approval)

    def test_production_write_blocked_via_queue_gate(self):
        proposal = _proposal(production_impact=True, production_impact_description="x")
        result = validate(ExperimentSpec(proposal=proposal))
        assert is_queue_eligible(result) is False


class TestQueueGateAlwaysAuthoritative:
    def test_queue_experiment_from_spec_refuses_missing_approval(self):
        from research import orchestrator

        proposal = _proposal(family="temporal_pipeline", mac_iphone_required=True)
        with pytest.raises(orchestrator.QueueGateError):
            orchestrator.queue_experiment_from_spec(ExperimentSpec(proposal=proposal))

    def test_queue_blocked_by_operational_state_regardless_of_approval_status(self):
        """PAUSED/STOPPED still blocks queueing even for an otherwise-fully-
        approved, queue-eligible proposal -- the operational gate and the
        approval gate are independent, both must pass."""
        from research import orchestrator

        operational_state.pause(reason="test")
        proposal = _proposal()  # nothing requires approval, fully queue-eligible on its own
        result = validate(ExperimentSpec(proposal=proposal))
        assert is_queue_eligible(result) is True  # approval-wise it's fine
        with pytest.raises(operational_state.OperationalPausedError):
            orchestrator.queue_experiment_from_spec(ExperimentSpec(proposal=proposal))


class TestApprovalFlagsNeverLlmSettable:
    def test_proposal_response_has_no_approval_fields(self):
        fields = set(ProposalResponse.__dataclass_fields__)
        forbidden = {
            "production_swift_modification_approved", "coreml_model_replacement_approved",
            "new_training_approved", "private_user_data_use_approved", "external_upload_approved",
            "mac_iphone_deployment_approved", "signing_distribution_change_approved",
        }
        assert fields.isdisjoint(forbidden)

    def test_build_proposal_hardcodes_false_regardless_of_revision(self):
        """A revision call reuses the SAME _build_proposal path -- approval
        flags cannot be silently granted or dropped-to-true during
        revision, because there is no field for the LLM to set one on."""
        from research.dry_run.pipeline import _build_proposal

        pr = ProposalResponse(
            selected_problem="p", selection_rationale="r", title="t", family="temporal_pipeline",
            research_question="rq", hypothesis="h", motivation="m",
            independent_variables=["x"], dependent_variables=["person.recall"],
            control_condition="c", baseline_comparison="bc", success_criteria={"primary_metric": "person.recall"},
            supports_hypothesis_if="s", rejects_hypothesis_if="r2", inconclusive_if="i",
            mac_iphone_required=True,
        )
        proposal = _build_proposal(pr, "EXP-9001", "RUN-20260904-002")
        assert proposal.mac_iphone_deployment_approved is False
        assert proposal.mac_iphone_required is True  # the REQUIREMENT is preserved
        for flag in (
            "production_swift_modification_approved", "coreml_model_replacement_approved",
            "new_training_approved", "private_user_data_use_approved", "external_upload_approved",
            "signing_distribution_change_approved",
        ):
            assert getattr(proposal, flag) is False


class TestCoreMLAndSigningRequirementRepresentation:
    """Phase-I CANDIDATE-0002 admission-boundary audit, section 11: closes
    the gap where a proposal had NO way to describe a CoreML-replacement or
    signing/distribution-change requirement independently of the
    (always-False) approval flag."""

    def test_coreml_replacement_required_is_valid_not_error(self):
        proposal = _proposal(coreml_replacement_required=True)
        result = validate(ExperimentSpec(proposal=proposal))
        assert result.is_valid is True
        assert any(i.code == "UNAPPROVED_COREML_REPLACEMENT" for i in result.needs_human_approval)
        assert not is_queue_eligible(result)

    def test_signing_distribution_change_required_is_valid_not_error(self):
        proposal = _proposal(signing_distribution_change_required=True)
        result = validate(ExperimentSpec(proposal=proposal))
        assert result.is_valid is True
        assert any(i.code == "UNAPPROVED_SIGNING_DISTRIBUTION_CHANGE" for i in result.needs_human_approval)
        assert not is_queue_eligible(result)

    def test_llm_cannot_grant_coreml_or_signing_approval(self):
        from research.llm.structured_output import ProposalResponse

        fields = set(ProposalResponse.__dataclass_fields__)
        assert "coreml_model_replacement_approved" not in fields
        assert "signing_distribution_change_approved" not in fields
        # but CAN describe the requirement:
        assert "coreml_replacement_required" in fields
        assert "signing_distribution_change_required" in fields

    def test_build_proposal_never_sets_coreml_or_signing_approval(self):
        from research.dry_run.pipeline import _build_proposal

        pr = ProposalResponse(
            selected_problem="p", selection_rationale="r", title="t", family="threshold_postprocessing",
            research_question="rq", hypothesis="h", motivation="m",
            independent_variables=["x"], dependent_variables=["person.recall"],
            control_condition="c", baseline_comparison="bc", success_criteria={"primary_metric": "person.recall"},
            supports_hypothesis_if="s", rejects_hypothesis_if="r2", inconclusive_if="i",
            coreml_replacement_required=True, signing_distribution_change_required=True,
        )
        proposal = _build_proposal(pr, "EXP-9001", "RUN-20260904-002")
        assert proposal.coreml_replacement_required is True  # requirement preserved
        assert proposal.coreml_model_replacement_approved is False  # approval never granted
        assert proposal.signing_distribution_change_required is True
        assert proposal.signing_distribution_change_approved is False

    def test_approving_coreml_makes_it_queue_eligible(self):
        proposal = _proposal(coreml_replacement_required=True, coreml_model_replacement_approved=True)
        result = validate(ExperimentSpec(proposal=proposal))
        assert is_queue_eligible(result) is True


class TestGenuineInvalidityStillRejects:
    def test_missing_control_condition_is_a_real_error(self):
        proposal = _proposal(control_condition="")
        result = validate(ExperimentSpec(proposal=proposal))
        assert result.is_valid is False
        assert any(i.code == "MISSING_CONTROL_CONDITION" for i in result.errors)
        assert is_queue_eligible(result) is False

    def test_unknown_family_is_a_real_error_not_needs_approval(self):
        proposal = _proposal(family="not_a_real_family")
        result = validate(ExperimentSpec(proposal=proposal))
        assert result.is_valid is False
        assert any(i.code == "UNKNOWN_FAMILY" for i in result.errors)


class TestMissingApprovalNeverMasqueradesAsInvalidity:
    def test_needs_human_approval_never_counted_in_errors_property(self):
        proposal = _proposal(family="temporal_pipeline", mac_iphone_required=True, production_impact=True, production_impact_description="x")
        result = validate(ExperimentSpec(proposal=proposal))
        error_codes = {i.code for i in result.errors}
        assert "UNAPPROVED_MAC_IPHONE_DEPLOYMENT" not in error_codes
        assert "UNAPPROVED_PRODUCTION_IMPACT" not in error_codes
        assert result.is_valid is True


class TestRejectedHypothesisAcknowledgmentArchitecture:
    """Phase-I CANDIDATE-0002 admission-boundary audit finding A: the
    acknowledgment mechanism (research/experiment_validator.py's
    UNACKNOWLEDGED_REJECTED_HYPOTHESIS check) was audited and DELIBERATELY
    KEPT as-is -- acknowledges_rejected_hypothesis_ids remains LLM_SUPPLIED,
    a genuine research-integrity judgment, never satisfiable by citing the
    same id in prior_experiment_ids/evidence_references alone (that would
    let ANY proposal that merely cites prior work as background -- normal,
    encouraged practice -- silently satisfy acknowledgment of a REJECTED
    direction it may just be quietly repeating). See
    reports/phase_i/PHASE_I_ADMISSION_BOUNDARY_AUDIT.md for the full
    reasoning. These tests prove the (unchanged) mechanism still behaves
    correctly under both a genuine repeat and a genuinely-acknowledged
    materially-new proposal."""

    def test_citing_rejected_exp_id_in_prior_experiment_ids_alone_does_not_acknowledge(self):
        """CANDIDATE-0002's exact failure mode: EXP-0005/MEM-0014 cited in
        prior_experiment_ids/evidence_references, but NOT in
        acknowledges_rejected_hypothesis_ids -- must still be flagged as
        unacknowledged. Proves the fix did NOT broaden the acknowledged-set
        to include those fields."""
        proposal = _proposal(
            family="model_variant",
            independent_variables=("model checkpoint/architecture",),  # overlaps EXP-0005/MEM-0014
            prior_experiment_ids=("EXP-0005",),
            evidence_references=(),
            acknowledges_rejected_hypothesis_ids=(),  # NOT populated -- the actual CANDIDATE-0002 gap
            materially_new_rationale="",
        )
        result = validate(ExperimentSpec(proposal=proposal))
        assert any(i.code == "UNACKNOWLEDGED_REJECTED_HYPOTHESIS" for i in result.errors)
        assert result.is_valid is False

    def test_genuine_repeat_with_only_rationale_no_id_still_rejects(self):
        """A materially_new_rationale alone, without the explicit id in
        acknowledges_rejected_hypothesis_ids, is NOT sufficient -- this is
        the deliberate design choice (Option A), not a bug."""
        proposal = _proposal(
            family="model_variant",
            independent_variables=("model checkpoint/architecture",),
            acknowledges_rejected_hypothesis_ids=(),
            materially_new_rationale="This is totally different, trust me.",
        )
        result = validate(ExperimentSpec(proposal=proposal))
        assert any(i.code == "UNACKNOWLEDGED_REJECTED_HYPOTHESIS" for i in result.errors)

    def test_explicit_acknowledgment_with_rationale_passes(self):
        """The correct way to satisfy this gate -- explicit id AND a
        substantive rationale -- still works exactly as designed."""
        proposal = _proposal(
            family="model_variant",
            independent_variables=("model checkpoint/architecture",),
            acknowledges_rejected_hypothesis_ids=("EXP-0005",),
            materially_new_rationale="Unlike EXP-0005's architecture-only comparison, this combines "
                                     "a checkpoint shift with a preprocessing transform to target a "
                                     "different failure subset.",
        )
        result = validate(ExperimentSpec(proposal=proposal))
        assert not any(i.code == "UNACKNOWLEDGED_REJECTED_HYPOTHESIS" for i in result.errors)
        assert not any(i.code == "MISSING_MATERIALLY_NEW_RATIONALE" for i in result.errors)

    def test_acknowledged_id_without_rationale_still_rejects(self):
        """Listing the id alone, with an EMPTY rationale, is also
        insufficient -- both are required, acknowledgment is never reduced
        to a bare ID-matching exercise."""
        proposal = _proposal(
            family="model_variant",
            independent_variables=("model checkpoint/architecture",),
            acknowledges_rejected_hypothesis_ids=("EXP-0005",),
            materially_new_rationale="",
        )
        result = validate(ExperimentSpec(proposal=proposal))
        assert any(i.code == "MISSING_MATERIALLY_NEW_RATIONALE" for i in result.errors)
