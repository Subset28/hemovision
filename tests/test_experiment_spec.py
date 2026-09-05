"""Phase F tests — research/experiment_spec.py, research/experiment_validator.py,
research/experiment_spec_migrations.py, research/backfill_experiment_specs.py,
and the queue gate in research/orchestrator.py.

No LLM call anywhere in this file. Tests that touch OPENROUTER_API_KEY
explicitly clear/mock the environment rather than reading the real key's
value, per the Phase F hard boundary.
"""

from __future__ import annotations

import json
import os

import pytest

from research.experiment_spec import (
    Amendment,
    ExperimentProposal,
    ExperimentResult,
    ExperimentSpec,
    FrozenProposalTamperedError,
    ProposalContainsResultFieldsError,
    SCHEMA_VERSION,
    SpecStatusError,
    check_no_result_fields_in_proposal,
)
from research.experiment_spec_migrations import UnsupportedSchemaVersionError, migrate_proposal_dict
from research.experiment_validator import (
    KNOWN_METRIC_GROUPS,
    find_rejected_hypothesis_conflicts,
    is_queue_eligible,
    resolve_baseline_run_dir,
    validate,
)
from research.db import OmniLabDB
from research.memory_db import MemoryDB


def _minimal_proposal(**overrides) -> ExperimentProposal:
    defaults = dict(
        schema_version=SCHEMA_VERSION,
        experiment_id="EXP-9001",
        title="Test proposal",
        family="threshold_postprocessing",
        hypothesis="Some hypothesis.",
        motivation="Some motivation.",
        research_question="Some question?",
        baseline_run_id="RUN-20260904-002",
        independent_variables=("some_variable",),
        dependent_variables=("person.recall",),
        control_condition="baseline conf=0.4",
        baseline_comparison="RUN-20260904-002",
        success_criteria={"primary_metric": "person.recall", "min_meaningful_delta": 0.03, "precision_floor": 0.75},
        procedure="Do the thing.",
        reproducibility_requirements="Re-run from manifest.",
    )
    defaults.update(overrides)
    return ExperimentProposal(**defaults)


# ---------------------------------------------------------------------------
# Basic validity
# ---------------------------------------------------------------------------


def test_valid_experiment_accepted():
    spec = ExperimentSpec(proposal=_minimal_proposal())
    result = validate(spec)
    assert result.is_valid, [i.message for i in result.errors]
    assert is_queue_eligible(result)


def test_missing_hypothesis_rejected():
    spec = ExperimentSpec(proposal=_minimal_proposal(hypothesis=""))
    result = validate(spec)
    assert not result.is_valid
    assert any(i.code == "MISSING_HYPOTHESIS" for i in result.errors)


def test_missing_motivation_rejected():
    spec = ExperimentSpec(proposal=_minimal_proposal(motivation=""))
    result = validate(spec)
    assert any(i.code == "MISSING_MOTIVATION" for i in result.errors)


def test_bad_baseline_ref_rejected():
    spec = ExperimentSpec(proposal=_minimal_proposal(baseline_run_id="RUN-NOT-REAL"))
    result = validate(spec)
    assert any(i.code == "BAD_BASELINE_REF" for i in result.errors)


def test_real_baseline_resolves():
    assert resolve_baseline_run_dir("RUN-20260904-002") is not None
    assert resolve_baseline_run_dir("RUN-DOES-NOT-EXIST") is None


def test_bad_memory_finding_ref_rejected():
    spec = ExperimentSpec(proposal=_minimal_proposal(evidence_references=("MEM-9999",)))
    result = validate(spec)
    assert any(i.code == "BAD_EVIDENCE_REF" for i in result.errors)


def test_good_memory_finding_ref_accepted():
    spec = ExperimentSpec(proposal=_minimal_proposal(evidence_references=("MEM-0001",)))
    result = validate(spec)
    assert not any(i.code == "BAD_EVIDENCE_REF" for i in result.errors)


def test_duplicate_id_rejected():
    spec = ExperimentSpec(proposal=_minimal_proposal(experiment_id="EXP-0001"))
    result = validate(spec)
    assert any(i.code == "DUPLICATE_ID" for i in result.errors)


def test_malformed_experiment_id_rejected():
    with pytest.raises(ValueError):
        _minimal_proposal(experiment_id="not-an-id")


