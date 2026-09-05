"""Phase E — structured research memory.

Typed SQLite wrapper for `research/memory.db`, following the exact pattern
established by `research/db.py` (`OmniLabDB`): dataclasses + stdlib sqlite3,
no ORM. This is a SIBLING database, not new tables bolted onto
`research/omnilab.db` — see "Design choice" below for why.

Phase E's job (per the task spec) is to turn Phase A-D findings into
structured, queryable research memory with an explicit evidence-level
ontology, mandatory provenance, and supersession tracking — replacing
"read five markdown files and hope you remember the caveats" with something
a future agent can query deterministically (`research/memory_query.py`) and
that produces a compact context packet (`research/memory_context.py`)
before it proposes anything.

Ontology (`MEMORY_TAGS`)
------------------------
- VERIFIED             — a fact directly measured/confirmed against a real
                          artifact (a metrics.json field, a run_metadata.json
                          field, a source file's literal content).
- SUPPORTED_HYPOTHESIS  — evidence points this way but is not proven; must
                          not be worded as a settled fact.
- OPEN_QUESTION         — an explicit unresolved question this lab cannot
                          currently answer (missing resource, deconfounding
                          not done, etc).
- REJECTED_HYPOTHESIS   — an idea a real experiment's evidence argues
                          against. One per closed experimental direction
                          (EXP-0001..0005), plus any others well-supported by
                          the artifacts.
- LIMITATION            — a methodological constraint on what ANY finding in
                          this lab can claim (proxy latency, static-image
                          eval, thin samples, etc), independent of any single
                          experiment.

Every tag has a fixed `status` lifecycle: ACTIVE (the current, correct
version of a claim) or SUPERSEDED (superseded by a newer, more rigorous
record — kept forever, never deleted, but excluded from default queries).
See `supersede()` below for the mechanism, and
`research/memory_seed.py::SUPERSESSION_35_TO_5_4` for the flagship case this
was built for (Phase B.5's informal "~35% of Person misses are semantic
class confusion" claim, superseded by EXP-0003's rigorous IoU-based
re-matching: 13/239 = 5.4%).

Mandatory evidence provenance
------------------------------
Every record must carry at least one concrete provenance pointer: an
`experiment_id`, a `run_id`, or an `artifact_path`. `MemoryDB.insert()`
calls `validate_provenance()` and raises `ProvenanceError` if none is
present — there is no code path that inserts a claim with zero evidence.
`git_commit`, `metric_field`, and `dataset_version` are additional,
optional-but-encouraged provenance detail (not sufficient on their own to
satisfy the check, since a commit hash alone doesn't say WHERE the claim
came from).

Design choice: sibling database, not new tables in research/omnilab.db
------------------------------------------------------------------------
`research/db.py::OmniLabDB` models experiment *execution* — its schema,
transition rules, and immutability guarantees (verdicts are immutable once
set; only `transition_status`/`set_research_verdict` may touch those
columns) are specifically about experiment lifecycle, not general knowledge
claims about the system. Memory records have a different lifecycle
(supersession, not state-machine transitions) and a different mutation
model (a record's `status`/`superseded_by`/`supersedes` fields DO change
after creation, unlike an Experiment's core fields). Bolting a
knowledge-claim table onto `OmniLabDB` would mean either (a) reusing its
migration-sensitive `_init_schema()` for a schema with unrelated invariants,
or (b) forking OmniLabDB's internals to add a second unrelated concern to
one class. A sibling module with its own DB file
(`research/memory.db`, `research/config.py::MEMORY_DB_PATH`) keeps both
schemas independently testable and migration-safe, at the cost of
cross-referencing `experiment_id`s as plain (unenforced) string values
rather than a real SQL foreign key — acceptable here since
`research/omnilab.db` is itself gitignored/regenerable and the durable
source of truth for experiment facts is the `experiments/completed/EXP-XXXX/`
directories on disk, which `research/memory_seed.py` reads directly.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from research.config import MEMORY_DB_PATH

# ---------------------------------------------------------------------------
# Ontology
# ---------------------------------------------------------------------------

MEMORY_TAGS = (
    "VERIFIED",
    "SUPPORTED_HYPOTHESIS",
    "OPEN_QUESTION",
    "REJECTED_HYPOTHESIS",
    "LIMITATION",
)

MEMORY_STATUSES = ("ACTIVE", "SUPERSEDED")


class ProvenanceError(ValueError):
    """Raised when a record has no concrete evidence pointer at all."""


class MemoryRecordNotFoundError(KeyError):
    pass


class SupersessionError(ValueError):
    """Raised when supersede() is called on records that are already linked,
    already superseded, or otherwise in an inconsistent state."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------


