"""Regression tests for research/migrations/002_add_family_h.py -- the
one-off migration that widens the `experiments` table's `experiment_family`
CHECK constraint to accept the 8th family, 'application_decision_logic'
(added to research/experiment_registry.py in Phase F but not yet accepted
by research/db.py's CHECK constraint until this migration).

Builds a throwaway SQLite file shaped like a pre-migration ("old",
7-family) database, points the migration module at it (never touches the
real research/omnilab.db), and verifies: existing rows survive unchanged,
the new family value becomes insertable afterward, and re-running the
migration against an already-migrated DB is a safe no-op (idempotent).
"""

from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

import pytest

MIGRATION_MODULE = "research.migrations.002_add_family_h"

def _old_schema_sql() -> str:
    """The real, current _SCHEMA from research/db.py, with the CHECK
    constraint narrowed back to the original 7 families -- i.e. exactly
    what research/omnilab.db looked like before this migration, field for
    field, so the migration's generic column-preserving copy logic (which
    inserts by real column name, not a hand-picked subset) is exercised
    faithfully rather than against an oversimplified fixture."""
    from research.db import _SCHEMA

    old = _SCHEMA.replace(
        "'threshold_postprocessing','class_confusion',\n"
        "                                 'small_object','preprocessing','model_variant',\n"
        "                                 'training_data','temporal_pipeline',\n"
        "                                 'application_decision_logic')),",
        "'threshold_postprocessing','class_confusion',\n"
        "                                 'small_object','preprocessing','model_variant',\n"
        "                                 'training_data','temporal_pipeline')),",
    )
    assert "application_decision_logic" not in old, "fixture failed to narrow the CHECK constraint back down"
    return old