def test_malformed_metric_rejected():
    spec = ExperimentSpec(proposal=_minimal_proposal(
        success_criteria={"primary_metric": "totally.bogus.metric", "min_meaningful_delta": 0.03}
    ))
    result = validate(spec)
    assert any(i.code == "INVALID_METRIC_NAME" for i in result.errors)


def test_known_metric_groups_include_person_and_hazard():
    assert "person" in KNOWN_METRIC_GROUPS
    assert "hazard" in KNOWN_METRIC_GROUPS


def test_contradictory_success_criteria_negative_delta_rejected():
    spec = ExperimentSpec(proposal=_minimal_proposal(
        success_criteria={"primary_metric": "person.recall", "min_meaningful_delta": -0.03}
    ))
    result = validate(spec)
    assert any(i.code == "CONTRADICTORY_SUCCESS_CRITERIA" for i in result.errors)


def test_contradictory_success_criteria_precision_floor_above_one_rejected():
    spec = ExperimentSpec(proposal=_minimal_proposal(
        success_criteria={"primary_metric": "person.recall", "precision_floor": 1.5}
    ))
    result = validate(spec)
    assert any(i.code == "CONTRADICTORY_SUCCESS_CRITERIA" for i in result.errors)


def test_missing_success_criteria_rejected():
    spec = ExperimentSpec(proposal=_minimal_proposal(success_criteria={}))
    result = validate(spec)
    assert any(i.code == "MISSING_SUCCESS_CRITERIA" for i in result.errors)


def test_missing_independent_variable_rejected():
    spec = ExperimentSpec(proposal=_minimal_proposal(independent_variables=()))
    result = validate(spec)
    assert any(i.code == "MISSING_INDEPENDENT_VARIABLE" for i in result.errors)


def test_missing_dependent_variables_rejected():
    spec = ExperimentSpec(proposal=_minimal_proposal(dependent_variables=()))
    result = validate(spec)
    assert any(i.code == "MISSING_DEPENDENT_VARIABLES" for i in result.errors)


def test_missing_control_condition_rejected():
    spec = ExperimentSpec(proposal=_minimal_proposal(control_condition=""))
    result = validate(spec)
    assert any(i.code == "MISSING_CONTROL_CONDITION" for i in result.errors)


def test_missing_baseline_comparison_rejected():
    spec = ExperimentSpec(proposal=_minimal_proposal(baseline_comparison=""))
    result = validate(spec)
    assert any(i.code == "MISSING_BASELINE_COMPARISON" for i in result.errors)


def test_unsupported_family_rejected():
    spec = ExperimentSpec(proposal=_minimal_proposal(family="not_a_real_family"))
    result = validate(spec)
    assert any(i.code == "UNKNOWN_FAMILY" for i in result.errors)


def test_unchecked_conditions_surface_as_needs_human_review():
    spec = ExperimentSpec(proposal=_minimal_proposal())
    result = validate(spec)
    assert any(i.level == "NEEDS_HUMAN_REVIEW" and i.code == "SCIENTIFIC_MERIT" for i in result.issues)


# ---------------------------------------------------------------------------
# #3 — proposal/result separation
# ---------------------------------------------------------------------------


def test_result_fields_rejected_from_proposal_dict():
    data = _minimal_proposal().to_dict()
    data["metrics"] = {"person": {"recall": 0.9}}  # a result-only field smuggled in
    with pytest.raises(ProposalContainsResultFieldsError):
        check_no_result_fields_in_proposal(data)
    with pytest.raises(ProposalContainsResultFieldsError):
        ExperimentProposal.from_dict(data)


def test_result_fields_populated_before_execution_status_rejected():
    spec = ExperimentSpec(proposal=_minimal_proposal())
    spec.result = ExperimentResult(metrics={"person": {"recall": 0.9}})  # execution_status still None
    result = validate(spec)
    assert any(i.code == "PREMATURE_RESULT_FIELDS" for i in result.errors)


def test_completed_result_can_link_metrics_and_artifacts():
    spec = ExperimentSpec(proposal=_minimal_proposal())
    spec.result = ExperimentResult(
        execution_status="COMPLETED",
        research_verdict="PASS",
        metrics={"person": {"recall": 0.9}},
        benchmark_artifact_paths=("experiments/completed/EXP-9001/results.json",),
    )
    result = validate(spec)
    assert not any(i.code == "PREMATURE_RESULT_FIELDS" for i in result.errors)


