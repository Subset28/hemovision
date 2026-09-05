"""Phase I proposal-only autonomous loop tests (research/phase_i/loop.py).
Every LLM response here is MOCKED -- the repo-wide socket guard in
tests/conftest.py would refuse a real call anyway. No EXP row, branch, or
queue operation is ever created by this module -- verified explicitly
below."""

from __future__ import annotations

import json

import pytest

from research import operational_state
from research.db import OmniLabDB
from research.dry_run.budget import DryRunCallBudget
from research.llm.base import LLMProvider, LLMResponse, LLMUnavailableError, UsageTracker
from research.llm.router import LLMRouter
from research.phase_i import candidate_state as cs
from research.phase_i.loop import run_phase_i_cycle

VALID_PROPOSAL = {
    "selected_problem": "TRUE_DETECTOR_MISS on small/distant persons",
    "selection_rationale": "highest-value unresolved question per corrected failure taxonomy",
    "title": "Hard-positive mining for missed small-person detections",
    "family": "training_data",
    "research_question": "Does hard-positive mining on TRUE_DETECTOR_MISS crops improve person.recall?",
    "hypothesis": "Fine-tuning with an oversampled hard-positive set of TRUE_DETECTOR_MISS crops "
                  "improves person.recall by >=0.03 without violating the hazard.precision floor, "
                  "because the baseline never sees enough of this specific visual pattern.",
    "motivation": "TRUE_DETECTOR_MISS is 92/239 of Person failures, the largest single bucket.",
    "independent_variables": ["hard_positive_oversampling_ratio"],
    "dependent_variables": ["person.recall", "hazard.precision"],
    "control_condition": "baseline OIV7-only training, no oversampling",
    "baseline_comparison": "RUN-20260904-002",
    "success_criteria": {"primary_metric": "person.recall", "min_meaningful_delta": 0.03, "precision_floor": 0.757},
    "supports_hypothesis_if": "recall improves >=0.03 and hazard.precision >= 0.757",
    "rejects_hypothesis_if": "recall improves <0.03 or hazard.precision < 0.757",
    "inconclusive_if": "mixed guardrail results across seeds",
    "evidence_references": [],
    "prior_experiment_ids": ["EXP-0001", "EXP-0002", "EXP-0003", "EXP-0004", "EXP-0005"],
    "controlled_variables": {"architecture": "YOLOv8m"},
    "procedure": "mine TRUE_DETECTOR_MISS crops from baseline eval failures, oversample in training",
    "production_impact": False,
    "production_impact_description": "",
    "data_privacy_classification": "NONE",
    "external_api_required": False,
    "mac_iphone_required": False,
    "acknowledges_rejected_hypothesis_ids": [],
    "materially_new_rationale": "",
}

VALID_REVIEW_ACCEPT = {
    "novelty_assessment": "novel vs EXP-0001..0005",
    "scientific_validity_assessment": "plausible mechanism",
    "targets_verified_failure_mode": True,
    "success_criteria_deterministic": True,
    "confounding_notes": "none major",
    "dataset_can_answer_question": True,
    "sample_size_adequate": True,
    "leakage_risk_notes": "none",
    "privacy_safety_ok": True,
    "feasibility_notes": "feasible offline",
    "worth_running": True,
    "recommends_revision": False,
    "revision_notes": "",
    "summary": "worth running",
}

VALID_REVIEW_REVISE = dict(VALID_REVIEW_ACCEPT, recommends_revision=True, revision_notes="tighten isolation")
VALID_REVIEW_REJECT = dict(VALID_REVIEW_ACCEPT, worth_running=False, recommends_revision=False, summary="not worth running")


def _proposal_json(**overrides) -> str:
    d = dict(VALID_PROPOSAL)
    d.update(overrides)
    return json.dumps(d)


def _review_json(**overrides) -> str:
    d = dict(VALID_REVIEW_ACCEPT)
    d.update(overrides)
    return json.dumps(d)


