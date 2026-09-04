"""Typed SQLite wrapper for the experiment database (research/omnilab.db).

No ORM — dataclasses + stdlib sqlite3, per the Phase C spec ("this is
infrastructure not a product"). Two tables:

  - experiments        one row per EXP-XXXX record (full experiment spec + result)
  - experiment_events   append-only audit log of status transitions

Status-transition policy (deliberate, not accidental — see
`ALLOWED_TRANSITIONS` below): QUEUED -> RUNNING -> {PASSED, FAILED, REJECTED,
INCONCLUSIVE}. A QUEUED experiment can never jump straight to a terminal
verdict state without passing through RUNNING — this mirrors the real-world
requirement that a verdict must be backed by an actual benchmark execution,
not just declared. BLOCKED is reachable from QUEUED (an experiment can be
provisionally queued but marked blocked pending a dependency) and BLOCKED can
return to QUEUED once unblocked. Terminal states (PASSED, FAILED, REJECTED,
INCONCLUSIVE) do not transition further in this phase — retrying an
experiment means creating a new EXP-XXXX record with `parent_experiment_id`
set, not mutating the old one's status. This keeps the audit log honest: once
an experiment has a verdict, that verdict is immutable history.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from research.config import DB_PATH

# ---------------------------------------------------------------------------
# Enums (stored as TEXT with CHECK constraints — sqlite has no native enum)
# ---------------------------------------------------------------------------

EXPERIMENT_FAMILIES = (
    "threshold_postprocessing",
    "class_confusion",
    "small_object",
    "preprocessing",
    "model_variant",
    "training_data",
    "temporal_pipeline",
)

STATUSES = (
    "QUEUED",
    "RUNNING",
    "PASSED",
    "FAILED",
    "REJECTED",
    "INCONCLUSIVE",
    "BLOCKED",
)

VALIDATION_REQUIREMENTS = (
    "OFFLINE_SIMULATABLE",
    "REQUIRES_MAC",
    "REQUIRES_IPHONE",
)

TERMINAL_STATUSES = ("PASSED", "FAILED", "REJECTED", "INCONCLUSIVE")

# status -> set of statuses it may transition to.
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "QUEUED": ("RUNNING", "BLOCKED", "REJECTED"),
    "BLOCKED": ("QUEUED", "REJECTED"),
    "RUNNING": ("PASSED", "FAILED", "REJECTED", "INCONCLUSIVE", "BLOCKED"),
    "PASSED": (),
    "FAILED": (),
    "REJECTED": (),
    "INCONCLUSIVE": (),
}


class TransitionError(ValueError):
    """Raised when a status transition is not allowed by ALLOWED_TRANSITIONS."""


class ExperimentNotFoundError(KeyError):
    pass


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Dataclass record
# ---------------------------------------------------------------------------


@dataclass
class Experiment:
    experiment_id: str
    hypothesis: str
    motivation: str
    rationale: str
    independent_variable: str
    controls: dict = field(default_factory=dict)
    evaluation_method: str = ""
    success_criteria: dict = field(default_factory=dict)
    risks: str = ""
    expected_outcome: str = ""
    parent_experiment_id: Optional[str] = None
    experiment_family: str = "threshold_postprocessing"
    git_branch: Optional[str] = None
    start_commit: Optional[str] = None
    end_commit: Optional[str] = None
    model_version: Optional[str] = None
    dataset_version: Optional[str] = None
    configuration: dict = field(default_factory=dict)
    baseline_run_id: str = ""
    result_run_id: Optional[str] = None
    status: str = "QUEUED"
    metrics: Optional[dict] = None
    conclusion: Optional[str] = None
    validation_requirement: str = "OFFLINE_SIMULATABLE"
    estimated_cost: dict = field(default_factory=dict)
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)
    completed_at: Optional[str] = None
    llm_model_used: Optional[str] = None
    llm_tokens_used: Optional[int] = None
    llm_cost_usd: Optional[float] = None

    def __post_init__(self):
        if self.experiment_family not in EXPERIMENT_FAMILIES:
            raise ValueError(f"invalid experiment_family: {self.experiment_family!r}")
        if self.status not in STATUSES:
            raise ValueError(f"invalid status: {self.status!r}")
        if self.validation_requirement not in VALIDATION_REQUIREMENTS:
            raise ValueError(f"invalid validation_requirement: {self.validation_requirement!r}")


@dataclass
class ExperimentEvent:
    experiment_id: str
    from_status: Optional[str]
    to_status: str
    note: Optional[str]
    timestamp: str = field(default_factory=_utcnow)
    id: Optional[int] = None


_JSON_FIELDS = ("controls", "success_criteria", "configuration", "metrics", "estimated_cost")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id           TEXT PRIMARY KEY,
    hypothesis              TEXT NOT NULL,
    motivation              TEXT NOT NULL,
    rationale               TEXT NOT NULL,
    independent_variable    TEXT NOT NULL,
    controls                TEXT NOT NULL DEFAULT '{}',
    evaluation_method       TEXT NOT NULL DEFAULT '',
    success_criteria        TEXT NOT NULL DEFAULT '{}',
    risks                   TEXT NOT NULL DEFAULT '',
    expected_outcome        TEXT NOT NULL DEFAULT '',
    parent_experiment_id    TEXT,
    experiment_family       TEXT NOT NULL CHECK (experiment_family IN (
                                 'threshold_postprocessing','class_confusion',
                                 'small_object','preprocessing','model_variant',
                                 'training_data','temporal_pipeline')),
    git_branch               TEXT,
    start_commit              TEXT,
    end_commit                TEXT,
    model_version              TEXT,
    dataset_version             TEXT,
    configuration                TEXT NOT NULL DEFAULT '{}',
    baseline_run_id               TEXT NOT NULL,
    result_run_id                  TEXT,
    status                          TEXT NOT NULL CHECK (status IN (
                                 'QUEUED','RUNNING','PASSED','FAILED',
                                 'REJECTED','INCONCLUSIVE','BLOCKED')),
    metrics                          TEXT,
    conclusion                        TEXT,
    validation_requirement              TEXT NOT NULL CHECK (validation_requirement IN (
                                 'OFFLINE_SIMULATABLE','REQUIRES_MAC','REQUIRES_IPHONE')),
    estimated_cost                        TEXT NOT NULL DEFAULT '{}',
    created_at                              TEXT NOT NULL,
    updated_at                                TEXT NOT NULL,
    completed_at                                TEXT,
    llm_model_used                                TEXT,
    llm_tokens_used                                 INTEGER,
    llm_cost_usd                                      REAL,
    FOREIGN KEY (parent_experiment_id) REFERENCES experiments(experiment_id)
);

CREATE TABLE IF NOT EXISTS experiment_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id   TEXT NOT NULL,
    from_status     TEXT,
    to_status       TEXT NOT NULL,
    note            TEXT,
    timestamp       TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
);
"""