# ---------------------------------------------------------------------------
# #4 — freeze / amendment
# ---------------------------------------------------------------------------


def test_freeze_then_amend_produces_traceable_record():
    spec = ExperimentSpec(proposal=_minimal_proposal())
    spec.freeze("VALIDATED")
    assert spec.is_frozen()
    old_hyp = spec.proposal.hypothesis
    amendment = spec.amend("hypothesis", "A revised hypothesis.", reason="clarified after review", approved_by="human via CLI")
    assert isinstance(amendment, Amendment)
    assert amendment.old_value == old_hyp
    assert amendment.new_value == "A revised hypothesis."
    assert amendment.reason == "clarified after review"
    assert amendment.approved_by == "human via CLI"
    assert amendment.timestamp
    assert spec.proposal.hypothesis == "A revised hypothesis."
    assert len(spec.amendments) == 1
    # verify_integrity must still pass after a legitimate amend()
    spec.verify_integrity()


def test_amend_without_freeze_raises():
    spec = ExperimentSpec(proposal=_minimal_proposal())
    with pytest.raises(SpecStatusError):
        spec.amend("hypothesis", "x", reason="y")


def test_frozen_proposal_tampering_detected():
    spec = ExperimentSpec(proposal=_minimal_proposal())
    spec.freeze("VALIDATED")
    # Simulate silent, out-of-band mutation (bypassing amend()) by directly
    # replacing the proposal without updating frozen_hash.
    from dataclasses import replace
    spec.proposal = replace(spec.proposal, hypothesis="tampered")
    with pytest.raises(FrozenProposalTamperedError):
        spec.verify_integrity()


def test_success_criteria_frozen_after_approval():
    """Success criteria (part of the frozen proposal payload) cannot be
    changed except via amend() once frozen — this is the concrete Phase F
    item #4 requirement."""
    spec = ExperimentSpec(proposal=_minimal_proposal())
    spec.freeze("APPROVED")
    with pytest.raises(Exception):
        # frozen dataclass: direct attribute assignment must fail outright.
        spec.proposal.success_criteria = {"primary_metric": "hazard.precision"}
    # the sanctioned path works and is traceable:
    amendment = spec.amend(
        "success_criteria", {"primary_metric": "hazard.precision", "min_meaningful_delta": 0.05},
        reason="scope correction", approved_by="human via CLI",
    )
    assert amendment.field_name == "success_criteria"


# ---------------------------------------------------------------------------
# #5/#9 — queue gate
# ---------------------------------------------------------------------------


def test_queue_blocked_for_invalid_spec():
    spec = ExperimentSpec(proposal=_minimal_proposal(hypothesis=""))
    result = validate(spec)
    assert not is_queue_eligible(result)


def test_queue_allowed_for_valid_spec():
    spec = ExperimentSpec(proposal=_minimal_proposal())
    result = validate(spec)
    assert is_queue_eligible(result)


def test_orchestrator_refuses_to_queue_invalid_spec(tmp_path, monkeypatch):
    from research import orchestrator

    spec = ExperimentSpec(proposal=_minimal_proposal(hypothesis=""))
    with pytest.raises(orchestrator.QueueGateError):
        orchestrator.queue_experiment_from_spec(spec)


# ---------------------------------------------------------------------------
# #8 — rejected-hypothesis acknowledgment
# ---------------------------------------------------------------------------


def test_naive_reproposal_of_lower_confidence_is_caught():
    """EXP-0001/MEM-0010 already rejected 'lower the global confidence
    threshold alone'. A naive re-proposal in the same family with an
    overlapping independent-variable keyword must be flagged unless it
    explicitly acknowledges the prior rejection with new rationale."""
    proposal = _minimal_proposal(
        experiment_id="EXP-9002",
        family="threshold_postprocessing",
        independent_variables=("lower confidence threshold to 0.1",),
    )
    spec = ExperimentSpec(proposal=proposal)
    result = validate(spec)
    assert any(i.code == "UNACKNOWLEDGED_REJECTED_HYPOTHESIS" for i in result.errors)

    with MemoryDB() as mdb:
        conflicts = find_rejected_hypothesis_conflicts(proposal, mdb)
    assert any(exp_id == "EXP-0001" for exp_id, _ in conflicts)