class QueueProvider(LLMProvider):
    def __init__(self, items: list):
        self.items = list(items)
        self.calls: list[tuple[str, str]] = []

    def complete(self, prompt: str, role: str, model: str = "", **kwargs) -> LLMResponse:
        self.calls.append((role, model))
        if not self.items:
            raise LLMUnavailableError("QueueProvider: no more queued responses")
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResponse(text=item, tokens_used=10, cost_usd=0.0, model_used=model)


def _router(items: list):
    import tempfile
    from pathlib import Path

    tracker_path = Path(tempfile.mkstemp(suffix=".json")[1])
    tracker = UsageTracker(path=tracker_path, max_per_day=1000)
    provider = QueueProvider(items)
    return LLMRouter(provider=provider, usage_tracker=tracker), provider


@pytest.fixture(autouse=True)
def _isolated_candidates_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CANDIDATES_DIR", tmp_path / "candidates")


def _experiments_row_count() -> int:
    with OmniLabDB() as db:
        return len(db.list_experiments())


class TestAcceptPathUsesTwoCalls:
    def test_accept_finalizes_with_two_calls(self):
        router, provider = _router([_proposal_json(), _review_json()])
        result = run_phase_i_cycle(router=router, authorized=True)
        assert result.final_state == cs.FINALIZED
        assert result.calls_made == 2
        assert result.recommendation == "ACCEPT"
        assert result.revision_path is None
        assert result.final_report_path is not None

    def test_accept_never_touches_exp_db(self):
        before = _experiments_row_count()
        router, provider = _router([_proposal_json(), _review_json()])
        run_phase_i_cycle(router=router, authorized=True)
        assert _experiments_row_count() == before

    def test_candidate_id_is_not_an_exp_id(self):
        router, provider = _router([_proposal_json(), _review_json()])
        result = run_phase_i_cycle(router=router, authorized=True)
        assert result.candidate_id.startswith("CANDIDATE-")


class TestRevisePathUsesThreeCalls:
    def test_revise_finalizes_with_three_calls(self):
        router, provider = _router([_proposal_json(), _review_json(**VALID_REVIEW_REVISE), _proposal_json(title="revised title")])
        result = run_phase_i_cycle(router=router, authorized=True)
        assert result.final_state == cs.FINALIZED
        assert result.calls_made == 3
        assert result.recommendation == "REVISE"
        assert result.revised is True
        assert result.revision_path is not None

    def test_revise_never_makes_a_second_reviewer_call(self):
        """Section 15: after revision, do NOT invoke a second reviewer."""
        router, provider = _router([_proposal_json(), _review_json(**VALID_REVIEW_REVISE), _proposal_json(title="revised title")])
        run_phase_i_cycle(router=router, authorized=True)
        reviewer_calls = [c for c in provider.calls if c[0] == "reviewer"]
        assert len(reviewer_calls) == 1


class TestRejectPathTerminatesSafely:
    def test_reject_terminates_without_revision(self):
        router, provider = _router([_proposal_json(), _review_json(**VALID_REVIEW_REJECT)])
        result = run_phase_i_cycle(router=router, authorized=True)
        assert result.final_state == cs.REJECTED
        assert result.calls_made == 2
        assert result.recommendation == "REJECT"
        assert result.final_report_path is None


class TestDeterministicValidationFailureTerminatesSafely:
    def test_unknown_family_rejected_before_reviewer_call(self):
        """A structurally well-formed but semantically invalid proposal
        (unknown family -> UNKNOWN_FAMILY validator error) is rejected by
        the deterministic canonical validator, never silently repaired,
        never sent to the reviewer."""
        router, provider = _router([_proposal_json(family="not_a_real_family")])
        result = run_phase_i_cycle(router=router, authorized=True)
        assert result.final_state == cs.REJECTED
        assert result.calls_made == 1  # never reached the reviewer
        reviewer_calls = [c for c in provider.calls if c[0] == "reviewer"]
        assert reviewer_calls == []


