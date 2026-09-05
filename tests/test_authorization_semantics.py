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