def test_acknowledged_reproposal_with_rationale_passes_that_check():
    proposal = _minimal_proposal(
        experiment_id="EXP-9003",
        family="threshold_postprocessing",
        independent_variables=("lower confidence threshold to 0.1",),
        acknowledges_rejected_hypothesis_ids=("EXP-0001",),
        materially_new_rationale="This proposal additionally applies a class-specific floor, unlike EXP-0001's global-only change.",
    )
    spec = ExperimentSpec(proposal=proposal)
    result = validate(spec)
    assert not any(i.code == "UNACKNOWLEDGED_REJECTED_HYPOTHESIS" for i in result.errors)
    assert not any(i.code == "MISSING_MATERIALLY_NEW_RATIONALE" for i in result.errors)


def test_acknowledged_reproposal_without_rationale_still_fails():
    proposal = _minimal_proposal(
        experiment_id="EXP-9004",
        family="threshold_postprocessing",
        independent_variables=("lower confidence threshold to 0.1",),
        acknowledges_rejected_hypothesis_ids=("EXP-0001",),
        materially_new_rationale="",
    )
    spec = ExperimentSpec(proposal=proposal)
    result = validate(spec)
    assert any(i.code == "MISSING_MATERIALLY_NEW_RATIONALE" for i in result.errors)


# ---------------------------------------------------------------------------
# #10 — human authority flags + API-key decoupling
# ---------------------------------------------------------------------------


def test_protected_production_action_requires_explicit_approval():
    spec = ExperimentSpec(proposal=_minimal_proposal(
        production_impact=True, production_impact_description="modifies StepHazardDetector.swift",
        production_swift_modification_approved=False,
    ))
    result = validate(spec)
    assert any(i.code == "UNAPPROVED_PRODUCTION_IMPACT" for i in result.errors)

    spec2 = ExperimentSpec(proposal=_minimal_proposal(
        production_impact=True, production_impact_description="modifies StepHazardDetector.swift",
        production_swift_modification_approved=True,
    ))
    result2 = validate(spec2)
    assert not any(i.code == "UNAPPROVED_PRODUCTION_IMPACT" for i in result2.errors)


def test_private_data_use_requires_approval():
    spec = ExperimentSpec(proposal=_minimal_proposal(data_privacy_classification="PRIVATE_USER_DATA"))
    result = validate(spec)
    assert any(i.code == "UNAPPROVED_PRIVATE_DATA_USE" for i in result.errors)


