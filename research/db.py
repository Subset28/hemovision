"""Typed SQLite wrapper for the experiment database (research/omnilab.db).

No ORM — dataclasses + stdlib sqlite3, per the Phase C spec ("this is
infrastructure not a product"). Two tables:

  - experiments        one row per EXP-XXXX record (full experiment spec + result)
  - experiment_events   append-only audit log of status/verdict transitions

Two orthogonal axes (Phase C.5 fix — see research/README.md "Execution status
vs. research verdict" for the full rationale)
----------------------------------------------------------------------------
The original schema had a single `status` column conflating "did the
pipeline run" with "was the scientific result good" (QUEUED/RUNNING/PASSED/
FAILED/REJECTED/INCONCLUSIVE/BLOCKED all mixed together). That made
`research/experiment_lifecycle.py`'s directory-per-status scheme misleading:
an INCONCLUSIVE experiment (EXP-0004) landed in `completed/` (execution
succeeded — correct) right next to nothing, while FAILED experiments
(EXP-0002, EXP-0003, both of which also executed successfully — they just
produced a negative research result) landed in a separate `failed/` bucket
that read as if something had gone wrong operationally. It hadn't; the
pipeline worked exactly as intended and produced real, negative evidence.

This is fixed by splitting the single column into two:

  - `execution_status` (EXECUTION_STATUSES below): did the pipeline run to
    completion? QUEUED -> RUNNING -> {COMPLETED, ABORTED, BLOCKED}. This is
    the axis `ALLOWED_TRANSITIONS` governs, and the axis
    `research/experiment_lifecycle.py` uses to choose an experiment's
    directory (experiments/{queued,running,completed,blocked,aborted}/).
    ABORTED is new: it means the runner crashed / hit a resource limit /
    never produced a fair, complete result to judge — distinct from a
    REJECTED *verdict* (below), which means the pipeline ran fine but the
    result was thrown out post-hoc as structurally invalid.

  - `research_verdict` (RESEARCH_VERDICTS below): what does the scientific
    result MEAN? Only meaningful once execution_status=COMPLETED (enforced
    by `set_research_verdict`, not `transition_status`). Values: PENDING
    (no verdict yet — the only value legal before execution_status=
    COMPLETED), PASS, FAIL, INCONCLUSIVE, REJECTED.

    REJECTED lives on the verdict axis, not the execution axis, even though
    `research/rejection.py`'s checks (dataset tampering, unrelated files
    touched, pytest failure on the experiment branch, etc.) are structural
    rather than about the numbers. The reason: those checks run AFTER the
    pipeline has already executed to completion — a rejected experiment
    still has an execution_status of COMPLETED (the world did stay sane
    long enough to produce a result; the result is just discarded as unfair
    evidence for the declared hypothesis). Modeling REJECTED as an execution
    status would make execution_status lie about whether the run finished.

Choice made explicitly: `status` is RENAMED to `execution_status` (not kept
alongside a new column) with a narrowed, execution-only value set, and
`research_verdict` is added as a genuinely new column. Renaming rather than
leaving `status` as a vestigial duplicate avoids two columns that can
silently drift out of sync, and the audit log (`experiment_events`) already
preserves full history of the old conflated value for EXP-0001..0004 from
before this migration (see research/migrations/001_split_status_verdict.py).

Status-transition policy (deliberate, not accidental — see
`ALLOWED_TRANSITIONS` below, which now governs ONLY execution_status):
QUEUED -> RUNNING -> {COMPLETED, ABORTED, BLOCKED}. A QUEUED experiment can
never jump straight to COMPLETED without passing through RUNNING — this
mirrors the real-world requirement that an execution result must be backed
by an actual run, not just declared. BLOCKED is reachable from QUEUED (an
experiment can be provisionally queued but marked blocked pending a
dependency) and BLOCKED can return to QUEUED once unblocked. Terminal
execution states (COMPLETED, ABORTED) do not transition further in this
phase — retrying an experiment means creating a new EXP-XXXX record with
`parent_experiment_id` set, not mutating the old one's execution_status.

Setting `research_verdict` is a SEPARATE, less-constrained operation
(`set_research_verdict`), available only when execution_status=COMPLETED,
and — once set to anything other than PENDING — immutable, same spirit as
the old terminal-status immutability: a verdict is scientific history, not
a mutable field. `update_fields` refuses to touch either
`execution_status` or `research_verdict` directly, for the same audit-log
reason it already refused `status`.
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
    "application_decision_logic",  # family H, added Phase F->G cleanup (research/migrations/002_add_family_h.py) --
                                    # registry-only until a runner exists; TTS/announcement-decision-logic
                                    # experiments (e.g. SpeechEngine cooldown/priority tuning), REQUIRES_IPHONE-leaning.
)

# Execution axis: did the pipeline run to completion?
EXECUTION_STATUSES = (
    "QUEUED",
    "RUNNING",
    "COMPLETED",
    "BLOCKED",
    "ABORTED",
)

# Research axis: what does the result mean? Only meaningful once
# execution_status == "COMPLETED". PENDING is the only legal value before
# that (while QUEUED/RUNNING/BLOCKED/ABORTED).
RESEARCH_VERDICTS = (
    "PENDING",
    "PASS",
    "FAIL",
    "INCONCLUSIVE",
    "REJECTED",
)

VALIDATION_REQUIREMENTS = (
    "OFFLINE_SIMULATABLE",
    "REQUIRES_MAC",
    "REQUIRES_IPHONE",
)

TERMINAL_EXECUTION_STATUSES = ("COMPLETED", "ABORTED")

# execution_status -> set of execution_statuses it may transition to.
# Governs ONLY execution_status; research_verdict has its own, separate rule
# (see set_research_verdict): legal only from execution_status=COMPLETED,
# and immutable once set to anything other than PENDING.
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "QUEUED": ("RUNNING", "BLOCKED"),
    "BLOCKED": ("QUEUED",),
    "RUNNING": ("COMPLETED", "ABORTED", "BLOCKED"),
    "COMPLETED": (),
    "ABORTED": (),
}


class TransitionError(ValueError):
    """Raised when an execution_status transition is not allowed by
    ALLOWED_TRANSITIONS."""


class VerdictError(ValueError):
    """Raised when set_research_verdict is called out of order (before
    execution_status=COMPLETED) or on an experiment that already has a
    recorded (non-PENDING) verdict — verdicts are immutable once set."""


class ImmutableExperimentError(VerdictError):
    """Raised when update_fields()/set_research_verdict() is called against
    an experiment whose scientific record is already finalized
    (execution_status=COMPLETED) without allow_amendment=True. Phase-I-
    readiness HIGH finding #3 (reports/phase_i/PHASE_I_READINESS_AUDIT.md):
    update_fields() previously had NO guard at all against rewriting
    metrics/conclusion/etc. on an already-COMPLETED experiment -- every
    write silently succeeded with no audit trail. A legitimate correction
    is still possible via allow_amendment=True + a non-empty reason, which
    is itself logged to experiment_events (see _log_amendment) — this is a
    deliberate, audited exception, never a silent overwrite. Subclasses
    VerdictError (not bare ValueError) so pre-existing callers that catch
    `except VerdictError` for "verdict already set" keep working unchanged
    -- this is strictly a more specific exception, not a different one."""


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
    execution_status: str = "QUEUED"
    research_verdict: str = "PENDING"
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
        if self.execution_status not in EXECUTION_STATUSES:
            raise ValueError(f"invalid execution_status: {self.execution_status!r}")
        if self.research_verdict not in RESEARCH_VERDICTS:
            raise ValueError(f"invalid research_verdict: {self.research_verdict!r}")
        if self.research_verdict != "PENDING" and self.execution_status != "COMPLETED":
            raise ValueError(
                f"invalid combination: research_verdict={self.research_verdict!r} requires "
                f"execution_status='COMPLETED', got {self.execution_status!r}"
            )
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
                                 'training_data','temporal_pipeline',
                                 'application_decision_logic')),
    git_branch               TEXT,
    start_commit              TEXT,
    end_commit                TEXT,
    model_version              TEXT,
    dataset_version             TEXT,
    configuration                TEXT NOT NULL DEFAULT '{}',
    baseline_run_id               TEXT NOT NULL,
    result_run_id                  TEXT,
    execution_status                TEXT NOT NULL CHECK (execution_status IN (
                                 'QUEUED','RUNNING','COMPLETED','BLOCKED','ABORTED')),
    research_verdict                 TEXT NOT NULL DEFAULT 'PENDING' CHECK (research_verdict IN (
                                 'PENDING','PASS','FAIL','INCONCLUSIVE','REJECTED')),
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
            (exp.experiment_id, exp.execution_status, "created", _utcnow()),
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

    def list_experiments(
        self, execution_status: Optional[str] = None, research_verdict: Optional[str] = None
    ) -> list[Experiment]:
        clauses = []
        params: list[str] = []
        if execution_status is not None:
            clauses.append("execution_status = ?")
            params.append(execution_status)
        if research_verdict is not None:
            clauses.append("research_verdict = ?")
            params.append(research_verdict)
        sql = "SELECT * FROM experiments"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY experiment_id"
        cur = self._conn.execute(sql, params)
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
        """Move an experiment's execution_status to a new value, enforcing
        ALLOWED_TRANSITIONS. Logs the transition to experiment_events. Raises
        TransitionError if the transition is not permitted (e.g.
        QUEUED -> COMPLETED directly). This governs execution_status ONLY —
        use set_research_verdict() to record a scientific verdict."""
        if to_status not in EXECUTION_STATUSES:
            raise ValueError(f"invalid execution_status: {to_status!r}")
        exp = self.get_experiment(experiment_id)
        allowed = ALLOWED_TRANSITIONS.get(exp.execution_status, ())
        if to_status not in allowed:
            raise TransitionError(
                f"{experiment_id}: cannot transition execution_status {exp.execution_status!r} -> "
                f"{to_status!r}. Allowed from {exp.execution_status!r}: {allowed!r}"
            )
        now = _utcnow()
        completed_at = now if to_status in TERMINAL_EXECUTION_STATUSES else exp.completed_at
        self._conn.execute(
            "UPDATE experiments SET execution_status = ?, updated_at = ?, completed_at = ? "
            "WHERE experiment_id = ?",
            (to_status, now, completed_at, experiment_id),
        )
        self._conn.execute(
            "INSERT INTO experiment_events (experiment_id, from_status, to_status, note, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (experiment_id, exp.execution_status, to_status, note, now),
        )
        self._conn.commit()
        return self.get_experiment(experiment_id)

    def _log_amendment(self, experiment_id: str, field_name: str, old_value: Any, new_value: Any, reason: str, now: str) -> None:
        """Append-only audit record for an explicit, human-authorized
        correction to an already-finalized experiment. Distinct event-type
        prefix ('amend:') so the audit log can tell an amendment apart from
        a normal execution_status/verdict transition."""
        self._conn.execute(
            "INSERT INTO experiment_events (experiment_id, from_status, to_status, note, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                experiment_id,
                f"amend:{field_name}={old_value!r}",
                f"amend:{field_name}={new_value!r}",
                f"AMENDMENT (reason: {reason})",
                now,
            ),
        )

    def set_research_verdict(
        self, experiment_id: str, verdict: str, note: Optional[str] = None,
        *, allow_amendment: bool = False, reason: str = "",
    ) -> Experiment:
        """Record the scientific verdict for an experiment. Distinct from
        transition_status() — this is a separate, less-constrained operation
        available ONLY once execution_status='COMPLETED' (a verdict must be
        backed by a finished run), and immutable once set to anything other
        than PENDING (a verdict is scientific history, not a mutable field;
        retrying means a new EXP-XXXX record with parent_experiment_id set).
        Logs to experiment_events with from_status/to_status prefixed
        'verdict:' so the audit log distinguishes verdict changes from
        execution_status transitions.

        `allow_amendment=True` + a non-empty `reason` is the ONLY sanctioned
        way to change an already-finalized (non-PENDING) verdict -- an
        explicit, audited correction (Phase-I-readiness HIGH finding #3),
        never a silent overwrite."""
        if verdict not in RESEARCH_VERDICTS:
            raise ValueError(f"invalid research_verdict: {verdict!r}")
        exp = self.get_experiment(experiment_id)
        if exp.execution_status != "COMPLETED":
            raise VerdictError(
                f"{experiment_id}: cannot set research_verdict while execution_status="
                f"{exp.execution_status!r} — a verdict requires execution_status='COMPLETED'."
            )
        if exp.research_verdict != "PENDING":
            if not allow_amendment:
                raise ImmutableExperimentError(
                    f"{experiment_id}: research_verdict is already {exp.research_verdict!r} — "
                    "verdicts are immutable once set. Pass allow_amendment=True with a non-empty "
                    "reason for an explicit, audited correction, or create a new EXP-XXXX record "
                    "with parent_experiment_id set to retry."
                )
            if not reason or not reason.strip():
                raise ValueError("allow_amendment=True requires a non-empty reason")
        now = _utcnow()
        self._conn.execute(
            "UPDATE experiments SET research_verdict = ?, updated_at = ? WHERE experiment_id = ?",
            (verdict, now, experiment_id),
        )
        if allow_amendment and exp.research_verdict != "PENDING":
            self._log_amendment(experiment_id, "research_verdict", exp.research_verdict, verdict, reason, now)
        else:
            self._conn.execute(
                "INSERT INTO experiment_events (experiment_id, from_status, to_status, note, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (experiment_id, f"verdict:{exp.research_verdict}", f"verdict:{verdict}", note, now),
            )
        self._conn.commit()
        return self.get_experiment(experiment_id)

    def update_fields(
        self, experiment_id: str, *, allow_amendment: bool = False, reason: str = "", **fields: Any,
    ) -> Experiment:
        """Update arbitrary non-status/non-verdict fields (e.g. metrics,
        conclusion, result_run_id, git_branch, end_commit). Use
        transition_status() for execution_status changes and
        set_research_verdict() for verdict changes — this method refuses to
        touch either directly, to keep the audit log authoritative.

        Phase-I-readiness HIGH finding #3: once execution_status='COMPLETED',
        this method refuses to write ANY field unless allow_amendment=True
        with a non-empty reason -- previously there was no guard at all, so
        metrics/conclusion/etc. could be silently rewritten on an already-
        finalized experiment with zero audit trail. A legitimate correction
        goes through allow_amendment=True (logged to experiment_events, old
        value preserved) -- history is appended to, never erased."""
        if "execution_status" in fields or "status" in fields:
            raise ValueError("use transition_status() to change execution_status, not update_fields()")
        if "research_verdict" in fields:
            raise ValueError("use set_research_verdict() to change research_verdict, not update_fields()")
        exp = self.get_experiment(experiment_id)
        if exp.execution_status == "COMPLETED":
            if not allow_amendment:
                raise ImmutableExperimentError(
                    f"{experiment_id}: execution_status is already COMPLETED — its scientific "
                    "record fields are immutable. Pass allow_amendment=True with a non-empty "
                    "reason for an explicit, audited correction."
                )
            if not reason or not reason.strip():
                raise ValueError("allow_amendment=True requires a non-empty reason")
        set_clauses = []
        params: dict[str, Any] = {"experiment_id": experiment_id}
        now = _utcnow()
        for k, v in fields.items():
            if k in _JSON_FIELDS and v is not None:
                v = json.dumps(v)
            set_clauses.append(f"{k} = :{k}")
            params[k] = v
            if allow_amendment and exp.execution_status == "COMPLETED":
                self._log_amendment(experiment_id, k, getattr(exp, k, None), fields[k], reason, now)
        set_clauses.append("updated_at = :updated_at")
        params["updated_at"] = now
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
