"""Tests for the revision-only resume mode (Phase H final round):
research/dry_run/pipeline.py::load_preserved_review/run_revision_only/
write_revision_artifact, and research/cli.py's `omnilab dry-run-revise`.
All LLM calls mocked -- no network."""

from __future__ import annotations

import json

import pytest

from research.dry_run.budget import DryRunCallBudget
from research.dry_run.pipeline import (
    DRY_RUN_PROPOSALS_DIR,
    load_preserved_review,
    run_revision_only,
    write_revision_artifact,
)
from research.llm.base import LLMProvider, LLMResponse, LLMUnavailableError
from research.llm.router import LLMRouter

_VALID_PROPOSAL = {
    "schema_version": "1.0",
    "experiment_id": "EXP-9007",
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

_REVIEW_RECORD = {
    "dryrun_id": "DRYRUN-TEST",
    "artifact_type": "DRY_RUN_REVIEW_ONLY",
    "reviewer_critique": {
        "novelty_assessment": "novel", "scientific_validity_assessment": "sound",
        "targets_verified_failure_mode": True, "success_criteria_deterministic": True,
        "confounding_notes": "baseline provenance unknown", "dataset_can_answer_question": True,
        "sample_size_adequate": True, "leakage_risk_notes": "possible leakage",
        "privacy_safety_ok": True, "feasibility_notes": "ok",
        "worth_running": True, "recommends_revision": True, "revision_notes": "clarify isolation",
        "summary": "revise",
    },
}

_FORBIDDEN_KEYS = (
    "schema_version", "experiment_id", "baseline_run_id",
    "production_swift_modification_approved", "coreml_model_replacement_approved",
    "new_training_approved", "private_user_data_use_approved", "external_upload_approved",
    "mac_iphone_deployment_approved", "signing_distribution_change_approved",
)

_REVISED_PROPOSAL_JSON = json.dumps({
    "selected_problem": "training-data representation gap",
    "selection_rationale": "r",
    **{k: v for k, v in _VALID_PROPOSAL.items() if k not in _FORBIDDEN_KEYS},
})


def _write_fake_files(tmp_path_dir, dryrun_id: str) -> None:
    (tmp_path_dir / f"{dryrun_id}.json").write_text(
        json.dumps({"dryrun_id": dryrun_id, "proposal": _VALID_PROPOSAL}), encoding="utf-8"
    )
    (tmp_path_dir / f"{dryrun_id}-review.json").write_text(json.dumps(_REVIEW_RECORD), encoding="utf-8")


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


class TestLoadPreservedReview:
    def test_loads_real_shape_correctly(self, tmp_path, monkeypatch):
        import research.dry_run.pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "DRY_RUN_PROPOSALS_DIR", tmp_path)
        _write_fake_files(tmp_path, "DRYRUN-TEST")
        record = load_preserved_review("DRYRUN-TEST")
        assert record["reviewer_critique"]["recommends_revision"] is True

    def test_missing_file_raises(self, tmp_path, monkeypatch):
        import research.dry_run.pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "DRY_RUN_PROPOSALS_DIR", tmp_path)
        with pytest.raises(FileNotFoundError):
            load_preserved_review("DRYRUN-NOPE")

    def test_null_critique_raises_value_error(self, tmp_path, monkeypatch):
        import research.dry_run.pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "DRY_RUN_PROPOSALS_DIR", tmp_path)
        (tmp_path / "DRYRUN-NULL-review.json").write_text(
            json.dumps({"dryrun_id": "DRYRUN-NULL", "reviewer_critique": None})
        )
        with pytest.raises(ValueError):
            load_preserved_review("DRYRUN-NULL")