@dataclass
class MemoryRecord:
    record_id: str
    claim: str
    tag: str
    # -- evidence provenance (at least one of experiment_id/run_id/artifact_path
    #    must be set; see validate_provenance()) --
    experiment_id: Optional[str] = None
    run_id: Optional[str] = None
    artifact_path: Optional[str] = None
    metric_field: Optional[str] = None
    dataset_version: Optional[str] = None
    git_commit: Optional[str] = None
    # -- supersession / lifecycle --
    status: str = "ACTIVE"
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    # -- grouping / retrieval helpers --
    category: str = ""  # e.g. "person_recall", "class_confusion", "latency"
    independent_variable: Optional[str] = None  # convenience mirror of Experiment field, when experiment_id set
    verdict: Optional[str] = None  # convenience mirror of Experiment.research_verdict, when experiment_id set
    notes: str = ""
    created_at: str = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if self.tag not in MEMORY_TAGS:
            raise ValueError(f"invalid memory tag: {self.tag!r} (must be one of {MEMORY_TAGS})")
        if self.status not in MEMORY_STATUSES:
            raise ValueError(f"invalid memory status: {self.status!r} (must be one of {MEMORY_STATUSES})")


def validate_provenance(rec: MemoryRecord) -> None:
    """Raise ProvenanceError unless the record carries at least one concrete
    evidence pointer. Called by MemoryDB.insert() — there is no code path
    that skips this check."""
    if not (rec.experiment_id or rec.run_id or rec.artifact_path):
        raise ProvenanceError(
            f"{rec.record_id}: no evidence provenance — at least one of "
            "experiment_id, run_id, or artifact_path is required. "
            f"claim={rec.claim!r}"
        )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_records (
    record_id             TEXT PRIMARY KEY,
    claim                 TEXT NOT NULL,
    tag                   TEXT NOT NULL CHECK (tag IN (
                              'VERIFIED','SUPPORTED_HYPOTHESIS','OPEN_QUESTION',
                              'REJECTED_HYPOTHESIS','LIMITATION')),
    experiment_id         TEXT,
    run_id                TEXT,
    artifact_path         TEXT,
    metric_field          TEXT,
    dataset_version       TEXT,
    git_commit            TEXT,
    status                TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','SUPERSEDED')),
    supersedes            TEXT,
    superseded_by         TEXT,
    category              TEXT NOT NULL DEFAULT '',
    independent_variable  TEXT,
    verdict               TEXT,
    notes                 TEXT NOT NULL DEFAULT '',
    created_at            TEXT NOT NULL,
    FOREIGN KEY (supersedes) REFERENCES memory_records(record_id),
    FOREIGN KEY (superseded_by) REFERENCES memory_records(record_id)
);

