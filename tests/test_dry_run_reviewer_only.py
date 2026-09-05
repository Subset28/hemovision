"""Tests for the reviewer-only resume mode (Phase H follow-up):
research/dry_run/pipeline.py::load_preserved_proposal/run_reviewer_only/
write_review_artifact, and research/cli.py's `omnilab dry-run-review`.
All LLM calls mocked -- no network."""

from __future__ import annotations

import json

import pytest

from research.dry_run.budget import DryRunCallBudget
from research.dry_run.pipeline import (
    DRY_RUN_PROPOSALS_DIR,
    load_preserved_proposal,
    run_reviewer_only,
    write_review_artifact,
)
from research.llm.base import LLMProvider, LLMResponse, LLMUnavailableError
from research.llm.router import LLMRouter


def _write_fake_dryrun_json(tmp_path_dir, dryrun_id: str, proposal: dict) -> None:
    path = tmp_path_dir / f"{dryrun_id}.json"
    path.write_text(json.dumps({"dryrun_id": dryrun_id, "proposal": proposal}), encoding="utf-8")


_VALID_PROPOSAL = {
    "schema_version": "1.0",
    "experiment_id": "EXP-9999",
    "title": "t", "family": "training_data", "hypothesis": "h", "motivation": "m",
    "research_question": "rq", "evidence_references": [], "prior_experiment_ids": [],
    "baseline_run_id": "RUN-20260904-002", "independent_variables": ["x"],
    "dependent_variables": ["person.recall"], "controlled_variables": {}, "procedure": "p",
    "control_condition": "c", "baseline_comparison": "bc", "success_criteria": {"primary_metric": "person.recall", "min_meaningful_delta": 0.03},
    "production_impact": False, "production_impact_description": "",
    "data_privacy_classification": "NONE", "external_api_required": False,
    "mac_iphone_required": False, "supports_hypothesis_if": "s", "rejects_hypothesis_if": "r",
    "inconclusive_if": "i", "production_swift_modification_approved": False,
    "coreml_model_replacement_approved": False, "new_training_approved": False,
    "private_user_data_use_approved": False, "external_upload_approved": False,
    "mac_iphone_deployment_approved": False, "signing_distribution_change_approved": False,
    "acknowledges_rejected_hypothesis_ids": [], "materially_new_rationale": "",
}

_REVIEW_JSON = json.dumps({
    "novelty_assessment": "novel", "scientific_validity_assessment": "sound",
    "targets_verified_failure_mode": True, "success_criteria_deterministic": True,
    "confounding_notes": "none", "dataset_can_answer_question": True,
    "sample_size_adequate": True, "leakage_risk_notes": "none",
    "privacy_safety_ok": True, "feasibility_notes": "ok",
    "worth_running": True, "recommends_revision": False, "revision_notes": "",
    "summary": "good",
})


class _FixedProvider(LLMProvider):
    def __init__(self, text_or_exc):
        self.item = text_or_exc
        self.calls = 0

    def complete(self, prompt, role, model="", **kwargs):
        self.calls += 1
        if isinstance(self.item, Exception):
            raise self.item
        return LLMResponse(text=self.item, tokens_used=10, cost_usd=0.0, model_used=model)


def _isolated_router(provider):
    import tempfile
    from pathlib import Path

    from research.llm.base import UsageTracker

    tracker_path = Path(tempfile.mkstemp(suffix=".json")[1])
    return LLMRouter(provider=provider, usage_tracker=UsageTracker(path=tracker_path, max_per_day=1000))


class TestLoadPreservedProposal:
    def test_loads_real_shape_correctly(self, tmp_path, monkeypatch):
        import research.dry_run.pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "DRY_RUN_PROPOSALS_DIR", tmp_path)
        _write_fake_dryrun_json(tmp_path, "DRYRUN-TEST", _VALID_PROPOSAL)
        proposal = load_preserved_proposal("DRYRUN-TEST")
        assert proposal.experiment_id == "EXP-9999"
        assert proposal.hypothesis == "h"

    def test_missing_file_raises(self, tmp_path, monkeypatch):
        import research.dry_run.pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "DRY_RUN_PROPOSALS_DIR", tmp_path)
        with pytest.raises(FileNotFoundError):
            load_preserved_proposal("DRYRUN-NOPE")

    def test_null_proposal_raises_value_error(self, tmp_path, monkeypatch):
        import research.dry_run.pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "DRY_RUN_PROPOSALS_DIR", tmp_path)
        (tmp_path / "DRYRUN-NULL.json").write_text(json.dumps({"dryrun_id": "DRYRUN-NULL", "proposal": None}))
        with pytest.raises(ValueError):
            load_preserved_proposal("DRYRUN-NULL")

    def test_never_writes_to_source_file(self, tmp_path, monkeypatch):
        """The immutability guarantee: loading must never modify the file."""
        import research.dry_run.pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "DRY_RUN_PROPOSALS_DIR", tmp_path)
        _write_fake_dryrun_json(tmp_path, "DRYRUN-IMMUT", _VALID_PROPOSAL)
        path = tmp_path / "DRYRUN-IMMUT.json"
        before = path.read_bytes()
        load_preserved_proposal("DRYRUN-IMMUT")
        after = path.read_bytes()
        assert before == after


