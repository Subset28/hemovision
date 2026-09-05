"""Tests for research/db.py — the experiment database wrapper."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from research.db import (
    Experiment,
    ExperimentNotFoundError,
    OmniLabDB,
    TransitionError,
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


class TestExperimentCreation:
    def test_create_and_get(self, db: OmniLabDB):
        exp = _make_experiment()
        db.create_experiment(exp)
        fetched = db.get_experiment("EXP-0001")
        assert fetched.experiment_id == "EXP-0001"
        assert fetched.hypothesis == "test hypothesis"
        assert fetched.controls == {"model": "yolov8m-oiv7"}
        assert fetched.execution_status == "QUEUED"
        assert fetched.research_verdict == "PENDING"

    def test_get_missing_raises(self, db: OmniLabDB):
        with pytest.raises(ExperimentNotFoundError):
            db.get_experiment("EXP-9999")

    def test_next_experiment_id_increments(self, db: OmniLabDB):
        assert db.next_experiment_id() == "EXP-0001"
        db.create_experiment(_make_experiment("EXP-0001"))
        assert db.next_experiment_id() == "EXP-0002"
        db.create_experiment(_make_experiment("EXP-0002"))
        assert db.next_experiment_id() == "EXP-0003"

    def test_experiment_id_uniqueness_enforced(self, db: OmniLabDB):
        db.create_experiment(_make_experiment("EXP-0001"))
        with pytest.raises(sqlite3.IntegrityError):
            db.create_experiment(_make_experiment("EXP-0001", hypothesis="different"))

    def test_invalid_family_rejected(self):
        with pytest.raises(ValueError):
            _make_experiment(experiment_family="not_a_real_family")

    def test_invalid_execution_status_rejected(self):
        with pytest.raises(ValueError):
            _make_experiment(execution_status="NOT_A_STATUS")

    def test_invalid_research_verdict_rejected(self):
        with pytest.raises(ValueError):
            _make_experiment(execution_status="COMPLETED", research_verdict="NOT_A_VERDICT")

    def test_non_pending_verdict_requires_completed_execution_status(self):
        """A research_verdict other than PENDING can never coexist with an
        execution_status other than COMPLETED — this is checked at
        construction time, not just by set_research_verdict()."""
        with pytest.raises(ValueError):
            _make_experiment(execution_status="RUNNING", research_verdict="PASS")


class TestExecutionStatusTransitions:
    def test_queued_to_running_to_completed(self, db: OmniLabDB):
        db.create_experiment(_make_experiment())
        db.transition_status("EXP-0001", "RUNNING")
        exp = db.transition_status("EXP-0001", "COMPLETED")
        assert exp.execution_status == "COMPLETED"
        assert exp.completed_at is not None

    def test_queued_cannot_jump_to_completed(self, db: OmniLabDB):
        """Core invariant: a verdict must be backed by an actual RUNNING
        execution — QUEUED -> COMPLETED directly is structurally disallowed."""
        db.create_experiment(_make_experiment())
        with pytest.raises(TransitionError):
            db.transition_status("EXP-0001", "COMPLETED")

    def test_queued_cannot_jump_to_aborted(self, db: OmniLabDB):
        db.create_experiment(_make_experiment())
        with pytest.raises(TransitionError):
            db.transition_status("EXP-0001", "ABORTED")

    def test_terminal_execution_status_cannot_transition_further(self, db: OmniLabDB):
        db.create_experiment(_make_experiment())
        db.transition_status("EXP-0001", "RUNNING")
        db.transition_status("EXP-0001", "ABORTED")
        with pytest.raises(TransitionError):
            db.transition_status("EXP-0001", "RUNNING")

    def test_completed_cannot_transition_further(self, db: OmniLabDB):
        db.create_experiment(_make_experiment())
        db.transition_status("EXP-0001", "RUNNING")
        db.transition_status("EXP-0001", "COMPLETED")
        with pytest.raises(TransitionError):
            db.transition_status("EXP-0001", "RUNNING")

    def test_blocked_to_queued_allowed(self, db: OmniLabDB):
        db.create_experiment(_make_experiment())
        db.transition_status("EXP-0001", "BLOCKED")
        exp = db.transition_status("EXP-0001", "QUEUED")
        assert exp.execution_status == "QUEUED"

    def test_transition_logs_event(self, db: OmniLabDB):
        db.create_experiment(_make_experiment())
        db.transition_status("EXP-0001", "RUNNING", note="starting benchmark")
        events = db.get_events("EXP-0001")
        # creation event + the RUNNING transition
        assert len(events) == 2
        assert events[0].to_status == "QUEUED"
        assert events[1].to_status == "RUNNING"
        assert events[1].note == "starting benchmark"

    def test_running_can_go_to_aborted(self, db: OmniLabDB):
        """A runner crash / resource limit / incomplete result maps to
        ABORTED — distinct from a REJECTED research_verdict, which requires
        execution_status=COMPLETED (see TestResearchVerdicts)."""
        db.create_experiment(_make_experiment())
        db.transition_status("EXP-0001", "RUNNING")
        exp = db.transition_status("EXP-0001", "ABORTED")
        assert exp.execution_status == "ABORTED"
        assert exp.research_verdict == "PENDING"


class TestResearchVerdicts:
    def _completed(self, db: OmniLabDB, experiment_id: str = "EXP-0001") -> Experiment:
        db.create_experiment(_make_experiment(experiment_id))
        db.transition_status(experiment_id, "RUNNING")
        return db.transition_status(experiment_id, "COMPLETED")

    def test_completed_plus_pass_is_valid(self, db: OmniLabDB):
        self._completed(db)
        exp = db.set_research_verdict("EXP-0001", "PASS")
        assert exp.execution_status == "COMPLETED"
        assert exp.research_verdict == "PASS"

    def test_completed_plus_fail_is_valid(self, db: OmniLabDB):
        self._completed(db)
        exp = db.set_research_verdict("EXP-0001", "FAIL")
        assert exp.execution_status == "COMPLETED"
        assert exp.research_verdict == "FAIL"

    def test_completed_plus_inconclusive_is_valid(self, db: OmniLabDB):
        self._completed(db)
        exp = db.set_research_verdict("EXP-0001", "INCONCLUSIVE")
        assert exp.execution_status == "COMPLETED"
        assert exp.research_verdict == "INCONCLUSIVE"

    def test_completed_plus_rejected_is_valid(self, db: OmniLabDB):
        self._completed(db)
        exp = db.set_research_verdict("EXP-0001", "REJECTED")
        assert exp.execution_status == "COMPLETED"
        assert exp.research_verdict == "REJECTED"

    def test_inconclusive_is_not_conflated_with_aborted_or_rejected(self, db: OmniLabDB):
        """execution_status and research_verdict are genuinely different
        axes: an INCONCLUSIVE research_verdict is a normal, successful
        execution outcome, not an execution failure. ABORTED and REJECTED
        (structural) live on different axes/values entirely."""
        self._completed(db)
        exp = db.set_research_verdict("EXP-0001", "INCONCLUSIVE")
        assert exp.execution_status == "COMPLETED"  # not ABORTED
        assert exp.research_verdict == "INCONCLUSIVE"
        assert exp.research_verdict != "ABORTED"  # not even a legal verdict value
        assert exp.execution_status != "REJECTED"  # not even a legal execution_status value

    def test_cannot_set_verdict_before_completed(self, db: OmniLabDB):
        db.create_experiment(_make_experiment())
        db.transition_status("EXP-0001", "RUNNING")
        with pytest.raises(VerdictError):
            db.set_research_verdict("EXP-0001", "PASS")

    def test_cannot_set_verdict_while_queued(self, db: OmniLabDB):
        db.create_experiment(_make_experiment())
        with pytest.raises(VerdictError):
            db.set_research_verdict("EXP-0001", "PASS")

    def test_verdict_is_immutable_once_set(self, db: OmniLabDB):
        self._completed(db)
        db.set_research_verdict("EXP-0001", "FAIL")
        with pytest.raises(VerdictError):
            db.set_research_verdict("EXP-0001", "PASS")
        # the original verdict must survive the rejected overwrite attempt
        assert db.get_experiment("EXP-0001").research_verdict == "FAIL"

    def test_invalid_verdict_value_rejected(self, db: OmniLabDB):
        self._completed(db)
        with pytest.raises(ValueError):
            db.set_research_verdict("EXP-0001", "NOT_A_VERDICT")


class TestUpdateFields:
    def test_update_metrics(self, db: OmniLabDB):
        db.create_experiment(_make_experiment())
        exp = db.update_fields("EXP-0001", metrics={"person.recall": 0.25}, conclusion="confirmed")
        assert exp.metrics == {"person.recall": 0.25}
        assert exp.conclusion == "confirmed"

    def test_update_fields_refuses_execution_status(self, db: OmniLabDB):
        db.create_experiment(_make_experiment())
        with pytest.raises(ValueError):
            db.update_fields("EXP-0001", execution_status="COMPLETED")

    def test_update_fields_refuses_legacy_status_kwarg(self, db: OmniLabDB):
        db.create_experiment(_make_experiment())
        with pytest.raises(ValueError):
            db.update_fields("EXP-0001", status="COMPLETED")

    def test_update_fields_refuses_research_verdict(self, db: OmniLabDB):
        db.create_experiment(_make_experiment())
        with pytest.raises(ValueError):
            db.update_fields("EXP-0001", research_verdict="PASS")


class TestBaselineRunResolution:
    def test_resolves_real_baseline_run(self, db: OmniLabDB):
        db.create_experiment(_make_experiment(baseline_run_id="RUN-20260904-002"))
        run_dir = db.resolve_baseline_run_dir("EXP-0001")
        assert run_dir.exists()
        assert (run_dir / "run_metadata.json").exists()

    def test_unresolvable_baseline_raises(self, db: OmniLabDB):
        db.create_experiment(_make_experiment(baseline_run_id="RUN-DOES-NOT-EXIST"))
        with pytest.raises(FileNotFoundError):
            db.resolve_baseline_run_dir("EXP-0001")


class TestListExperiments:
    def test_list_all_and_by_execution_status(self, db: OmniLabDB):
        db.create_experiment(_make_experiment("EXP-0001"))
        db.create_experiment(_make_experiment("EXP-0002"))
        db.transition_status("EXP-0002", "RUNNING")
        assert len(db.list_experiments()) == 2
        assert len(db.list_experiments(execution_status="QUEUED")) == 1
        assert len(db.list_experiments(execution_status="RUNNING")) == 1

    def test_list_by_research_verdict(self, db: OmniLabDB):
        db.create_experiment(_make_experiment("EXP-0001"))
        db.create_experiment(_make_experiment("EXP-0002"))
        db.transition_status("EXP-0001", "RUNNING")
        db.transition_status("EXP-0001", "COMPLETED")
        db.set_research_verdict("EXP-0001", "PASS")
        assert len(db.list_experiments(research_verdict="PENDING")) == 1
        assert len(db.list_experiments(research_verdict="PASS")) == 1
