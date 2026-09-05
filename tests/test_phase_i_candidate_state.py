"""Phase I candidate-run state machine tests (research/phase_i/candidate_state.py).
No LLM call anywhere in this file."""

from __future__ import annotations

import pytest

from research.phase_i import candidate_state as cs


@pytest.fixture(autouse=True)
def _isolated_candidates_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CANDIDATES_DIR", tmp_path / "candidates")


class TestCandidateIdAllocation:
    def test_first_id_is_candidate_0001(self):
        record = cs.create_candidate()
        assert record.candidate_id == "CANDIDATE-0001"

    def test_ids_increment(self):
        cs.create_candidate()
        cs.create_candidate()
        r3 = cs.create_candidate()
        assert r3.candidate_id == "CANDIDATE-0003"

    def test_never_uses_exp_or_dryrun_prefix(self):
        record = cs.create_candidate()
        assert not record.candidate_id.startswith("EXP-")
        assert not record.candidate_id.startswith("DRYRUN-")

    def test_created_state_is_persisted(self):
        record = cs.create_candidate()
        reloaded = cs.load_candidate(record.candidate_id)
        assert reloaded.state == cs.CREATED


class TestStateTransitions:
    def test_valid_transition_sequence(self):
        record = cs.create_candidate()
        record.proposal_path = "x"
        cs.transition(record, cs.RESEARCHER_COMPLETED)
        cs.transition(record, cs.VALIDATED)
        record.review_path = "y"
        cs.transition(record, cs.REVIEW_COMPLETED)
        cs.transition(record, cs.FINALIZED)
        assert record.state == cs.FINALIZED

    def test_invalid_transition_rejected(self):
        record = cs.create_candidate()
        with pytest.raises(cs.CandidateStateError):
            cs.transition(record, cs.FINALIZED)  # cannot skip straight to FINALIZED

    def test_terminal_state_accepts_no_further_transition(self):
        record = cs.create_candidate()
        cs.transition(record, cs.FAILED)
        with pytest.raises(cs.CandidateStateError):
            cs.transition(record, cs.RESEARCHER_COMPLETED)

    def test_blocked_is_not_terminal_and_can_resume_onward(self):
        """BLOCKED means the operational gate refused an attempt -- a
        TEMPORARY condition, not a scientific/technical verdict. Unlike
        FINALIZED/REJECTED/FAILED, a transition OUT of BLOCKED is legal."""
        record = cs.create_candidate()
        cs.transition(record, cs.BLOCKED, reason="paused")
        cs.transition(record, cs.RESEARCHER_COMPLETED)  # must not raise
        assert record.state == cs.RESEARCHER_COMPLETED

    def test_unknown_state_rejected(self):
        record = cs.create_candidate()
        with pytest.raises(cs.CandidateStateError):
            cs.transition(record, "NOT_A_REAL_STATE")

    def test_transition_persists_immediately(self):
        record = cs.create_candidate()
        cs.transition(record, cs.BLOCKED, reason="test")
        reloaded = cs.load_candidate(record.candidate_id)
        assert reloaded.state == cs.BLOCKED
        assert reloaded.stopped_reason == "test"

    def test_history_records_every_transition(self):
        record = cs.create_candidate()
        cs.transition(record, cs.RESEARCHER_COMPLETED)
        cs.transition(record, cs.BLOCKED, reason="stopped")
        assert len(record.history) == 2
        assert record.history[0] == {
            "from": cs.CREATED, "to": cs.RESEARCHER_COMPLETED,
            "at": record.history[0]["at"], "reason": "",
        }
        assert record.history[1]["to"] == cs.BLOCKED
        assert record.history[1]["reason"] == "stopped"

    def test_review_completed_forks_three_ways(self):
        for target in (cs.FINALIZED, cs.REJECTED, cs.REVISION_COMPLETED):
            record = cs.create_candidate()
            record.proposal_path = "x"
            cs.transition(record, cs.RESEARCHER_COMPLETED)
            cs.transition(record, cs.VALIDATED)
            record.review_path = "y"
            cs.transition(record, cs.REVIEW_COMPLETED)
            cs.transition(record, target)
            assert record.state == target


