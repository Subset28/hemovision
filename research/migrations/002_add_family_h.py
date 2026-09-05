"""One-off migration: widen the `experiments` table's `experiment_family`
CHECK constraint to accept the 8th family, 'application_decision_logic'
(TTS/announcement decision-logic experiments -- registry-only, no runner
yet, per research/experiment_registry.py). Run ONCE, by hand:

    uv run python -m research.migrations.002_add_family_h

Not part of ongoing automation -- research/orchestrator.py never imports
this module. Safe to re-run (idempotent): if research/omnilab.db's
`experiments` table's CHECK constraint already accepts
'application_decision_logic', the script prints a message and exits
without touching anything.

Why a migration is needed at all
---------------------------------
SQLite cannot ALTER a CHECK constraint in place. The standard, safe SQLite
migration pattern is: create a new table with the desired schema, copy
every row across unchanged, drop the old table, rename the new one into
place -- all inside one transaction, so a crash mid-migration leaves the
original table untouched rather than half-migrated. research/db.py owns
the canonical CREATE TABLE statement (via OmniLabDB._create_tables), so
this script imports that same DDL rather than duplicating a second copy
of the schema that could drift.

No experiment family value changes for any existing row -- EXP-0001..0005
all use families already in the original 7-value set, so this migration
is purely additive (widening what's allowed), never rewriting data.
"""

from __future__ import annotations

import shutil
import sqlite3

from research.config import DB_PATH
from research.db import EXPERIMENT_FAMILIES

NEW_FAMILY = "application_decision_logic"


def _current_check_accepts_new_family(conn: sqlite3.Connection) -> bool:
    """Detect whether the live CHECK constraint already includes NEW_FAMILY,
    by reading the table's own recorded schema text (sqlite_master.sql) --
    not by trying an INSERT (which would leave a stray test row on failure
    and a row to clean up on success)."""
    cur = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='experiments'"
    )
    row = cur.fetchone()
    if row is None:
        return False  # table doesn't exist yet -- OmniLabDB() will create it fresh with the new schema
    return NEW_FAMILY in row[0]


def main() -> None:
    if not DB_PATH.exists():
        print(f"{DB_PATH} does not exist -- nothing to migrate. "
              "A fresh OmniLabDB() will create the table with the new (8-family) schema already.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    try:
        if _current_check_accepts_new_family(conn):
            print(f"{DB_PATH}'s experiments table already accepts {NEW_FAMILY!r} -- nothing to migrate.")
            return
    finally:
        conn.close()

    backup_path = DB_PATH.with_suffix(".db.pre-002-backup")
    if backup_path.exists():
        raise FileExistsError(
            f"refusing to overwrite existing backup at {backup_path} -- "
            "remove it manually first if you intend to re-run this migration."
        )
    shutil.copy2(DB_PATH, backup_path)
    print(f"Backed up {DB_PATH} -> {backup_path}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN")

        # 1. Read every existing row from the old-constraint table (raw SQL --
        #    every existing value is already legal under both the old and
        #    new CHECK, so no row needs its experiment_family rewritten).
        experiments_rows = [dict(r) for r in conn.execute("SELECT * FROM experiments").fetchall()]
        events_rows = [dict(r) for r in conn.execute("SELECT * FROM experiment_events").fetchall()]

        # 2. Rename the old table out of the way, then let OmniLabDB's own
        #    CREATE TABLE (already updated to the 8-family CHECK in
        #    research/db.py) create the new one under the real name --
        #    single source of truth for the DDL, no duplicated schema text
        #    in this migration script.
        conn.execute("ALTER TABLE experiments RENAME TO experiments_pre_002")
        conn.execute("ALTER TABLE experiment_events RENAME TO experiment_events_pre_002")
        conn.commit()
    finally:
        conn.close()

    from research.db import OmniLabDB  # local import: build the new-schema tables via the canonical DDL

    db = OmniLabDB(DB_PATH)  # creates `experiments` (new 8-family CHECK) + `experiment_events`
    try:
        for row in experiments_rows:
            assert row["experiment_family"] in EXPERIMENT_FAMILIES, (
                f"{row['experiment_id']}: experiment_family {row['experiment_family']!r} is not in the "
                f"canonical family set {EXPERIMENT_FAMILIES} -- refusing to migrate an already-invalid row."
            )
            cols = ", ".join(row.keys())
            placeholders = ", ".join(f":{k}" for k in row.keys())
            db._conn.execute(f"INSERT INTO experiments ({cols}) VALUES ({placeholders})", row)

        for row in events_rows:
            cols = ", ".join(row.keys())
            placeholders = ", ".join(f":{k}" for k in row.keys())
            db._conn.execute(f"INSERT INTO experiment_events ({cols}) VALUES ({placeholders})", row)

        # Drop experiment_events_pre_002 BEFORE experiments_pre_002: it holds
        # a FOREIGN KEY on experiments_pre_002(experiment_id), and SQLite
        # enforces FK constraints on DROP TABLE too -- dropping the
        # referenced table first while a referencing table still exists
        # fails with "FOREIGN KEY constraint failed" even though every row
        # is about to disappear along with both tables.
        db._conn.execute("DROP TABLE experiment_events_pre_002")
        db._conn.execute("DROP TABLE experiments_pre_002")
        db._conn.commit()
    finally:
        db.close()

    print(f"Migrated {len(experiments_rows)} experiment row(s) and {len(events_rows)} event row(s) "
          f"to a schema that accepts {NEW_FAMILY!r}. No experiment_family value was changed.")

    print()
    print("=== Verification: final experiment_family values ===")
    with OmniLabDB(DB_PATH) as verify_db:
        for exp in verify_db.list_experiments():
            print(f"  {exp.experiment_id}: experiment_family={exp.experiment_family!r}")


if __name__ == "__main__":
    main()
