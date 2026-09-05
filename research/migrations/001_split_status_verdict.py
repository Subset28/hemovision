"""One-off migration: split the old single `status` column into
`execution_status` + `research_verdict` (see research/db.py's module
docstring and research/README.md's "Execution status vs. research verdict"
section for the full rationale). Run ONCE, by hand:

    uv run python -m research.migrations.001_split_status_verdict

Not part of ongoing automation — research/orchestrator.py never imports
this module. Safe to re-run (idempotent): if research/omnilab.db's
`experiments` table already has an `execution_status` column, the script
prints a message and exits without touching anything.

What this does, in order
-------------------------
1. If research/omnilab.db exists, back it up to
   research/omnilab.db.pre-001-backup (never overwritten by this script if
   that backup already exists — refuses rather than clobbering an earlier
   backup) and reads its `experiments` + `experiment_events` rows with the
   OLD schema (single `status` column) via raw sqlite3 (bypassing
   research/db.py's OmniLabDB, which now speaks the NEW schema and would
   fail to read old rows).
2. If research/omnilab.db does NOT exist (or has no `experiments` table),
   reconstructs the 4 known records (EXP-0001..0004) directly from
   experiments/*/EXP-000N/results.json + config.yaml + hypothesis.md, which
   is the more robust source of truth per the task spec (the DB is
   gitignored/regenerable; the on-disk experiment artifacts are the durable
   record). EXP-0005 is reconstructed from research/seed_experiments.py's
   declared record (its BLOCKED status was never runner-derived, so there is
   no results.json for it).
3. Determines each experiment's (execution_status, research_verdict) pair.
   EXP-0001's mapping is NOT a mechanical "old status -> new status"
   rename: the finding recorded below (see EXP0001_VERDICT_NOTE) is that
   EXP-0001's old status=PASSED meant "the confirmatory/control hypothesis
   was confirmed," which is semantically a research_verdict of PASS with
   execution_status=COMPLETED — never "conf=0.05 is production-viable."
   This was verified by reading:
     - research/runners.py::run_exp_0001's docstring (explicit
       verdict_interpretation inversion: a hard evaluation-policy FAILED
       verdict CONFIRMS this experiment's negative hypothesis)
     - experiments/completed/EXP-0001/conclusion.md ("Final status: PASSED",
       "Raw evaluation-policy verdict: FAILED", both present and consistent)
   EXP-0002/EXP-0003's old status=FAILED are real research failures (the
   resolution / semantic-remapping interventions did not work) -> FAIL.
   EXP-0004's old status=INCONCLUSIVE (best candidate's delta below the
   pre-registered minimum meaningful delta) -> INCONCLUSIVE.
   EXP-0005's old status=BLOCKED (never run) -> execution_status=BLOCKED,
   research_verdict=PENDING (no verdict exists yet — this script does NOT
   unblock or run EXP-0005; it only relocates its directory into the new
   execution-status-keyed layout, per research/README.md's directory
   scheme).
4. Recreates the `experiments` table under the new schema (via
   research.db.OmniLabDB, which owns the CREATE TABLE statement) and
   inserts every row with execution_status/research_verdict backfilled,
   preserving every other original field exactly. Copies
   `experiment_events` across unchanged (its schema did not change; old
   entries keep their original QUEUED/RUNNING/PASSED/... vocabulary as
   historical record, plus one new migration event per experiment).
5. Moves each experiment's on-disk directory to the new
   experiments/{queued,running,completed,blocked,aborted}/ layout:
     EXP-0001 completed/       (unchanged — already correct bucket)
     EXP-0002 failed/ -> completed/
     EXP-0003 failed/ -> completed/
     EXP-0004 completed/       (unchanged — already correct bucket)
     EXP-0005 queued/ -> blocked/
   Then removes the now-empty legacy `experiments/failed/` and
   `experiments/rejected/` directories (never deletes anything with content
   in it — refuses if either is non-empty after the moves above).
6. Prints the final DB rows and directory layout for by-hand verification
   (per the task spec: "verify the resulting DB rows and directory layout
   by hand, don't just trust the script ran without error").
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

from research.config import DB_PATH, EXPERIMENTS_DIR, REPO_ROOT

# ---------------------------------------------------------------------------
# EXP-0001 semantics — read and documented BEFORE assigning research_verdict
# (task requirement: do not silently reinterpret EXP-0001's verdict).
# ---------------------------------------------------------------------------
EXP0001_VERDICT_NOTE = (
    "EXP-0001 is a confirmatory/control experiment. Its hypothesis is a "
    "NEGATIVE claim: 'threshold alone cannot resolve Person recall without "
    "unacceptable precision loss.' The old status=PASSED recorded by "
    "research/orchestrator.py was produced via run_exp_0001's "
    "verdict_interpretation inversion ({'PASSED':'FAIL','FAILED':'PASS',...}) "
    "specifically BECAUSE the raw evaluation-policy verdict was FAILED (the "
    "hazard-precision guardrail was badly violated at conf=0.05) -- see "
    "experiments/completed/EXP-0001/conclusion.md: 'Final status: PASSED' / "
    "'Raw evaluation-policy verdict: FAILED'. A hard guardrail-violating "
    "FAILED verdict is exactly what CONFIRMS this experiment's negative "
    "hypothesis. Therefore: execution_status=COMPLETED, "
    "research_verdict=PASS means 'the hypothesis that threshold-only cannot "
    "resolve Person recall without unacceptable precision loss was "
    "confirmed' -- it does NOT mean 'conf=0.05 is a good production "
    "setting.' The opposite is true: this PASS verdict is the evidence "
    "against ever shipping conf=0.05. This is stated explicitly in "
    "research/README.md's 'Execution status vs. research verdict' section "
    "and in research/runners.py::run_exp_0001's docstring."
)

# experiment_id -> (execution_status, research_verdict), verified against
# each experiment's results.json/conclusion.md before assignment (see
# module docstring and EXP0001_VERDICT_NOTE above).
VERDICT_MAP: dict[str, tuple[str, str]] = {
    "EXP-0001": ("COMPLETED", "PASS"),         # confirmatory hypothesis confirmed (see EXP0001_VERDICT_NOTE)
    "EXP-0002": ("COMPLETED", "FAIL"),          # resolution intervention did not work
    "EXP-0003": ("COMPLETED", "FAIL"),          # semantic remapping did not work
    "EXP-0004": ("COMPLETED", "INCONCLUSIVE"),  # preprocessing effect below meaningful-delta threshold
    "EXP-0005": ("BLOCKED", "PENDING"),         # never run; blocked pending 0002/0003/0004 (per seed_experiments.py)
}

# Old on-disk directory -> new on-disk directory, execution-status-keyed.
DIRECTORY_MOVES: dict[str, str] = {
    "EXP-0001": "completed",
    "EXP-0002": "completed",
    "EXP-0003": "completed",
    "EXP-0004": "completed",
    "EXP-0005": "blocked",
}


def _find_old_dir(experiment_id: str) -> Path | None:
    for legacy in ("queued", "active", "running", "completed", "failed", "rejected", "blocked", "aborted"):
        candidate = EXPERIMENTS_DIR / legacy / experiment_id
        if candidate.exists():
            return candidate
    return None


def _reconstruct_from_artifacts(experiment_id: str) -> dict | None:
    """Fallback source of truth when the DB is missing/never persisted:
    build a minimal experiment record from on-disk artifacts. Returns a
    dict of the old-schema-shaped fields (including a 'status' key) or None
    if nothing is found for this id."""
    old_dir = _find_old_dir(experiment_id)
    if old_dir is None:
        return None

    results_path = old_dir / "results.json"
    results = {}
    if results_path.exists():
        try:
            results = json.loads(results_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            results = {}

    old_status = results.get("final_experiment_status")
    if old_status is None:
        # No results.json (e.g. EXP-0005, never run) -> treat as BLOCKED/QUEUED
        # per whichever legacy directory it's currently sitting in.
        parent_name = old_dir.parent.name
        old_status = {"queued": "QUEUED", "active": "RUNNING", "blocked": "BLOCKED"}.get(parent_name, "QUEUED")

    return {
        "experiment_id": experiment_id,
        "status": old_status,
        "conclusion": None,
        "metrics": results if results else None,
    }


def _read_old_db_rows(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    cur = conn.execute("SELECT * FROM experiments ORDER BY experiment_id")
    return [dict(r) for r in cur.fetchall()]


def _has_new_schema(conn: sqlite3.Connection) -> bool:
    cur = conn.execute("PRAGMA table_info(experiments)")
    cols = {r[1] for r in cur.fetchall()}
    return "execution_status" in cols


def main() -> None:
    print(EXP0001_VERDICT_NOTE)
    print()

    old_rows: list[dict] = []
    old_events: list[dict] = []

    if DB_PATH.exists():
        raw = sqlite3.connect(str(DB_PATH))
        raw.row_factory = sqlite3.Row
        try:
            if _has_new_schema(raw):
                print(f"{DB_PATH} already has execution_status/research_verdict — nothing to migrate.")
                raw.close()
                return
            old_rows = _read_old_db_rows(raw)
            try:
                cur = raw.execute("SELECT * FROM experiment_events ORDER BY id")
                old_events = [dict(r) for r in cur.fetchall()]
            except sqlite3.OperationalError:
                old_events = []
        finally:
            raw.close()

        backup_path = DB_PATH.with_suffix(".db.pre-001-backup")
        if backup_path.exists():
            raise FileExistsError(
                f"refusing to overwrite existing backup at {backup_path} — "
                "remove it manually first if you intend to re-run this migration."
            )
        shutil.copy2(DB_PATH, backup_path)
        print(f"Backed up {DB_PATH} -> {backup_path}")
    else:
        print(f"{DB_PATH} does not exist — reconstructing records from on-disk experiment artifacts.")

    # Reconstruct/verify every known experiment id, cross-checking the DB
    # row (if any) against the on-disk results.json (if any).
    all_ids = sorted(set(VERDICT_MAP) | {r["experiment_id"] for r in old_rows})
    by_id_db = {r["experiment_id"]: r for r in old_rows}

    resolved: dict[str, dict] = {}
    for exp_id in all_ids:
        db_row = by_id_db.get(exp_id)
        artifact = _reconstruct_from_artifacts(exp_id)
        if db_row is not None:
            source = "db"
            record = db_row
        elif artifact is not None:
            source = "artifacts"
            record = artifact
        else:
            print(f"WARNING: no DB row and no on-disk artifacts found for {exp_id} — skipping.")
            continue

        if db_row is not None and artifact is not None:
            db_status = db_row.get("status")
            artifact_status = artifact.get("status")
            if db_status != artifact_status:
                print(
                    f"NOTE: {exp_id} DB status ({db_status!r}) and on-disk results.json "
                    f"final_experiment_status ({artifact_status!r}) disagree — using DB as "
                    "primary source (it is the more complete record), cross-checked here for visibility."
                )

        resolved[exp_id] = {"source": source, "record": record}
        print(f"{exp_id}: source={source} old_status={record.get('status')!r}")

    print()

    # ---- rebuild the experiments table under the new schema ----
    from research.db import OmniLabDB, Experiment  # local import: only valid once db.py is migrated to the new schema

    if DB_PATH.exists():
        DB_PATH.unlink()  # the backup above already preserved the pre-migration file

    db = OmniLabDB(DB_PATH)  # creates the new-schema experiments/experiment_events tables

    for exp_id in all_ids:
        if exp_id not in resolved:
            continue
        record = resolved[exp_id]["record"]
        if exp_id not in VERDICT_MAP:
            raise ValueError(
                f"{exp_id} has no entry in VERDICT_MAP — this migration only knows how to "
                "backfill EXP-0001..0005; add an explicit, documented mapping before running "
                "this script on a DB containing any other experiment id."
            )
        execution_status, research_verdict = VERDICT_MAP[exp_id]

        if "hypothesis" in record:
            # Came from the old DB row — carry every original field forward,
            # only replacing status with the new pair.
            row = dict(record)
            row.pop("status", None)
            for json_field in ("controls", "success_criteria", "configuration", "metrics", "estimated_cost"):
                v = row.get(json_field)
                if isinstance(v, str):
                    row[json_field] = json.loads(v) if v else {}
            exp = Experiment(
                **{k: v for k, v in row.items() if k in Experiment.__dataclass_fields__},
                execution_status=execution_status,
                research_verdict=research_verdict,
            )
        else:
            # Reconstructed from artifacts only (should not happen for
            # EXP-0001..0005 in this repo, since the DB already exists, but
            # kept for the "DB missing" fallback path per the task spec).
            from research.config import CANONICAL_BASELINE_RUN_ID

            exp = Experiment(
                experiment_id=exp_id,
                hypothesis=f"(reconstructed from experiments/*/{exp_id}/results.json — see migration script)",
                motivation="(reconstructed)",
                rationale="(reconstructed)",
                independent_variable="(reconstructed)",
                baseline_run_id=CANONICAL_BASELINE_RUN_ID,
                experiment_family="threshold_postprocessing",
                execution_status=execution_status,
                research_verdict=research_verdict,
                metrics=record.get("metrics"),
            )

        # Insert directly (bypassing create_experiment's own event-logging
        # default so we can log a migration-specific event instead).
        row = __import__("dataclasses").asdict(exp)
        for json_field in ("controls", "success_criteria", "configuration", "metrics", "estimated_cost"):
            row[json_field] = json.dumps(row[json_field]) if row[json_field] is not None else None
        cols = ", ".join(row.keys())
        placeholders = ", ".join(f":{k}" for k in row.keys())
        db._conn.execute(f"INSERT INTO experiments ({cols}) VALUES ({placeholders})", row)
        db._conn.execute(
            "INSERT INTO experiment_events (experiment_id, from_status, to_status, note, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                exp_id,
                f"status:{resolved[exp_id]['record'].get('status')}",
                f"execution_status:{execution_status};research_verdict:{research_verdict}",
                "research/migrations/001_split_status_verdict.py",
                exp.updated_at,
            ),
        )
        db._conn.commit()
        print(f"{exp_id}: inserted execution_status={execution_status} research_verdict={research_verdict}")

    # Carry forward the old audit log too, for continuity (schema unchanged).
    for ev in old_events:
        db._conn.execute(
            "INSERT INTO experiment_events (experiment_id, from_status, to_status, note, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (ev["experiment_id"], ev["from_status"], ev["to_status"], ev["note"], ev["timestamp"]),
        )
    db._conn.commit()
    print(f"Carried forward {len(old_events)} pre-migration experiment_events row(s).")

    db.close()

    # ---- move directories to the new execution-status-keyed layout ----
    print()
    for exp_id, new_bucket in DIRECTORY_MOVES.items():
        old_dir = _find_old_dir(exp_id)
        if old_dir is None:
            print(f"{exp_id}: no on-disk directory found, skipping move.")
            continue
        new_dir = EXPERIMENTS_DIR / new_bucket / exp_id
        if old_dir == new_dir:
            print(f"{exp_id}: already at {new_dir} — no move needed.")
            continue
        new_dir.parent.mkdir(parents=True, exist_ok=True)
        if new_dir.exists():
            raise FileExistsError(f"refusing to overwrite existing directory at {new_dir}")
        shutil.move(str(old_dir), str(new_dir))
        print(f"{exp_id}: moved {old_dir} -> {new_dir}")

    for legacy_name in ("failed", "rejected", "active"):
        legacy_dir = EXPERIMENTS_DIR / legacy_name
        if legacy_dir.exists():
            remaining = list(legacy_dir.iterdir())
            if remaining:
                print(f"NOTE: {legacy_dir} still has content ({remaining}) — leaving it in place, not deleting.")
            else:
                legacy_dir.rmdir()
                print(f"Removed now-empty legacy directory {legacy_dir}")

    for bucket in ("queued", "running", "completed", "blocked", "aborted"):
        (EXPERIMENTS_DIR / bucket).mkdir(parents=True, exist_ok=True)

    # ---- verification: print final rows and directory layout ----
    print()
    print("=== Final DB rows ===")
    with OmniLabDB(DB_PATH) as verify_db:
        for exp in verify_db.list_experiments():
            print(
                f"  {exp.experiment_id}: execution_status={exp.execution_status} "
                f"research_verdict={exp.research_verdict}"
            )

    print()
    print("=== Final directory layout ===")
    for bucket in ("queued", "running", "completed", "blocked", "aborted"):
        d = EXPERIMENTS_DIR / bucket
        contents = sorted(p.name for p in d.iterdir()) if d.exists() else []
        print(f"  experiments/{bucket}/: {contents}")


if __name__ == "__main__":
    main()