CREATE INDEX IF NOT EXISTS idx_memory_tag ON memory_records(tag);
CREATE INDEX IF NOT EXISTS idx_memory_status ON memory_records(status);
CREATE INDEX IF NOT EXISTS idx_memory_experiment ON memory_records(experiment_id);
"""


class MemoryDB:
    def __init__(self, db_path: Path = MEMORY_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "MemoryDB":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- id allocation --------------------------------------------------

    def next_record_id(self) -> str:
        cur = self._conn.execute(
            "SELECT record_id FROM memory_records ORDER BY record_id DESC"
        )
        rows = cur.fetchall()
        if not rows:
            return "MEM-0001"
        nums = [int(r["record_id"].split("-")[1]) for r in rows if r["record_id"].startswith("MEM-")]
        return f"MEM-{(max(nums) + 1):04d}" if nums else "MEM-0001"

    # -- create -----------------------------------------------------------

    def insert(self, rec: MemoryRecord) -> MemoryRecord:
        """Insert a new memory record. Raises ProvenanceError if the record
        has no evidence pointer; raises sqlite3.IntegrityError on a
        duplicate record_id."""
        validate_provenance(rec)
        row = asdict(rec)
        self._conn.execute(
            "INSERT INTO memory_records "
            "(record_id, claim, tag, experiment_id, run_id, artifact_path, metric_field, "
            "dataset_version, git_commit, status, supersedes, superseded_by, category, "
            "independent_variable, verdict, notes, created_at) VALUES "
            "(:record_id, :claim, :tag, :experiment_id, :run_id, :artifact_path, :metric_field, "
            ":dataset_version, :git_commit, :status, :supersedes, :superseded_by, :category, "
            ":independent_variable, :verdict, :notes, :created_at)",
            row,
        )
        self._conn.commit()
        return rec

    # -- read ---------------------------------------------------------------

    def get(self, record_id: str) -> MemoryRecord:
        cur = self._conn.execute("SELECT * FROM memory_records WHERE record_id = ?", (record_id,))
        row = cur.fetchone()
        if row is None:
            raise MemoryRecordNotFoundError(record_id)
        return self._row_to_record(row)

    def list_records(
        self,
        tag: Optional[str] = None,
        category: Optional[str] = None,
        experiment_id: Optional[str] = None,
        include_superseded: bool = False,
    ) -> list[MemoryRecord]:
        """Default (include_superseded=False): only ACTIVE records — a future
        agent asking "what's the class-confusion rate" gets the current,
        corrected number, not both numbers with equal weight. Pass
        include_superseded=True to retrieve full history, superseded
        records included."""
        clauses = []
        params: list[str] = []
        if not include_superseded:
            clauses.append("status = 'ACTIVE'")
        if tag is not None:
            clauses.append("tag = ?")
            params.append(tag)
        if category is not None:
            clauses.append("category = ?")
            params.append(category)
        if experiment_id is not None:
            clauses.append("experiment_id = ?")
            params.append(experiment_id)
        sql = "SELECT * FROM memory_records"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY record_id"
        cur = self._conn.execute(sql, params)
        return [self._row_to_record(r) for r in cur.fetchall()]

    def _row_to_record(self, row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(**dict(row))

    # -- supersession -----------------------------------------------------

    def supersede(self, old_id: str, new_id: str, note: str = "") -> tuple[MemoryRecord, MemoryRecord]:
        """Mark `old_id` SUPERSEDED by `new_id`, and link `new_id` back to
        `old_id` via `supersedes`. Both records must already exist (insert
        the new record first). Raises SupersessionError if `old_id` is
        already superseded by something else, or if either id does not
        exist. Idempotent-safe: calling again with the same pair is a no-op
        error (already superseded), not a silent double-link."""
        old = self.get(old_id)
        new = self.get(new_id)
        if old.status == "SUPERSEDED":
            raise SupersessionError(
                f"{old_id} is already SUPERSEDED (by {old.superseded_by!r}) — cannot re-supersede."
            )
        if old_id == new_id:
            raise SupersessionError("a record cannot supersede itself")
        now_note = note or f"superseded by {new_id}"
        self._conn.execute(
            "UPDATE memory_records SET status = 'SUPERSEDED', superseded_by = ?, notes = notes || ? "
            "WHERE record_id = ?",
            (new_id, f" [SUPERSEDED: {now_note}]", old_id),
        )
        self._conn.execute(
            "UPDATE memory_records SET supersedes = ? WHERE record_id = ?",
            (old_id, new_id),
        )
        self._conn.commit()
        return self.get(old_id), self.get(new_id)

    # -- convenience --------------------------------------------------------

    def experiments_referenced(self) -> list[str]:
        cur = self._conn.execute(
            "SELECT DISTINCT experiment_id FROM memory_records WHERE experiment_id IS NOT NULL ORDER BY experiment_id"
        )
        return [r["experiment_id"] for r in cur.fetchall()]