class TestOperationalGate:
    def test_paused_blocks_before_first_call(self):
        operational_state.pause(reason="test")
        router, provider = _router([_proposal_json(), _review_json()])
        result = run_phase_i_cycle(router=router, authorized=True)
        assert result.final_state == cs.BLOCKED
        assert result.calls_made == 0
        assert provider.calls == []

    def test_stopped_blocks_before_first_call(self):
        operational_state.stop(reason="test")
        router, provider = _router([_proposal_json(), _review_json()])
        result = run_phase_i_cycle(router=router, authorized=True)
        assert result.final_state == cs.BLOCKED
        assert provider.calls == []

    def test_pause_between_researcher_and_reviewer_blocks_continuation(self):
        """Recheck immediately before each real LLM request (section 4) --
        pausing after the researcher call but before the reviewer call must
        block the reviewer call, preserving the already-written proposal
        artifact."""

        class PausingProvider(LLMProvider):
            def __init__(self, first_response):
                self.first_response = first_response
                self.calls = 0

            def complete(self, prompt, role, model="", **kwargs):
                self.calls += 1
                if self.calls == 1:
                    resp = LLMResponse(text=self.first_response, tokens_used=10, cost_usd=0.0, model_used=model)
                    operational_state.pause(reason="mid-cycle")
                    return resp
                raise AssertionError("must never reach a second call while paused")

        import tempfile
        from pathlib import Path

        tracker_path = Path(tempfile.mkstemp(suffix=".json")[1])
        provider = PausingProvider(_proposal_json())
        router = LLMRouter(provider=provider, usage_tracker=UsageTracker(path=tracker_path, max_per_day=1000))

        result = run_phase_i_cycle(router=router, authorized=True)
        assert result.final_state == cs.BLOCKED
        assert result.proposal_path is not None
        assert result.proposal_path.exists()  # artifact preserved


class TestFreeModelInvariant:
    def test_paid_model_rejected(self):
        paid_catalog = {"real/model": {
            "pricing": {"prompt": "0.001", "completion": "0.001"},
            "supported_parameters": ["response_format", "structured_outputs"],
        }}
        router, provider = _router([_proposal_json(), _review_json()])
        for role_cfg in router._roles.values():
            role_cfg["preferred_model"] = "real/model"
        result = run_phase_i_cycle(router=router, authorized=True, model_catalog=paid_catalog)
        assert result.final_state == cs.FAILED
        assert provider.calls == []


class TestBudgetExhaustion:
    def test_revision_never_exceeds_three_calls(self):
        """Even the longest legitimate path (REVISE) never exceeds the
        3-call per-cycle cap -- proven across the whole suite's call
        counting, checked explicitly here too."""
        router, provider = _router([_proposal_json(), _review_json(**VALID_REVIEW_REVISE), _proposal_json()])
        result = run_phase_i_cycle(router=router, authorized=True)
        assert result.calls_made <= 3


class TestNoSideEffects:
    def test_no_branch_created(self):
        import subprocess

        from research.config import REPO_ROOT

        before = subprocess.run(["git", "branch", "--list", "experiment/*"], cwd=REPO_ROOT, capture_output=True, text=True).stdout
        router, provider = _router([_proposal_json(), _review_json()])
        run_phase_i_cycle(router=router, authorized=True)
        after = subprocess.run(["git", "branch", "--list", "experiment/*"], cwd=REPO_ROOT, capture_output=True, text=True).stdout
        assert before == after

    def test_no_queue_call(self, monkeypatch):
        from research import orchestrator

        def _poisoned(*a, **k):
            raise AssertionError("queue_experiment_from_spec must never be called by Phase I")

        monkeypatch.setattr(orchestrator, "queue_experiment_from_spec", _poisoned)
        router, provider = _router([_proposal_json(), _review_json()])
        result = run_phase_i_cycle(router=router, authorized=True)
        assert result.final_state == cs.FINALIZED  # completed fine without ever calling it

    def test_no_approval_flags_ever_true(self):
        router, provider = _router([_proposal_json(), _review_json()])
        result = run_phase_i_cycle(router=router, authorized=True)
        p = result.proposal
        for flag in (
            "production_swift_modification_approved", "coreml_model_replacement_approved",
            "new_training_approved", "private_user_data_use_approved", "external_upload_approved",
            "mac_iphone_deployment_approved", "signing_distribution_change_approved",
        ):
            assert getattr(p, flag) is False