class TestRunReviewerOnly:
    def test_successful_review_does_not_mutate_source_proposal(self, tmp_path, monkeypatch):
        import research.dry_run.pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "DRY_RUN_PROPOSALS_DIR", tmp_path)
        _write_fake_dryrun_json(tmp_path, "DRYRUN-REV1", _VALID_PROPOSAL)
        path = tmp_path / "DRYRUN-REV1.json"
        before = path.read_bytes()

        router = _isolated_router(_FixedProvider(_REVIEW_JSON))
        result = run_reviewer_only(
            dryrun_id="DRYRUN-REV1", router=router, authorized=True,
            dry_run_budget=DryRunCallBudget(1),
        )
        assert path.read_bytes() == before  # immutable
        assert result.calls_made == 1
        assert result.reviewer_critique is not None
        assert result.reviewer_critique.recommends_revision is False
        assert result.queue_eligible_in_principle is True

    def test_one_logical_step_one_call(self, tmp_path, monkeypatch):
        import research.dry_run.pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "DRY_RUN_PROPOSALS_DIR", tmp_path)
        _write_fake_dryrun_json(tmp_path, "DRYRUN-REV2", _VALID_PROPOSAL)
        provider = _FixedProvider(_REVIEW_JSON)
        router = _isolated_router(provider)
        run_reviewer_only(dryrun_id="DRYRUN-REV2", router=router, authorized=True, dry_run_budget=DryRunCallBudget(1))
        assert provider.calls == 1

    def test_failed_call_preserved_with_diagnostics_no_crash(self, tmp_path, monkeypatch):
        import research.dry_run.pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "DRY_RUN_PROPOSALS_DIR", tmp_path)
        _write_fake_dryrun_json(tmp_path, "DRYRUN-REV3", _VALID_PROPOSAL)
        router = _isolated_router(_FixedProvider(LLMUnavailableError("boom", diagnostics={"network_attempted": True})))
        result = run_reviewer_only(dryrun_id="DRYRUN-REV3", router=router, authorized=True, dry_run_budget=DryRunCallBudget(1))
        assert result.reviewer_critique is None
        assert "boom" in result.stopped_reason
        assert result.call_records[0].network_attempted is True

    def test_additional_facts_appended_to_prompt(self, tmp_path, monkeypatch):
        import research.dry_run.pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "DRY_RUN_PROPOSALS_DIR", tmp_path)
        _write_fake_dryrun_json(tmp_path, "DRYRUN-REV4", _VALID_PROPOSAL)

        captured_prompts = []

        class CapturingProvider(LLMProvider):
            def complete(self, prompt, role, model="", **kwargs):
                captured_prompts.append(prompt)
                return LLMResponse(text=_REVIEW_JSON, tokens_used=10, cost_usd=0.0, model_used=model)

        router = _isolated_router(CapturingProvider())
        run_reviewer_only(
            dryrun_id="DRYRUN-REV4", router=router, authorized=True, dry_run_budget=DryRunCallBudget(1),
            additional_facts="\n\nSENTINEL_FACT_MARKER_12345",
        )
        assert "SENTINEL_FACT_MARKER_12345" in captured_prompts[0]

    def test_write_review_artifact_creates_separate_file(self, tmp_path, monkeypatch):
        import research.dry_run.pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "DRY_RUN_PROPOSALS_DIR", tmp_path)
        _write_fake_dryrun_json(tmp_path, "DRYRUN-REV5", _VALID_PROPOSAL)
        router = _isolated_router(_FixedProvider(_REVIEW_JSON))
        result = run_reviewer_only(dryrun_id="DRYRUN-REV5", router=router, authorized=True, dry_run_budget=DryRunCallBudget(1))
        review_path = write_review_artifact(result)
        assert review_path.name == "DRYRUN-REV5-review.json"
        assert review_path != tmp_path / "DRYRUN-REV5.json"
        data = json.loads(review_path.read_text(encoding="utf-8"))
        assert data["artifact_type"] == "DRY_RUN_REVIEW_ONLY"
        assert data["actually_queued"] is False
