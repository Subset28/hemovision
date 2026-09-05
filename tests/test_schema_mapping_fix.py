"""Tests for the Phase H schema-mapping fix (post-DRYRUN-0007-revision
audit): research/baseline_lookup.py, research/dry_run/pipeline.py's
_build_proposal wiring of baseline_metrics/allowed_path_scope/the 7
previously-unmapped ProposalResponse fields, and
research/experiment_validator.py's placeholder-garbage rejection +
NEEDS_HUMAN_REVIEW additions. No LLM call anywhere in this file.
"""

from __future__ import annotations

import json

import pytest

from research.baseline_lookup import load_baseline_metrics
from research.experiment_spec import SCHEMA_VERSION, ExperimentProposal, ExperimentSpec
from research.experiment_validator import validate
from research.llm.structured_output import ProposalResponse


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
        isolation_requirements="No training involved; not applicable.",
        dataset_version="eval_manifest.jsonl v1 (380 images)",
        model_config_ref="benchmark/config.py conf=0.4 iou=0.7 imgsz=640",
        compute_resource_estimate={"gpu": "RTX 3070 Ti", "estimated_gpu_hours": 0.5},
    )
    defaults.update(overrides)
    return ExperimentProposal(**defaults)


# ---------------------------------------------------------------------------
# research/baseline_lookup.py
# ---------------------------------------------------------------------------


class TestLoadBaselineMetrics:
    def test_matching_run_id_returns_real_recorded_numbers(self):
        # RUN-20260904-002 is the repo's real, checked-in baseline artifact.
        metrics = load_baseline_metrics("RUN-20260904-002")
        assert metrics["run_id"] == "RUN-20260904-002"
        assert metrics["hazard_precision"] is not None
        assert 0.0 <= metrics["hazard_precision"] <= 1.0
        assert metrics["hazard_recall"] is not None

    def test_mismatched_run_id_returns_empty_not_a_guess(self):
        assert load_baseline_metrics("RUN-DOES-NOT-EXIST") == {}

    def test_missing_metrics_file_returns_empty(self, tmp_path, monkeypatch):
        import research.baseline_lookup as baseline_lookup_mod

        monkeypatch.setattr(baseline_lookup_mod, "BASELINE_RESULTS_DIR", tmp_path / "nonexistent")
        assert load_baseline_metrics("RUN-20260904-002") == {}


# ---------------------------------------------------------------------------
# research/dry_run/pipeline.py::_build_proposal -- deterministic mapping
# ---------------------------------------------------------------------------


def _make_proposal_response(**overrides) -> ProposalResponse:
    defaults = dict(
        selected_problem="p", selection_rationale="r", title="t", family="threshold_postprocessing",
        research_question="rq", hypothesis="h", motivation="m",
        independent_variables=["x"], dependent_variables=["person.recall"],
        control_condition="c", baseline_comparison="bc", success_criteria={"primary_metric": "person.recall"},
        supports_hypothesis_if="s", rejects_hypothesis_if="r2", inconclusive_if="i",
    )
    defaults.update(overrides)
    return ProposalResponse(**defaults)


class TestBuildProposalSchemaMapping:
    def test_baseline_metrics_populated_from_real_artifact_not_llm(self):
        from research.dry_run.pipeline import _build_proposal

        pr = _make_proposal_response()
        proposal = _build_proposal(pr, "EXP-9001", "RUN-20260904-002")
        # LLM has no field for baseline_metrics at all -- this must come
        # from research/baseline_lookup.py, never be empty for the real
        # canonical baseline id.
        assert proposal.baseline_metrics != {}
        assert proposal.baseline_metrics["run_id"] == "RUN-20260904-002"

    def test_baseline_metrics_empty_for_unresolvable_baseline_id(self):
        from research.dry_run.pipeline import _build_proposal

        pr = _make_proposal_response()
        proposal = _build_proposal(pr, "EXP-9001", "RUN-DOES-NOT-EXIST")
        assert proposal.baseline_metrics == {}

    def test_allowed_path_scope_derived_from_registry_not_llm(self):
        from research.dry_run.pipeline import _build_proposal

        pr = _make_proposal_response(family="training_data")
        proposal = _build_proposal(pr, "EXP-9001", "RUN-20260904-002")
        # training_data's registry entry includes "data/" -- ProposalResponse
        # has no field an LLM could have used to say this.
        assert "data/" in proposal.allowed_path_scope

    def test_allowed_path_scope_empty_for_unknown_family(self):
        from research.dry_run.pipeline import _build_proposal

        pr = _make_proposal_response(family="not_a_real_family")
        proposal = _build_proposal(pr, "EXP-9001", "RUN-20260904-002")
        assert proposal.allowed_path_scope == ()

    def test_seven_previously_unmapped_fields_now_flow_through(self):
        from research.dry_run.pipeline import _build_proposal

        pr = _make_proposal_response(
            dataset_version="OIV7 train split v1, hash abc123",
            model_config_ref="PREREQUISITE: checkpoint not yet trained",
            implementation_scope="benchmark/, research/ only",
            expected_artifacts=["exp_coco_seed42_last.pt"],
            reproducibility_requirements="3 seeds: 42, 123, 456",
            isolation_requirements="SHA256 image-ID exclusion vs eval_manifest.jsonl",
            compute_resource_estimate={"gpu": "RTX 3070 Ti", "estimated_gpu_hours": 6},
        )
        proposal = _build_proposal(pr, "EXP-9001", "RUN-20260904-002")
        assert proposal.dataset_version == "OIV7 train split v1, hash abc123"
        assert proposal.model_config_ref == "PREREQUISITE: checkpoint not yet trained"
        assert proposal.implementation_scope == "benchmark/, research/ only"
        assert proposal.expected_artifacts == ("exp_coco_seed42_last.pt",)
        assert proposal.reproducibility_requirements == "3 seeds: 42, 123, 456"
        assert proposal.isolation_requirements == "SHA256 image-ID exclusion vs eval_manifest.jsonl"
        assert proposal.compute_resource_estimate == {"gpu": "RTX 3070 Ti", "estimated_gpu_hours": 6}


