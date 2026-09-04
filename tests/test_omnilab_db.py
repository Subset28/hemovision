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
        assert fetched.status == "QUEUED"

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

    def test_invalid_status_rejected(self):
        with pytest.raises(ValueError):
            _make_experiment(status="NOT_A_STATUS")


class TestStatusTransitions:
    def test_queued_to_running_to_passed(self, db: OmniLabDB):
        db.create_experiment(_make_experiment())
        db.transition_status("EXP-0001", "RUNNING")
        exp = db.transition_status("EXP-0001", "PASSED")
        assert exp.status == "PASSED"
        assert exp.completed_at is not None

    def test_queued_cannot_jump_to_passed(self, db: OmniLabDB):
        """Core invariant: a verdict must be backed by an actual RUNNING
        execution — QUEUED -> PASSED directly is structurally disallowed."""
        db.create_experiment(_make_experiment())
        with pytest.raises(TransitionError):
            db.transition_status("EXP-0001", "PASSED")

    def test_queued_cannot_jump_to_failed(self, db: OmniLabDB):
        db.create_experiment(_make_experiment())
        with pytest.raises(TransitionError):
            db.transition_status("EXP-0001", "FAILED")

    def test_terminal_status_cannot_transition_further(self, db: OmniLabDB):
        db.create_experiment(_make_experiment())
        db.transition_status("EXP-0001", "RUNNING")
        db.transition_status("EXP-0001", "REJECTED")
        with pytest.raises(TransitionError):
            db.transition_status("EXP-0001", "RUNNING")

    def test_blocked_to_queued_allowed(self, db: OmniLabDB):
        db.create_experiment(_make_experiment())
        db.transition_status("EXP-0001", "BLOCKED")
        exp = db.transition_status("EXP-0001", "QUEUED")
        assert exp.status == "QUEUED"

    def test_transition_logs_event(self, db: OmniLabDB):
        db.create_experiment(_make_experiment())
        db.transition_status("EXP-0001", "RUNNING", note="starting benchmark")
        events = db.get_events("EXP-0001")
        # creation event + the RUNNING transition
        assert len(events) == 2
        assert events[0].to_status == "QUEUED"
        assert events[1].to_status == "RUNNING"
        assert events[1].note == "starting benchmark"

    def test_inconclusive_is_valid_terminal_state(self, db: OmniLabDB):
        db.create_experiment(_make_experiment())
        db.transition_status("EXP-0001", "RUNNING")
        exp = db.transition_status("EXP-0001", "INCONCLUSIVE")
        assert exp.status == "INCONCLUSIVE"


class TestUpdateFields:
    def test_update_metrics(self, db: OmniLabDB):
        db.create_experiment(_make_experiment())
        exp = db.update_fields("EXP-0001", metrics={"person.recall": 0.25}, conclusion="confirmed")
        assert exp.metrics == {"person.recall": 0.25}
        assert exp.conclusion == "confirmed"

    def test_update_fields_refuses_status(self, db: OmniLabDB):
        db.create_experiment(_make_experiment())
        with pytest.raises(ValueError):
            db.update_fields("EXP-0001", status="PASSED")


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
    def test_list_all_and_by_status(self, db: OmniLabDB):
        db.create_experiment(_make_experiment("EXP-0001"))
        db.create_experiment(_make_experiment("EXP-0002"))
        db.transition_status("EXP-0002", "RUNNING")
        assert len(db.list_experiments()) == 2
        assert len(db.list_experiments(status="QUEUED")) == 1
        assert len(db.list_experiments(status="RUNNING")) == 1