class TestRunRevisionOnly:
    def test_successful_revision_does_not_mutate_source_files(self, tmp_path, monkeypatch):
        import research.dry_run.pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "DRY_RUN_PROPOSALS_DIR", tmp_path)
        _write_fake_files(tmp_path, "DRYRUN-REV1")
        proposal_path = tmp_path / "DRYRUN-REV1.json"
        review_path = tmp_path / "DRYRUN-REV1-review.json"
        proposal_before = proposal_path.read_bytes()
        review_before = review_path.read_bytes()

        router = _isolated_router(_FixedProvider(_REVISED_PROPOSAL_JSON))
        result = run_revision_only(
            dryrun_id="DRYRUN-REV1", router=router, authorized=True,
            dry_run_budget=DryRunCallBudget(1),
        )
        assert proposal_path.read_bytes() == proposal_before
        assert review_path.read_bytes() == review_before
        assert result.calls_made == 1
        assert result.revised_proposal is not None
        assert result.revised_proposal.experiment_id == "EXP-9007"  # reuses original id, never EXP-0006

    def test_one_logical_step_one_call(self, tmp_path, monkeypatch):
        import research.dry_run.pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "DRY_RUN_PROPOSALS_DIR", tmp_path)
        _write_fake_files(tmp_path, "DRYRUN-REV2")
        provider = _FixedProvider(_REVISED_PROPOSAL_JSON)
        router = _isolated_router(provider)
        run_revision_only(dryrun_id="DRYRUN-REV2", router=router, authorized=True, dry_run_budget=DryRunCallBudget(1))
        assert provider.calls == 1

    def test_failed_call_preserved_with_diagnostics_no_crash(self, tmp_path, monkeypatch):
        import research.dry_run.pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "DRY_RUN_PROPOSALS_DIR", tmp_path)
        _write_fake_files(tmp_path, "DRYRUN-REV3")
        router = _isolated_router(_FixedProvider(LLMUnavailableError("boom", diagnostics={"network_attempted": True})))
        result = run_revision_only(dryrun_id="DRYRUN-REV3", router=router, authorized=True, dry_run_budget=DryRunCallBudget(1))
        assert result.revised_proposal is None
        assert "boom" in result.stopped_reason
        assert result.call_records[0].network_attempted is True

    def test_additional_facts_appended_to_prompt(self, tmp_path, monkeypatch):
        import research.dry_run.pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "DRY_RUN_PROPOSALS_DIR", tmp_path)
        _write_fake_files(tmp_path, "DRYRUN-REV4")

        captured_prompts = []

        class CapturingProvider(LLMProvider):
            def complete(self, prompt, role, model="", **kwargs):
                captured_prompts.append(prompt)
                return LLMResponse(text=_REVISED_PROPOSAL_JSON, tokens_used=10, cost_usd=0.0, model_used=model)

        router = _isolated_router(CapturingProvider())
        run_revision_only(
            dryrun_id="DRYRUN-REV4", router=router, authorized=True, dry_run_budget=DryRunCallBudget(1),
            additional_facts="SENTINEL_FACT_MARKER_67890",
        )
        assert "SENTINEL_FACT_MARKER_67890" in captured_prompts[0]
        # original proposal + reviewer critique must both be embedded so the
        # reviser actually sees what it is revising against.
        assert "clarify isolation" in captured_prompts[0]

    def test_write_revision_artifact_creates_separate_file(self, tmp_path, monkeypatch):
        import research.dry_run.pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "DRY_RUN_PROPOSALS_DIR", tmp_path)
        _write_fake_files(tmp_path, "DRYRUN-REV5")
        router = _isolated_router(_FixedProvider(_REVISED_PROPOSAL_JSON))
        result = run_revision_only(dryrun_id="DRYRUN-REV5", router=router, authorized=True, dry_run_budget=DryRunCallBudget(1))
        revision_path = write_revision_artifact(result)
        assert revision_path.name == "DRYRUN-REV5-revision.json"
        assert revision_path != tmp_path / "DRYRUN-REV5.json"
        assert revision_path != tmp_path / "DRYRUN-REV5-review.json"
        data = json.loads(revision_path.read_text(encoding="utf-8"))
        assert data["artifact_type"] == "DRY_RUN_REVISION_ONLY"
        assert data["actually_queued"] is False