class TestFailClosedOnAmbiguousState:
    def test_missing_candidate_raises(self):
        with pytest.raises(cs.CandidateStateError):
            cs.load_candidate("CANDIDATE-9999")

    def test_resume_researcher_completed_without_proposal_file_fails_closed(self):
        record = cs.create_candidate()
        record.proposal_path = None  # never actually written
        cs.transition(record, cs.RESEARCHER_COMPLETED)
        with pytest.raises(cs.CandidateStateError):
            cs.resolve_resume_point(record.candidate_id)

    def test_resume_researcher_completed_with_nonexistent_path_fails_closed(self):
        record = cs.create_candidate()
        record.proposal_path = "/no/such/file.json"
        cs.transition(record, cs.RESEARCHER_COMPLETED)
        with pytest.raises(cs.CandidateStateError):
            cs.resolve_resume_point(record.candidate_id)

    def test_corrupt_state_file_fails_closed(self, tmp_path):
        record = cs.create_candidate()
        state_path = cs._state_path(record.candidate_id)
        state_path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(cs.CandidateStateError):
            cs.load_candidate(record.candidate_id)


class TestResumePointResolution:
    def test_created_resumes_at_researcher(self):
        record = cs.create_candidate()
        _, stage = cs.resolve_resume_point(record.candidate_id)
        assert stage == "researcher"

    def test_researcher_completed_resumes_at_validate(self, tmp_path):
        record = cs.create_candidate()
        proposal_file = tmp_path / "proposal.json"
        proposal_file.write_text("{}", encoding="utf-8")
        record.proposal_path = str(proposal_file)
        cs.transition(record, cs.RESEARCHER_COMPLETED)
        _, stage = cs.resolve_resume_point(record.candidate_id)
        assert stage == "validate"

    def test_validated_resumes_at_reviewer(self, tmp_path):
        record = cs.create_candidate()
        proposal_file = tmp_path / "proposal.json"
        proposal_file.write_text("{}", encoding="utf-8")
        record.proposal_path = str(proposal_file)
        cs.transition(record, cs.RESEARCHER_COMPLETED)
        cs.transition(record, cs.VALIDATED)
        _, stage = cs.resolve_resume_point(record.candidate_id)
        assert stage == "reviewer"

    def test_review_completed_resumes_at_revision(self, tmp_path):
        record = cs.create_candidate()
        proposal_file = tmp_path / "proposal.json"
        proposal_file.write_text("{}", encoding="utf-8")
        review_file = tmp_path / "review.json"
        review_file.write_text("{}", encoding="utf-8")
        record.proposal_path = str(proposal_file)
        cs.transition(record, cs.RESEARCHER_COMPLETED)
        cs.transition(record, cs.VALIDATED)
        record.review_path = str(review_file)
        cs.transition(record, cs.REVIEW_COMPLETED)
        _, stage = cs.resolve_resume_point(record.candidate_id)
        assert stage == "revision"

    def test_terminal_state_resumes_at_done(self):
        record = cs.create_candidate()
        cs.transition(record, cs.FAILED)
        _, stage = cs.resolve_resume_point(record.candidate_id)
        assert stage == "done"

    def test_blocked_from_created_resumes_at_researcher(self):
        """BLOCKED before any artifact exists must resume exactly where a
        fresh CREATED candidate would -- nothing was lost."""
        record = cs.create_candidate()
        cs.transition(record, cs.BLOCKED, reason="paused before first call")
        _, stage = cs.resolve_resume_point(record.candidate_id)
        assert stage == "researcher"

    def test_blocked_after_researcher_resumes_at_validate(self, tmp_path):
        record = cs.create_candidate()
        proposal_file = tmp_path / "proposal.json"
        proposal_file.write_text("{}", encoding="utf-8")
        record.proposal_path = str(proposal_file)
        cs.transition(record, cs.BLOCKED, reason="paused after researcher")
        _, stage = cs.resolve_resume_point(record.candidate_id)
        assert stage == "validate"

    def test_blocked_after_review_resumes_at_revision(self, tmp_path):
        record = cs.create_candidate()
        proposal_file = tmp_path / "proposal.json"
        proposal_file.write_text("{}", encoding="utf-8")
        review_file = tmp_path / "review.json"
        review_file.write_text("{}", encoding="utf-8")
        record.proposal_path = str(proposal_file)
        record.review_path = str(review_file)
        cs.transition(record, cs.BLOCKED, reason="paused after reviewer")
        _, stage = cs.resolve_resume_point(record.candidate_id)
        assert stage == "revision"
