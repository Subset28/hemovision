"""Regression tests for the execution_status/research_verdict split
(research/db.py) and its downstream effects: directory lifecycle
(research/experiment_lifecycle.py) and the EXP-0001..0004 migration
(research/migrations/001_split_status_verdict.py).

Distinct from tests/test_omnilab_db.py's own coverage of the DB API itself
(transitions, verdict immutability, invalid-value rejection) — this file
focuses on (a) the two axes staying genuinely independent under real
lifecycle operations, and (b) the already-migrated historical records
(EXP-0001..0004, on the real research/omnilab.db + experiments/ tree) still
loading correctly with the documented execution_status/research_verdict
pairs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research.db import ALLOWED_TRANSITIONS, Experiment, OmniLabDB, TransitionError


# ---------------------------------------------------------------------------
# The two axes are genuinely independent (not conflated in either direction)
# ---------------------------------------------------------------------------


class TestAxesAreIndependent:
    def test_completed_pass_completed_fail_completed_inconclusive_all_valid(self, tmp_path: Path):
        """COMPLETED+PASS, COMPLETED+FAIL, COMPLETED+INCONCLUSIVE are all
        legal combinations on the execution_status=COMPLETED axis."""
        db = OmniLabDB(tmp_path / "db.sqlite")
        try:
            for i, verdict in enumerate(("PASS", "FAIL", "INCONCLUSIVE"), start=1):
                exp_id = f"EXP-{i:04d}"
                db.create_experiment(_experiment(exp_id))
                db.transition_status(exp_id, "RUNNING")
                db.transition_status(exp_id, "COMPLETED")
                exp = db.set_research_verdict(exp_id, verdict)
                assert exp.execution_status == "COMPLETED"
                assert exp.research_verdict == verdict
        finally:
            db.close()

    def test_inconclusive_verdict_does_not_imply_execution_failure(self, tmp_path: Path):
        """An INCONCLUSIVE research_verdict is a normal, successful
        execution outcome (EXP-0004's real result) — it must never be
        conflated with an ABORTED execution_status (crash/incomplete run)
        or a REJECTED research_verdict (structurally invalid result)."""
        db = OmniLabDB(tmp_path / "db.sqlite")
        try:
            db.create_experiment(_experiment("EXP-0001"))
            db.transition_status("EXP-0001", "RUNNING")
            db.transition_status("EXP-0001", "COMPLETED")
            exp = db.set_research_verdict("EXP-0001", "INCONCLUSIVE")
            assert exp.execution_status == "COMPLETED"
            assert exp.execution_status != "ABORTED"
            assert exp.research_verdict == "INCONCLUSIVE"
            assert exp.research_verdict != "REJECTED"
        finally:
            db.close()

    def test_execution_status_transitions_still_guarded_by_allowed_transitions(self, tmp_path: Path):
        db = OmniLabDB(tmp_path / "db.sqlite")
        try:
            db.create_experiment(_experiment("EXP-0001"))
            # QUEUED -> COMPLETED is not in ALLOWED_TRANSITIONS["QUEUED"]
            assert "COMPLETED" not in ALLOWED_TRANSITIONS["QUEUED"]
            with pytest.raises(TransitionError):
                db.transition_status("EXP-0001", "COMPLETED")
            # RUNNING -> ABORTED is allowed
            db.transition_status("EXP-0001", "RUNNING")
            assert "ABORTED" in ALLOWED_TRANSITIONS["RUNNING"]
            exp = db.transition_status("EXP-0001", "ABORTED")
            assert exp.execution_status == "ABORTED"
        finally:
            db.close()


def _experiment(experiment_id: str) -> Experiment:
    return Experiment(
        experiment_id=experiment_id,
        hypothesis="h",
        motivation="m",
        rationale="r",
        independent_variable="iv",
        experiment_family="threshold_postprocessing",
        baseline_run_id="RUN-20260904-002",
        validation_requirement="OFFLINE_SIMULATABLE",
    )


# ---------------------------------------------------------------------------
# Directory lifecycle must never clobber an already-recorded research_verdict
# ---------------------------------------------------------------------------


class TestDirectoryLifecycleDoesNotTouchVerdict:
    def test_move_to_status_does_not_reset_or_read_research_verdict(self, tmp_path: Path, monkeypatch):
        """research/experiment_lifecycle.py::move_to_status is a pure
        filesystem operation keyed on execution_status — it must never
        silently reset or clear an experiment's research_verdict field
        (which lives only in the DB / results.json, not implied by the
        directory move at all)."""
        import research.experiment_lifecycle as lifecycle

        fake_dirs = {
            "QUEUED": tmp_path / "queued",
            "RUNNING": tmp_path / "running",
            "COMPLETED": tmp_path / "completed",
            "BLOCKED": tmp_path / "blocked",
            "ABORTED": tmp_path / "aborted",
        }
        monkeypatch.setattr(lifecycle, "EXPERIMENT_STATUS_DIRS", fake_dirs)

        db = OmniLabDB(tmp_path / "db.sqlite")
        try:
            exp_id = "EXP-0001"
            db.create_experiment(_experiment(exp_id))
            db.transition_status(exp_id, "RUNNING")
            lifecycle.move_to_status(exp_id, "RUNNING")
            (fake_dirs["RUNNING"] / exp_id).mkdir(parents=True, exist_ok=True)

            db.transition_status(exp_id, "COMPLETED")
            db.set_research_verdict(exp_id, "FAIL", note="resolution intervention did not work")

            before = db.get_experiment(exp_id).research_verdict
            assert before == "FAIL"

            # Move the directory (COMPLETED -> COMPLETED is idempotent, but
            # exercise a real move: RUNNING dir still exists from above).
            new_dir = lifecycle.move_to_status(exp_id, "COMPLETED")
            assert new_dir == fake_dirs["COMPLETED"] / exp_id
            assert new_dir.exists()
            assert not (fake_dirs["RUNNING"] / exp_id).exists()

            after = db.get_experiment(exp_id).research_verdict
            assert after == before == "FAIL"
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Historical EXP-0001..0004 records remain readable/loadable after the
# migration, with the documented execution_status/research_verdict pairs.
# ---------------------------------------------------------------------------

EXPECTED_FINAL_STATES = {
    "EXP-0001": ("COMPLETED", "PASS"),
    "EXP-0002": ("COMPLETED", "FAIL"),
    "EXP-0003": ("COMPLETED", "FAIL"),
    "EXP-0004": ("COMPLETED", "INCONCLUSIVE"),
}


class TestMigratedHistoricalRecords:
    def test_exp_0001_through_0004_load_with_expected_execution_status_and_verdict(self):
        with OmniLabDB() as db:
            for experiment_id, (expected_execution_status, expected_verdict) in EXPECTED_FINAL_STATES.items():
                exp = db.get_experiment(experiment_id)
                assert exp.execution_status == expected_execution_status, experiment_id
                assert exp.research_verdict == expected_verdict, experiment_id

    def test_exp_0001_pass_is_confirmatory_not_production_viable(self):
        """EXP-0001's PASS verdict must not be misread as "conf=0.05 is a
        good production setting" — see research/README.md and
        research/runners.py::run_exp_0001's docstring. This test asserts
        the raw evaluation-policy verdict recorded alongside it was FAILED
        (a guardrail violation), which is exactly what a confirmed negative
        hypothesis looks like — not a clean win."""
        with OmniLabDB() as db:
            exp = db.get_experiment("EXP-0001")
        assert exp.research_verdict == "PASS"
        assert exp.metrics is not None
        assert exp.metrics.get("raw_evaluation_policy_verdict") == "FAILED"

    def test_exp_0005_blocked_pending_not_advanced(self):
        """EXP-0005 must remain BLOCKED/PENDING — this migration (and this
        cleanup task) must never advance or unblock it."""
        with OmniLabDB() as db:
            exp = db.get_experiment("EXP-0005")
        assert exp.execution_status == "BLOCKED"
        assert exp.research_verdict == "PENDING"

    def test_experiments_directory_layout_is_execution_status_keyed(self):
        from research.config import EXPERIMENTS_DIR

        for experiment_id in ("EXP-0001", "EXP-0002", "EXP-0003", "EXP-0004"):
            assert (EXPERIMENTS_DIR / "completed" / experiment_id).exists(), experiment_id
        assert (EXPERIMENTS_DIR / "blocked" / "EXP-0005").exists()
        assert not (EXPERIMENTS_DIR / "failed").exists()
        assert not (EXPERIMENTS_DIR / "rejected").exists()

    def test_every_experiment_results_json_carries_explicit_verdict_field(self):
        """Automation must read the verdict from metadata, never infer it
        from a directory name — enforce that every COMPLETED experiment's
        results.json actually carries an unambiguous research_verdict."""
        import json

        from research.config import EXPERIMENTS_DIR

        for experiment_id in ("EXP-0001", "EXP-0002", "EXP-0003", "EXP-0004"):
            results_path = EXPERIMENTS_DIR / "completed" / experiment_id / "results.json"
            assert results_path.exists(), experiment_id
            data = json.loads(results_path.read_text(encoding="utf-8"))
            # Pre-migration results.json used 'final_experiment_status'; the
            # orchestrator now writes 'research_verdict' going forward (see
            # research/orchestrator.py::run_experiment). Either counts as an
            # explicit, unambiguous verdict field — accept both so this test
            # covers pre- and post-schema-split results.json alike.
            assert "research_verdict" in data or "final_experiment_status" in data, experiment_id