class OmniLabDB:
    def __init__(self, db_path: Path = DB_PATH):
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

    def __enter__(self) -> "OmniLabDB":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- id allocation --------------------------------------------------

    def next_experiment_id(self) -> str:
        cur = self._conn.execute(
            "SELECT experiment_id FROM experiments ORDER BY experiment_id DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            return "EXP-0001"
        last_n = int(row["experiment_id"].split("-")[1])
        return f"EXP-{last_n + 1:04d}"

    # -- create -----------------------------------------------------------

    def create_experiment(self, exp: Experiment) -> Experiment:
        """Insert a new experiment row. Raises sqlite3.IntegrityError on a
        duplicate experiment_id (uniqueness enforced by PRIMARY KEY)."""
        row = asdict(exp)
        for f in _JSON_FIELDS:
            row[f] = json.dumps(row[f]) if row[f] is not None else None
        cols = ", ".join(row.keys())
        placeholders = ", ".join(f":{k}" for k in row.keys())
        self._conn.execute(
            f"INSERT INTO experiments ({cols}) VALUES ({placeholders})", row
        )
        self._conn.execute(
            "INSERT INTO experiment_events (experiment_id, from_status, to_status, note, timestamp) "
            "VALUES (?, NULL, ?, ?, ?)",
            (exp.experiment_id, exp.status, "created", _utcnow()),
        )
        self._conn.commit()
        return exp

    # -- read ---------------------------------------------------------------

    def get_experiment(self, experiment_id: str) -> Experiment:
        cur = self._conn.execute(
            "SELECT * FROM experiments WHERE experiment_id = ?", (experiment_id,)
        )
        row = cur.fetchone()
        if row is None:
            raise ExperimentNotFoundError(experiment_id)
        return self._row_to_experiment(row)

    def list_experiments(self, status: Optional[str] = None) -> list[Experiment]:
        if status is None:
            cur = self._conn.execute("SELECT * FROM experiments ORDER BY experiment_id")
        else:
            cur = self._conn.execute(
                "SELECT * FROM experiments WHERE status = ? ORDER BY experiment_id", (status,)
            )
        return [self._row_to_experiment(r) for r in cur.fetchall()]

    def get_events(self, experiment_id: str) -> list[ExperimentEvent]:
        cur = self._conn.execute(
            "SELECT * FROM experiment_events WHERE experiment_id = ? ORDER BY id", (experiment_id,)
        )
        return [
            ExperimentEvent(
                id=r["id"],
                experiment_id=r["experiment_id"],
                from_status=r["from_status"],
                to_status=r["to_status"],
                note=r["note"],
                timestamp=r["timestamp"],
            )
            for r in cur.fetchall()
        ]

    def _row_to_experiment(self, row: sqlite3.Row) -> Experiment:
        d = dict(row)
        for f in _JSON_FIELDS:
            d[f] = json.loads(d[f]) if d[f] is not None else ({} if f != "metrics" else None)
        return Experiment(**d)

    # -- update ---------------------------------------------------------------

    def transition_status(
        self, experiment_id: str, to_status: str, note: Optional[str] = None
    ) -> Experiment:
        """Move an experiment to a new status, enforcing ALLOWED_TRANSITIONS.
        Logs the transition to experiment_events. Raises TransitionError if
        the transition is not permitted (e.g. QUEUED -> PASSED directly)."""
        if to_status not in STATUSES:
            raise ValueError(f"invalid status: {to_status!r}")
        exp = self.get_experiment(experiment_id)
        allowed = ALLOWED_TRANSITIONS.get(exp.status, ())
        if to_status not in allowed:
            raise TransitionError(
                f"{experiment_id}: cannot transition {exp.status!r} -> {to_status!r}. "
                f"Allowed from {exp.status!r}: {allowed!r}"
            )
        now = _utcnow()
        completed_at = now if to_status in TERMINAL_STATUSES else exp.completed_at
        self._conn.execute(
            "UPDATE experiments SET status = ?, updated_at = ?, completed_at = ? WHERE experiment_id = ?",
            (to_status, now, completed_at, experiment_id),
        )
        self._conn.execute(
            "INSERT INTO experiment_events (experiment_id, from_status, to_status, note, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (experiment_id, exp.status, to_status, note, now),
        )
        self._conn.commit()
        return self.get_experiment(experiment_id)

    def update_fields(self, experiment_id: str, **fields: Any) -> Experiment:
        """Update arbitrary non-status fields (e.g. metrics, conclusion,
        result_run_id, git_branch, end_commit). Use transition_status() for
        status changes — this method refuses to touch `status` directly to
        keep the audit log authoritative."""
        if "status" in fields:
            raise ValueError("use transition_status() to change status, not update_fields()")
        self.get_experiment(experiment_id)  # existence check
        set_clauses = []
        params: dict[str, Any] = {"experiment_id": experiment_id}
        for k, v in fields.items():
            if k in _JSON_FIELDS and v is not None:
                v = json.dumps(v)
            set_clauses.append(f"{k} = :{k}")
            params[k] = v
        set_clauses.append("updated_at = :updated_at")
        params["updated_at"] = _utcnow()
        sql = f"UPDATE experiments SET {', '.join(set_clauses)} WHERE experiment_id = :experiment_id"
        self._conn.execute(sql, params)
        self._conn.commit()
        return self.get_experiment(experiment_id)

    def resolve_baseline_run_dir(self, experiment_id: str) -> Path:
        """Resolve baseline_run_id to a real run directory under
        benchmark/results/. Raises FileNotFoundError if it doesn't exist —
        this is the invariant tests/test_omnilab_db.py checks."""
        from research.config import REPO_ROOT

        exp = self.get_experiment(experiment_id)
        candidates = [
            REPO_ROOT / "benchmark" / "results" / "baseline",
            REPO_ROOT / "benchmark" / "results" / "diagnostics",
        ]
        for c in candidates:
            meta = c / "run_metadata.json"
            if meta.exists():
                data = json.loads(meta.read_text(encoding="utf-8"))
                if data.get("run_id") == exp.baseline_run_id:
                    return c
        raise FileNotFoundError(
            f"{experiment_id}: baseline_run_id {exp.baseline_run_id!r} does not resolve to "
            "any real run directory under benchmark/results/"
        )
