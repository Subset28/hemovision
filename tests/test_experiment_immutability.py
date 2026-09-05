"""Phase-I-readiness HIGH finding #3: research/db.py::update_fields()/
set_research_verdict() must refuse to silently mutate an already-COMPLETED
experiment's scientific record, while still allowing an explicit, audited
correction via allow_amendment=True + a non-empty reason. Also verifies
EXP-0001..EXP-0005 (the real, historical Phase D records) are unaffected by
this change."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from research.config import DB_PATH
from research.db import (
    Experiment,
    ImmutableExperimentError,
    OmniLabDB,
    VerdictError,
)


@pytest.fixture()
def db(tmp_path: Path) -> OmniLabDB:
    d = OmniLabDB(tmp_path / "test_omnilab.db")
    yield d
    d.close()


def _make_experiment(experiment_id: str = "EXP-0001", **overrides) -> Experiment:
    defaults = dict(
        experiment_id=experiment_id,
        hypothesis="test hypothesis",
        motivation="test motivation",
        rationale="test rationale",
        independent_variable="conf_threshold",
        controls={"model": "yolov8m-oiv7"},
        evaluation_method="rerun benchmark.evaluate",
        success_criteria={"person.recall": {"min_delta": 0.05}},
        risks="none",
        expected_outcome="confirms sweep",
        experiment_family="threshold_postprocessing",
        baseline_run_id="RUN-20260904-002",
        validation_requirement="OFFLINE_SIMULATABLE",
    )
    defaults.update(overrides)
    return Experiment(**defaults)


def _completed(db: OmniLabDB, experiment_id: str = "EXP-0001") -> Experiment:
    db.create_experiment(_make_experiment(experiment_id))
    db.transition_status(experiment_id, "RUNNING")
    return db.transition_status(experiment_id, "COMPLETED")


class TestUpdateFieldsImmutability:
    def test_update_fields_allowed_before_completion(self, db: OmniLabDB):
        db.create_experiment(_make_experiment())
        db.transition_status("EXP-0001", "RUNNING")
        exp = db.update_fields("EXP-0001", metrics={"person.recall": 0.25}, conclusion="draft")
        assert exp.metrics == {"person.recall": 0.25}

    def test_update_fields_blocked_after_completion(self, db: OmniLabDB):
        _completed(db)
        with pytest.raises(ImmutableExperimentError):
            db.update_fields("EXP-0001", conclusion="silently rewritten")
        # value must NOT have changed
        assert db.get_experiment("EXP-0001").conclusion != "silently rewritten"

    def test_update_fields_blocked_after_completion_even_for_metrics(self, db: OmniLabDB):
        _completed(db)
        with pytest.raises(ImmutableExperimentError):
            db.update_fields("EXP-0001", metrics={"person.recall": 0.999})
        assert db.get_experiment("EXP-0001").metrics != {"person.recall": 0.999}

    def test_amendment_requires_nonempty_reason(self, db: OmniLabDB):
        _completed(db)
        with pytest.raises(ValueError):
            db.update_fields("EXP-0001", allow_amendment=True, reason="", conclusion="x")

    def test_amendment_with_reason_succeeds_and_is_audited(self, db: OmniLabDB):
        _completed(db)
        exp = db.update_fields(
            "EXP-0001", allow_amendment=True, reason="corrected a transcription error",
            conclusion="corrected conclusion text",
        )
        assert exp.conclusion == "corrected conclusion text"
        events = db.get_events("EXP-0001")
        amend_events = [e for e in events if e.from_status and e.from_status.startswith("amend:")]
        assert len(amend_events) == 1
        assert "corrected a transcription error" in amend_events[0].note

    def test_amendment_preserves_old_value_in_audit_log(self, db: OmniLabDB):
        db.create_experiment(_make_experiment())
        db.transition_status("EXP-0001", "RUNNING")
        db.update_fields("EXP-0001", conclusion="original conclusion")
        db.transition_status("EXP-0001", "COMPLETED")
        db.update_fields("EXP-0001", allow_amendment=True, reason="fix typo", conclusion="fixed conclusion")
        events = db.get_events("EXP-0001")
        amend_events = [e for e in events if e.from_status and "conclusion" in e.from_status]
        assert amend_events
        assert "original conclusion" in amend_events[0].from_status
        assert "fixed conclusion" in amend_events[0].to_status


class TestSetResearchVerdictImmutability:
    def test_first_verdict_set_at_completion_is_not_an_amendment(self, db: OmniLabDB):
        _completed(db)
        exp = db.set_research_verdict("EXP-0001", "PASS")
        assert exp.research_verdict == "PASS"

    def test_second_verdict_set_blocked_without_amendment(self, db: OmniLabDB):
        _completed(db)
        db.set_research_verdict("EXP-0001", "FAIL")
        with pytest.raises(VerdictError):
            db.set_research_verdict("EXP-0001", "PASS")
        assert db.get_experiment("EXP-0001").research_verdict == "FAIL"

    def test_second_verdict_set_blocked_is_specifically_immutable_error(self, db: OmniLabDB):
        _completed(db)
        db.set_research_verdict("EXP-0001", "FAIL")
        with pytest.raises(ImmutableExperimentError):
            db.set_research_verdict("EXP-0001", "PASS")

    def test_amendment_with_reason_corrects_verdict_and_is_audited(self, db: OmniLabDB):
        _completed(db)
        db.set_research_verdict("EXP-0001", "FAIL")
        exp = db.set_research_verdict(
            "EXP-0001", "PASS", allow_amendment=True, reason="re-scored with corrected matcher",
        )
        assert exp.research_verdict == "PASS"
        events = db.get_events("EXP-0001")
        amend_events = [e for e in events if e.from_status and e.from_status.startswith("amend:research_verdict")]
        assert len(amend_events) == 1
        assert "re-scored with corrected matcher" in amend_events[0].note
        assert "FAIL" in amend_events[0].from_status
        assert "PASS" in amend_events[0].to_status

    def test_amendment_requires_nonempty_reason(self, db: OmniLabDB):
        _completed(db)
        db.set_research_verdict("EXP-0001", "FAIL")
        with pytest.raises(ValueError):
            db.set_research_verdict("EXP-0001", "PASS", allow_amendment=True, reason="")


class TestExp0001Through0005Integrity:
    """The real, historical Phase D database (research/omnilab.db) must be
    completely unaffected by this fix -- these are read-only queries against
    the REAL db file, never mutated by this test class."""

    def test_all_five_exist_and_are_completed(self):
        if not DB_PATH.exists():
            pytest.skip("research/omnilab.db not present in this environment")
        db = OmniLabDB()
        try:
            for exp_id in ("EXP-0001", "EXP-0002", "EXP-0003", "EXP-0004", "EXP-0005"):
                exp = db.get_experiment(exp_id)
                assert exp.execution_status == "COMPLETED"
                assert exp.research_verdict in ("PASS", "FAIL", "INCONCLUSIVE", "REJECTED")
        finally:
            db.close()

    def test_verdicts_match_known_historical_values(self):
        if not DB_PATH.exists():
            pytest.skip("research/omnilab.db not present in this environment")
        expected = {
            "EXP-0001": "PASS",
            "EXP-0002": "FAIL",
            "EXP-0003": "FAIL",
            "EXP-0004": "INCONCLUSIVE",
            "EXP-0005": "INCONCLUSIVE",
        }
        db = OmniLabDB()
        try:
            for exp_id, verdict in expected.items():
                assert db.get_experiment(exp_id).research_verdict == verdict
        finally:
            db.close()

    def test_no_exp_0006_exists(self):
        if not DB_PATH.exists():
            pytest.skip("research/omnilab.db not present in this environment")
        from research.db import ExperimentNotFoundError

        db = OmniLabDB()
        try:
            with pytest.raises(ExperimentNotFoundError):
                db.get_experiment("EXP-0006")
        finally:
            db.close()

    def test_real_db_still_refuses_silent_mutation_of_exp_0001(self):
        """Confirms the NEW guard is live against the REAL database too --
        attempted, never actually committed (refused before any write)."""
        if not DB_PATH.exists():
            pytest.skip("research/omnilab.db not present in this environment")
        db = OmniLabDB()
        try:
            before = db.get_experiment("EXP-0001").conclusion
            with pytest.raises(ImmutableExperimentError):
                db.update_fields("EXP-0001", conclusion="THIS MUST NEVER BE WRITTEN")
            after = db.get_experiment("EXP-0001").conclusion
            assert before == after
        finally:
            db.close()