class TestArtifactImmutability:
    def test_proposal_artifact_never_overwritten_by_revision(self):
        router, provider = _router([_proposal_json(), _review_json(**VALID_REVIEW_REVISE), _proposal_json(title="revised")])
        result = run_phase_i_cycle(router=router, authorized=True)
        proposal_data = json.loads(result.proposal_path.read_text(encoding="utf-8"))
        assert proposal_data["proposal"]["title"] == VALID_PROPOSAL["title"]  # original, unchanged
        assert result.revision_path != result.proposal_path


class TestReturnedModelMismatch:
    def test_mismatched_model_fails_the_cycle(self):
        class MismatchProvider(LLMProvider):
            def complete(self, prompt, role, model="", **kwargs):
                return LLMResponse(text=_proposal_json(), tokens_used=10, cost_usd=0.0, model_used="some/other-model")

        import tempfile
        from pathlib import Path

        tracker_path = Path(tempfile.mkstemp(suffix=".json")[1])
        router = LLMRouter(provider=MismatchProvider(), usage_tracker=UsageTracker(path=tracker_path, max_per_day=1000))
        catalog = {
            rc["preferred_model"]: {"pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["response_format", "structured_outputs"]}
            for rc in router._roles.values()
        }
        result = run_phase_i_cycle(router=router, authorized=True, model_catalog=catalog)
        assert result.final_state == cs.FAILED


class TestMalformedStructuredOutput:
    def test_malformed_proposal_json_fails_safely(self):
        router, provider = _router(["not valid json at all"])
        result = run_phase_i_cycle(router=router, authorized=True)
        assert result.final_state == cs.FAILED


class TestNoProductionPathWrites:
    def test_ios_and_benchmark_config_untouched(self):
        import subprocess

        from research.config import REPO_ROOT

        before = subprocess.run(
            ["git", "diff", "--stat", "--", "ios/", "benchmark/config.py"], cwd=REPO_ROOT, capture_output=True, text=True,
        ).stdout
        router, provider = _router([_proposal_json(), _review_json()])
        run_phase_i_cycle(router=router, authorized=True)
        after = subprocess.run(
            ["git", "diff", "--stat", "--", "ios/", "benchmark/config.py"], cwd=REPO_ROOT, capture_output=True, text=True,
        ).stdout
        assert before == after == ""


class TestRestartIdempotency:
    def test_restart_after_researcher_does_not_repeat_researcher_call(self):
        """Pause immediately after the researcher call succeeds (before the
        reviewer call) -- forces a clean stop-after-researcher point,
        leaving the candidate resumable (BLOCKED, not terminal)."""

        class PausesAfterResearcherProvider(LLMProvider):
            def __init__(self, proposal_text):
                self.proposal_text = proposal_text
                self.roles_called = []

            def complete(self, prompt, role, model="", **kwargs):
                self.roles_called.append(role)
                resp = LLMResponse(text=self.proposal_text, tokens_used=10, cost_usd=0.0, model_used=model)
                operational_state.pause(reason="stop after researcher")
                return resp

        import tempfile
        from pathlib import Path

        tracker_path = Path(tempfile.mkstemp(suffix=".json")[1])
        provider1 = PausesAfterResearcherProvider(_proposal_json())
        router1 = LLMRouter(provider=provider1, usage_tracker=UsageTracker(path=tracker_path, max_per_day=1000))

        candidate = cs.create_candidate()
        result1 = run_phase_i_cycle(router=router1, authorized=True, resume_candidate_id=candidate.candidate_id)
        assert result1.final_state == cs.BLOCKED
        record = cs.load_candidate(candidate.candidate_id)
        assert record.state == cs.BLOCKED
        assert provider1.roles_called == ["researcher"]  # never reached reviewer

        operational_state.resume()

        class ReviewerOnlyProvider(LLMProvider):
            def __init__(self, review_text):
                self.review_text = review_text
                self.roles_called = []

            def complete(self, prompt, role, model="", **kwargs):
                self.roles_called.append(role)
                if role != "reviewer":
                    raise AssertionError(f"must not call role {role!r} again on resume")
                return LLMResponse(text=self.review_text, tokens_used=10, cost_usd=0.0, model_used=model)

        import tempfile
        from pathlib import Path

        tracker_path = Path(tempfile.mkstemp(suffix=".json")[1])
        provider2 = ReviewerOnlyProvider(_review_json())
        router2 = LLMRouter(provider=provider2, usage_tracker=UsageTracker(path=tracker_path, max_per_day=1000))
        result2 = run_phase_i_cycle(router=router2, authorized=True, resume_candidate_id=candidate.candidate_id)
        assert result2.final_state == cs.FINALIZED
        assert "researcher" not in provider2.roles_called

    def test_restart_after_reviewer_accept_does_not_repeat_reviewer_call(self):
        router1, provider1 = _router([_proposal_json(), _review_json()])
        candidate = cs.create_candidate()
        result1 = run_phase_i_cycle(router=router1, authorized=True, resume_candidate_id=candidate.candidate_id)
        assert result1.final_state == cs.FINALIZED  # ACCEPT path completes in one go

        class PoisonedProvider(LLMProvider):
            def complete(self, prompt, role, model="", **kwargs):
                raise AssertionError("must never call again -- candidate is already FINALIZED")

        import tempfile
        from pathlib import Path

        tracker_path = Path(tempfile.mkstemp(suffix=".json")[1])
        router2 = LLMRouter(provider=PoisonedProvider(), usage_tracker=UsageTracker(path=tracker_path, max_per_day=1000))
        result2 = run_phase_i_cycle(router=router2, authorized=True, resume_candidate_id=candidate.candidate_id)
        assert result2.final_state == cs.FINALIZED

    def test_restart_after_revision_does_not_repeat_revision_call(self):
        router1, provider1 = _router([_proposal_json(), _review_json(**VALID_REVIEW_REVISE), _proposal_json(title="revised")])
        candidate = cs.create_candidate()
        result1 = run_phase_i_cycle(router=router1, authorized=True, resume_candidate_id=candidate.candidate_id)
        assert result1.final_state == cs.FINALIZED

        class PoisonedProvider(LLMProvider):
            def complete(self, prompt, role, model="", **kwargs):
                raise AssertionError("must never call again -- candidate is already FINALIZED")

        import tempfile
        from pathlib import Path

        tracker_path = Path(tempfile.mkstemp(suffix=".json")[1])
        router2 = LLMRouter(provider=PoisonedProvider(), usage_tracker=UsageTracker(path=tracker_path, max_per_day=1000))
        result2 = run_phase_i_cycle(router=router2, authorized=True, resume_candidate_id=candidate.candidate_id)
        assert result2.final_state == cs.FINALIZED


class TestCandidateHistoryRedundancy:
    """Phase I second-cycle authorization, section 2: a prior candidate
    (REJECTED or otherwise) counts as prior proposal history for redundancy
    purposes even though it never became an EXP-XXXX row."""

    def test_superficial_rewrite_of_prior_candidate_is_flagged(self):
        # First candidate: proposes a temporal_pipeline intervention.
        router1, provider1 = _router([_proposal_json()])
        candidate1 = cs.create_candidate()
        result1 = run_phase_i_cycle(router=router1, authorized=True, resume_candidate_id=candidate1.candidate_id)
        assert result1.proposal_path is not None

        # Second candidate: same family, overlapping independent_variables
        # wording -- must be caught as a candidate-history conflict.
        router2, provider2 = _router([_proposal_json(
            independent_variables=["hard_positive_oversampling_ratio", "temporal_window_size"],
        )])
        result2 = run_phase_i_cycle(router=router2, authorized=True)
        assert any(cid == candidate1.candidate_id for cid, _ in result2.candidate_history_conflicts)

    def test_genuinely_different_family_not_flagged(self):
        router1, provider1 = _router([_proposal_json(family="temporal_pipeline")])
        candidate1 = cs.create_candidate()
        run_phase_i_cycle(router=router1, authorized=True, resume_candidate_id=candidate1.candidate_id)

        router2, provider2 = _router([_proposal_json(
            family="preprocessing", independent_variables=["clahe_clip_limit"],
        ), _review_json()])
        result2 = run_phase_i_cycle(router=router2, authorized=True)
        assert not any(cid == candidate1.candidate_id for cid, _ in result2.candidate_history_conflicts)

    def test_candidate_history_conflict_alone_does_not_insert_into_exp_db(self):
        before = _experiments_row_count()
        router1, provider1 = _router([_proposal_json()])
        candidate1 = cs.create_candidate()
        run_phase_i_cycle(router=router1, authorized=True, resume_candidate_id=candidate1.candidate_id)

        router2, provider2 = _router([_proposal_json(
            independent_variables=["hard_positive_oversampling_ratio", "temporal_window_size"],
        )])
        run_phase_i_cycle(router=router2, authorized=True)
        assert _experiments_row_count() == before

    def test_acknowledged_candidate_conflict_with_rationale_proceeds(self):
        router1, provider1 = _router([_proposal_json()])
        candidate1 = cs.create_candidate()
        run_phase_i_cycle(router=router1, authorized=True, resume_candidate_id=candidate1.candidate_id)

        router2, provider2 = _router([
            _proposal_json(
                independent_variables=["hard_positive_oversampling_ratio", "temporal_window_size"],
                acknowledges_rejected_hypothesis_ids=[candidate1.candidate_id],
                materially_new_rationale="Genuinely different mechanism: propagates evidence across frames "
                                         "via explicit carry-forward rather than confirmation filtering.",
            ),
            _review_json(),
        ])
        result2 = run_phase_i_cycle(router=router2, authorized=True)
        assert result2.final_state in (cs.FINALIZED, cs.REJECTED)  # proceeded past the redundancy gate either way
        assert result2.calls_made >= 2  # reached the reviewer, not rejected pre-reviewer for redundancy


class TestApprovalPendingReviewerAdmission:
    """Phase I section 8: missing approval alone must not stop reviewer
    critique -- only genuine scientific/schema ERRORs do."""

    def test_mac_iphone_required_proposal_reaches_reviewer(self):
        router, provider = _router([_proposal_json(family="temporal_pipeline", mac_iphone_required=True), _review_json()])
        result = run_phase_i_cycle(router=router, authorized=True)
        reviewer_calls = [c for c in provider.calls if c[0] == "reviewer"]
        assert len(reviewer_calls) == 1
        assert result.final_state == cs.FINALIZED

    def test_training_data_family_proposal_reaches_reviewer(self):
        router, provider = _router([_proposal_json(family="training_data"), _review_json()])
        result = run_phase_i_cycle(router=router, authorized=True)
        reviewer_calls = [c for c in provider.calls if c[0] == "reviewer"]
        assert len(reviewer_calls) == 1
        assert result.final_state == cs.FINALIZED