# ---------------------------------------------------------------------------
# research/experiment_validator.py -- placeholder-garbage rejection +
# semantic-completeness NEEDS_HUMAN_REVIEW additions
# ---------------------------------------------------------------------------


class TestPlaceholderRejection:
    @pytest.mark.parametrize("field_name", [
        "dataset_version", "model_config_ref", "isolation_requirements",
        "reproducibility_requirements", "implementation_scope",
    ])
    @pytest.mark.parametrize("placeholder", ["TBD", "unknown", "N/A", "  none  ", "..."])
    def test_bare_placeholder_rejected_as_error(self, field_name, placeholder):
        proposal = _minimal_proposal(**{field_name: placeholder})
        result = validate(ExperimentSpec(proposal=proposal))
        codes = [i.code for i in result.errors]
        assert "PLACEHOLDER_VALUE" in codes, f"{field_name}={placeholder!r} should be rejected"

    def test_real_explicit_prerequisite_sentence_not_rejected(self):
        proposal = _minimal_proposal(
            dataset_version="UNKNOWN -- blocking prerequisite: dataset must first be constructed and hashed.",
        )
        result = validate(ExperimentSpec(proposal=proposal))
        codes = [i.code for i in result.errors]
        assert "PLACEHOLDER_VALUE" not in codes

    def test_empty_field_is_needs_human_review_not_placeholder_error(self):
        # Empty is a pre-existing, separate NEEDS_HUMAN_REVIEW signal (can't
        # mechanically judge quality of "nothing") -- not the same as a bare
        # placeholder string, which IS an ERROR.
        proposal = _minimal_proposal(isolation_requirements="")
        result = validate(ExperimentSpec(proposal=proposal))
        error_codes = [i.code for i in result.errors]
        review_codes = [i.code for i in result.needs_human_review]
        assert "PLACEHOLDER_VALUE" not in error_codes
        assert "ISOLATION_REQUIREMENTS_QUALITY" in review_codes

    def test_empty_dataset_version_flagged_needs_human_review(self):
        proposal = _minimal_proposal(dataset_version="")
        result = validate(ExperimentSpec(proposal=proposal))
        assert "DATASET_VERSION_QUALITY" in [i.code for i in result.needs_human_review]

    def test_empty_model_config_ref_flagged_needs_human_review(self):
        proposal = _minimal_proposal(model_config_ref="")
        result = validate(ExperimentSpec(proposal=proposal))
        assert "MODEL_CONFIG_REF_QUALITY" in [i.code for i in result.needs_human_review]

    def test_empty_compute_resource_estimate_flagged_needs_human_review(self):
        proposal = _minimal_proposal(compute_resource_estimate={})
        result = validate(ExperimentSpec(proposal=proposal))
        assert "COMPUTE_ESTIMATE_QUALITY" in [i.code for i in result.needs_human_review]

    def test_placeholder_is_an_error_and_blocks_queue_eligibility(self):
        from research.experiment_validator import is_queue_eligible

        proposal = _minimal_proposal(dataset_version="TBD")
        result = validate(ExperimentSpec(proposal=proposal))
        assert is_queue_eligible(result) is False