def _make_old_style_db(path: Path) -> None:
    import dataclasses

    from research.db import Experiment

    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_old_schema_sql())

        exp = Experiment(
            experiment_id="EXP-TEST1",
            hypothesis="does X help?",
            motivation="test fixture",
            rationale="test fixture",
            independent_variable="x",
            baseline_run_id="RUN-TEST",
            experiment_family="small_object",
            execution_status="COMPLETED",
            research_verdict="FAIL",
            validation_requirement="OFFLINE_SIMULATABLE",
        )
        row = dataclasses.asdict(exp)
        for json_field in ("controls", "success_criteria", "configuration", "metrics", "estimated_cost"):
            row[json_field] = row[json_field] if row[json_field] is None else str(row[json_field])
        import json as _json

        for json_field in ("controls", "success_criteria", "configuration", "estimated_cost"):
            row[json_field] = _json.dumps(exp.__dict__[json_field])
        row["metrics"] = _json.dumps(exp.metrics) if exp.metrics is not None else None

        cols = ", ".join(row.keys())
        placeholders = ", ".join(f":{k}" for k in row.keys())
        conn.execute(f"INSERT INTO experiments ({cols}) VALUES ({placeholders})", row)
        conn.execute(
            "INSERT INTO experiment_events (experiment_id, from_status, to_status, note, timestamp) "
            "VALUES (?,?,?,?,?)",
            ("EXP-TEST1", "RUNNING", "COMPLETED", "test fixture event", "2026-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def migration_module(tmp_path, monkeypatch):
    """Import the migration module fresh and point its DB_PATH at a
    throwaway file -- never touches the real research/omnilab.db."""
    mod = importlib.import_module(MIGRATION_MODULE)
    fake_db_path = tmp_path / "omnilab_test.db"
    monkeypatch.setattr(mod, "DB_PATH", fake_db_path, raising=True)
    # research.db.OmniLabDB is imported lazily inside main(); its own
    # module-level DB_PATH default isn't used since the migration always
    # passes db_path explicitly -- no further patching needed there.
    return mod, fake_db_path


class TestFamilyHMigration:
    def test_missing_db_is_a_no_op(self, migration_module):
        mod, db_path = migration_module
        assert not db_path.exists()
        mod.main()  # must not raise, must not create anything
        assert not db_path.exists()

    def test_migrates_existing_rows_without_changing_values(self, migration_module):
        mod, db_path = migration_module
        _make_old_style_db(db_path)

        mod.main()

        from research.db import OmniLabDB

        with OmniLabDB(db_path) as db:
            exp = db.get_experiment("EXP-TEST1")
            assert exp is not None
            assert exp.experiment_family == "small_object"  # unchanged
            assert exp.execution_status == "COMPLETED"       # unchanged
            assert exp.research_verdict == "FAIL"             # unchanged

    def test_new_family_value_insertable_after_migration(self, migration_module):
        mod, db_path = migration_module
        _make_old_style_db(db_path)
        mod.main()

        from research.db import Experiment, OmniLabDB

        with OmniLabDB(db_path) as db:
            db.create_experiment(
                Experiment(
                    experiment_id="EXP-TEST2",
                    hypothesis="does application-level decision logic help?",
                    motivation="test",
                    rationale="test",
                    independent_variable="tts cooldown",
                    baseline_run_id="RUN-TEST",
                    experiment_family="application_decision_logic",
                    execution_status="QUEUED",
                )
            )
            exp = db.get_experiment("EXP-TEST2")
            assert exp.experiment_family == "application_decision_logic"

    def test_rejecting_invalid_family_still_works_after_migration(self, migration_module):
        """The widened CHECK constraint must still reject a bogus family --
        this migration only ADDS one legal value, it must not accidentally
        disable the constraint entirely."""
        mod, db_path = migration_module
        _make_old_style_db(db_path)
        mod.main()

        from research.db import Experiment, OmniLabDB

        with OmniLabDB(db_path) as db:
            with pytest.raises(Exception):  # ValueError (dataclass __post_init__) or sqlite3.IntegrityError
                db.create_experiment(
                    Experiment(
                        experiment_id="EXP-TEST3",
                        hypothesis="x",
                        motivation="x",
                        rationale="x",
                        independent_variable="x",
                        baseline_run_id="RUN-TEST",
                        experiment_family="not_a_real_family",
                        execution_status="QUEUED",
                    )
                )

    def test_idempotent_second_run_is_a_safe_no_op(self, migration_module, capsys):
        mod, db_path = migration_module
        _make_old_style_db(db_path)
        mod.main()

        from research.db import OmniLabDB

        with OmniLabDB(db_path) as db:
            before = {e.experiment_id: (e.execution_status, e.research_verdict) for e in db.list_experiments()}

        mod.main()  # second run
        captured = capsys.readouterr()
        assert "already accepts" in captured.out

        with OmniLabDB(db_path) as db:
            after = {e.experiment_id: (e.execution_status, e.research_verdict) for e in db.list_experiments()}
        assert before == after

    def test_events_carried_forward(self, migration_module):
        mod, db_path = migration_module
        _make_old_style_db(db_path)
        mod.main()

        conn = sqlite3.connect(str(db_path))
        try:
            rows = conn.execute(
                "SELECT experiment_id, note FROM experiment_events WHERE experiment_id = ?",
                ("EXP-TEST1",),
            ).fetchall()
        finally:
            conn.close()
        assert ("EXP-TEST1", "test fixture event") in rows

    def test_real_repo_registry_and_db_families_now_agree(self):
        """Not a migration-mechanics test -- a direct assertion that the
        actual research/experiment_registry.py and research/db.py in THIS
        repo now declare the same canonical family set, which was the
        Phase F->G consistency issue this migration exists to fix."""
        from research.db import EXPERIMENT_FAMILIES
        from research.experiment_registry import REGISTRY

        registry_families = set(REGISTRY.keys())
        db_families = set(EXPERIMENT_FAMILIES)
        assert registry_families == db_families, (
            f"registry/db family sets disagree: registry-only={registry_families - db_families}, "
            f"db-only={db_families - registry_families}"
        )
        assert "application_decision_logic" in db_families