def test_external_api_required_does_not_imply_authorization(monkeypatch):
    """External-API requirement and external-upload authorization are
    completely decoupled fields. This test also proves the decoupling holds
    regardless of OPENROUTER_API_KEY's presence in the environment — the
    key's value is NEVER read, printed, or used by this test or by the
    validator; only presence/absence of the env var name is exercised, and
    only via a mocked/cleared environment, never the real key."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-placeholder-not-a-real-key")
    assert os.environ.get("OPENROUTER_API_KEY")  # presence check only — value never used further

    spec = ExperimentSpec(proposal=_minimal_proposal(external_api_required=True, external_upload_approved=False))
    result = validate(spec)
    assert any(i.code == "UNAPPROVED_EXTERNAL_API" for i in result.errors), (
        "external_api_required=True must still fail validation even though OPENROUTER_API_KEY "
        "is present in the environment — key presence must never imply authorization."
    )

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    spec2 = ExperimentSpec(proposal=_minimal_proposal(external_api_required=True, external_upload_approved=False))
    result2 = validate(spec2)
    assert any(i.code == "UNAPPROVED_EXTERNAL_API" for i in result2.errors), (
        "the same failure must occur identically with the key absent — proving external_api_required's "
        "gating logic never conditions on os.environ at all."
    )

    # Grep-level structural check: experiment_validator.py must not reference
    # OPENROUTER_API_KEY anywhere near external_upload_approved's logic.
    import inspect
    import research.experiment_validator as validator_module
    source = inspect.getsource(validator_module)
    assert "OPENROUTER_API_KEY" not in source or "external_upload_approved" not in source.split("OPENROUTER_API_KEY")[0][-50:]


# ---------------------------------------------------------------------------
# #7 — legacy backfill
# ---------------------------------------------------------------------------

_EXPECTED_BACKFILL = {
    "EXP-0001": ("COMPLETED", "PASS"),
    "EXP-0002": ("COMPLETED", "FAIL"),
    "EXP-0003": ("COMPLETED", "FAIL"),
    "EXP-0004": ("COMPLETED", "INCONCLUSIVE"),
    "EXP-0005": ("COMPLETED", "INCONCLUSIVE"),
}


@pytest.mark.parametrize("experiment_id,expected", _EXPECTED_BACKFILL.items())
def test_legacy_experiments_load_successfully_with_correct_verdicts(experiment_id, expected):
    from research.backfill_experiment_specs import load_spec

    spec = load_spec(experiment_id)
    assert spec.proposal.experiment_id == experiment_id
    assert spec.proposal.schema_version == SCHEMA_VERSION
    assert (spec.result.execution_status, spec.result.research_verdict) == expected


@pytest.mark.parametrize("experiment_id,expected", _EXPECTED_BACKFILL.items())
def test_legacy_backfill_matches_live_db_row(experiment_id, expected):
    with OmniLabDB() as db:
        exp = db.get_experiment(experiment_id)
    assert (exp.execution_status, exp.research_verdict) == expected


def test_legacy_backfill_uses_legacy_markers_not_fabricated_preregistration():
    from research.backfill_experiment_specs import load_spec

    spec = load_spec("EXP-0001")
    # supports_hypothesis_if/rejects_hypothesis_if/inconclusive_if did not
    # exist as discrete pre-registered fields historically — must be marked,
    # never fabricated as if they were really written down at the time.
    assert spec.proposal.supports_hypothesis_if == "NOT_RECORDED"
    assert spec.proposal.rejects_hypothesis_if == "NOT_RECORDED"
    assert spec.proposal.evidence_references == ()


# ---------------------------------------------------------------------------
# #12 — schema versioning
# ---------------------------------------------------------------------------


def test_serialization_is_deterministic():
    spec = ExperimentSpec(proposal=_minimal_proposal())
    assert spec.to_json() == spec.to_json()


def test_same_major_version_loads_directly():
    data = _minimal_proposal().to_dict()
    data["schema_version"] = "1.7"  # same major, different minor — no registered migration needed
    migrated = migrate_proposal_dict(data, target_version="1.0")
    assert migrated["schema_version"] == "1.0"


def test_different_major_version_without_migration_raises():
    data = _minimal_proposal().to_dict()
    data["schema_version"] = "2.0"
    with pytest.raises(UnsupportedSchemaVersionError):
        migrate_proposal_dict(data, target_version="1.0")


def test_missing_schema_version_raises():
    from research.experiment_spec import SchemaVersionError

    data = _minimal_proposal().to_dict()
    del data["schema_version"]
    with pytest.raises(SchemaVersionError):
        migrate_proposal_dict(data, target_version="1.0")


def test_spec_round_trips_through_json():
    spec = ExperimentSpec(proposal=_minimal_proposal())
    spec.freeze("VALIDATED")
    text = spec.to_json()
    loaded = ExperimentSpec.from_json(text)
    assert loaded.proposal.experiment_id == spec.proposal.experiment_id
    assert loaded.status == "VALIDATED"
    assert loaded.frozen_hash == spec.frozen_hash


# ---------------------------------------------------------------------------
# Regression: PASS/FAIL/INCONCLUSIVE remain a separate axis from
# execution_status (Phase-C invariant) — still true after Phase F.
# ---------------------------------------------------------------------------


def test_execution_status_and_research_verdict_remain_separate_axes():
    result = ExperimentResult(execution_status="COMPLETED", research_verdict="FAIL")
    assert result.execution_status != result.research_verdict
    # a spec's result can be COMPLETED with any of PASS/FAIL/INCONCLUSIVE —
    # nothing in Phase F collapses these back into one axis.
    for verdict in ("PASS", "FAIL", "INCONCLUSIVE"):
        r = ExperimentResult(execution_status="COMPLETED", research_verdict=verdict)
        assert r.execution_status == "COMPLETED"
        assert r.research_verdict == verdict
