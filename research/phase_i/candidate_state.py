"""Phase I — the minimum safe candidate-run state machine.

Deliberately small: NOT a general workflow engine. One JSON state file per
candidate (research/candidates/<CANDIDATE-ID>/state.json), one explicit
transition function, fail-closed on anything ambiguous. This exists
specifically to satisfy the crash/restart-idempotency requirement identified
as an unmitigated threat in reports/phase_i/PHASE_I_READINESS_AUDIT.md: a
restart must never duplicate a researcher/reviewer/revision call, overwrite
an existing artifact, or silently guess what already happened.

States
------
CREATED             -- candidate id allocated, nothing else has happened yet.
RESEARCHER_COMPLETED -- researcher call succeeded, proposal artifact written.
VALIDATED           -- deterministic schema+redundancy checks passed
                       (queue-admissible in principle, still just a candidate).
REVIEW_COMPLETED    -- reviewer call succeeded, critique artifact written.
REVISION_COMPLETED  -- (only if reviewer said REVISE) revision call succeeded,
                       revision artifact written, revalidated.
FINALIZED           -- terminal, successful: a final candidate report exists,
                       awaiting human review. NEVER means "approved" or
                       "queued" -- see research/phase_i/loop.py's module
                       docstring for that distinction.
REJECTED            -- terminal: deterministic validation failed, or the
                       reviewer recommended REJECT. Preserved, never deleted.
BLOCKED             -- terminal: a precondition (operational gate, budget,
                       free-model check) refused before/during the cycle.
FAILED              -- terminal: an unexpected/transport failure stopped the
                       cycle (e.g. LLMUnavailableError, malformed response).

Every one of REJECTED/BLOCKED/FAILED/FINALIZED is TERMINAL -- no further
transition is ever allowed out of it. This is what makes restart-safety
simple: `resolve_resume_point()` below only ever needs to ask "what is the
last COMPLETED, non-terminal stage", never to reconstruct partial state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from research.config import REPO_ROOT

CANDIDATES_DIR = REPO_ROOT / "research" / "candidates"

CREATED = "CREATED"
RESEARCHER_COMPLETED = "RESEARCHER_COMPLETED"
VALIDATED = "VALIDATED"
REVIEW_COMPLETED = "REVIEW_COMPLETED"
REVISION_COMPLETED = "REVISION_COMPLETED"
FINALIZED = "FINALIZED"
REJECTED = "REJECTED"
BLOCKED = "BLOCKED"
FAILED = "FAILED"

ALL_STATES = frozenset({
    CREATED, RESEARCHER_COMPLETED, VALIDATED, REVIEW_COMPLETED,
    REVISION_COMPLETED, FINALIZED, REJECTED, BLOCKED, FAILED,
})

# BLOCKED is deliberately NOT terminal: it means "the operational gate
# (PAUSED/STOPPED) refused this attempt", a TEMPORARY condition, not a
# scientific/technical verdict on the candidate. A resume from BLOCKED must
# pick back up exactly where it left off -- see resolve_resume_point()'s
# artifact-presence-driven logic below, which BLOCKED shares with the
# genuinely-in-progress states. FINALIZED/REJECTED/FAILED are the only true
# terminals (a scientific/technical outcome that must never be revisited).
TERMINAL_STATES = frozenset({FINALIZED, REJECTED, FAILED})

# Explicit transition table -- anything not listed here is refused.
ALLOWED_TRANSITIONS: dict[str, frozenset] = {
    CREATED: frozenset({RESEARCHER_COMPLETED, BLOCKED, FAILED}),
    RESEARCHER_COMPLETED: frozenset({VALIDATED, REJECTED, BLOCKED, FAILED}),
    VALIDATED: frozenset({REVIEW_COMPLETED, BLOCKED, FAILED}),
    # REVIEW_COMPLETED forks three ways depending on the reviewer's
    # recommendation (ACCEPT -> FINALIZED, REJECT -> REJECTED,
    # REVISE -> REVISION_COMPLETED after one bounded revision call).
    REVIEW_COMPLETED: frozenset({FINALIZED, REJECTED, REVISION_COMPLETED, BLOCKED, FAILED}),
    REVISION_COMPLETED: frozenset({FINALIZED, BLOCKED, FAILED}),
    # BLOCKED can resume onward to whatever the NEXT stage would have been --
    # the union of every forward transition any pre-terminal state could
    # reach. resolve_resume_point() (artifact-presence-driven) determines
    # which one actually applies for a given candidate; this table only
    # needs to not refuse a transition that could legitimately happen next.
    BLOCKED: frozenset({
        RESEARCHER_COMPLETED, VALIDATED, REVIEW_COMPLETED, REVISION_COMPLETED,
        FINALIZED, REJECTED, BLOCKED, FAILED,
    }),
    FINALIZED: frozenset(),
    REJECTED: frozenset(),
    FAILED: frozenset(),
}


class CandidateStateError(RuntimeError):
    """Raised for an illegal transition, or when persisted state is
    ambiguous/inconsistent with what's actually on disk (fail closed --
    never guess what already happened)."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CandidateRecord:
    candidate_id: str
    state: str = CREATED
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)
    calls_made: int = 0
    calls_budget: int = 3
    proposal_path: Optional[str] = None
    review_path: Optional[str] = None
    revision_path: Optional[str] = None
    final_report_path: Optional[str] = None
    stopped_reason: str = ""
    history: list = field(default_factory=list)  # [{"from": ..., "to": ..., "at": ...}, ...]

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "calls_made": self.calls_made,
            "calls_budget": self.calls_budget,
            "proposal_path": self.proposal_path,
            "review_path": self.review_path,
            "revision_path": self.revision_path,
            "final_report_path": self.final_report_path,
            "stopped_reason": self.stopped_reason,
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CandidateRecord":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def _candidate_dir(candidate_id: str) -> Path:
    return CANDIDATES_DIR / candidate_id


def _state_path(candidate_id: str) -> Path:
    return _candidate_dir(candidate_id) / "state.json"


def next_candidate_id() -> str:
    """Allocate the next CANDIDATE-NNNN id -- same pattern as
    research/dry_run/pipeline.py::_next_dryrun_id, deliberately a DISTINCT
    namespace/directory (research/candidates/, never research/
    dry_run_proposals/) and DISTINCT prefix (never EXP-, never DRYRUN-) so a
    Phase I candidate can never be mistaken for a real experiment id or a
    Phase H dry-run artifact."""
    CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(p.name for p in CANDIDATES_DIR.iterdir() if p.is_dir() and p.name.startswith("CANDIDATE-"))
    n = len(existing) + 1
    return f"CANDIDATE-{n:04d}"


def list_all_candidates() -> list:
    """All persisted candidates, oldest first. Used for candidate-history
    redundancy checks (Phase I second-cycle authorization, section 2) --
    CANDIDATE-0001 (and any other prior candidate) counts as prior proposal
    history even though it never became an EXP row. Never touches
    research/db.py/EXP-XXXX in any way; a corrupt individual candidate's
    state.json is skipped (fail-closed for THAT candidate only -- a
    redundancy check must not crash the whole cycle over one unrelated bad
    file), not fatal to the caller."""
    if not CANDIDATES_DIR.exists():
        return []
    records = []
    for p in sorted(CANDIDATES_DIR.iterdir()):
        if not (p.is_dir() and p.name.startswith("CANDIDATE-")):
            continue
        try:
            records.append(load_candidate(p.name))
        except CandidateStateError:
            continue
    return records


def create_candidate() -> CandidateRecord:
    """Allocate a new candidate id and persist its initial CREATED state.
    Never touches EXP-XXXX/research/db.py in any way."""
    candidate_id = next_candidate_id()
    record = CandidateRecord(candidate_id=candidate_id, calls_budget=3)
    _save(record)
    return record


def load_candidate(candidate_id: str) -> CandidateRecord:
    path = _state_path(candidate_id)
    if not path.exists():
        raise CandidateStateError(f"no persisted state for {candidate_id!r} at {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise CandidateStateError(f"{candidate_id}: state.json is corrupt/unreadable: {e}") from e
    return CandidateRecord.from_dict(data)


def _save(record: CandidateRecord) -> None:
    d = _candidate_dir(record.candidate_id)
    d.mkdir(parents=True, exist_ok=True)
    _state_path(record.candidate_id).write_text(
        json.dumps(record.to_dict(), indent=2, sort_keys=True, default=str), encoding="utf-8"
    )


def transition(record: CandidateRecord, new_state: str, *, reason: str = "") -> CandidateRecord:
    """The ONLY sanctioned way to change a candidate's state. Raises
    CandidateStateError for any transition not explicitly listed in
    ALLOWED_TRANSITIONS -- including any transition attempted FROM a
    terminal state. Persists immediately (crash-safe: if the process dies
    right after this call, the new state is already on disk)."""
    if new_state not in ALL_STATES:
        raise CandidateStateError(f"unknown state {new_state!r}")
    allowed = ALLOWED_TRANSITIONS.get(record.state, frozenset())
    if new_state not in allowed:
        raise CandidateStateError(
            f"{record.candidate_id}: illegal transition {record.state!r} -> {new_state!r} "
            f"(allowed from {record.state!r}: {sorted(allowed) or 'none (terminal)'})"
        )
    record.history.append({"from": record.state, "to": new_state, "at": _utcnow(), "reason": reason})
    record.state = new_state
    record.updated_at = _utcnow()
    if reason and new_state in (REJECTED, BLOCKED, FAILED):
        record.stopped_reason = reason
    _save(record)
    return record


def save(record: CandidateRecord) -> None:
    """Persist the record without a state transition -- used when updating
    non-state fields (e.g. proposal_path, calls_made) mid-stage."""
    _save(record)


def resolve_resume_point(candidate_id: str) -> tuple[CandidateRecord, str]:
    """Fail-closed restart helper: load a candidate's persisted state and
    verify the artifact(s) its state claims exist actually do. Returns
    (record, resume_stage) where resume_stage names what should happen
    next ("researcher" | "validate" | "reviewer" | "revision" | "done").
    Raises CandidateStateError if the persisted state is inconsistent with
    what's actually on disk (e.g. state says RESEARCHER_COMPLETED but no
    proposal file exists) -- never silently re-derives or guesses."""
    record = load_candidate(candidate_id)

    def _require_artifact(path_str: Optional[str], label: str) -> None:
        if not path_str or not Path(path_str).exists():
            raise CandidateStateError(
                f"{candidate_id}: state is {record.state!r} but the {label} artifact "
                f"({path_str!r}) does not exist -- ambiguous persisted state, refusing "
                "to guess what already happened."
            )

    if record.state in TERMINAL_STATES:
        return record, "done"

    if record.state == CREATED:
        return record, "researcher"

    # RESEARCHER_COMPLETED, VALIDATED, REVIEW_COMPLETED, and BLOCKED (a
    # temporary operational-gate refusal, not terminal -- see BLOCKED's
    # docstring above) are all resolved the SAME way: by which artifacts
    # actually exist on disk, never by trusting the state label alone for
    # BLOCKED (which could have been recorded at any of several points).
    if record.state == RESEARCHER_COMPLETED:
        _require_artifact(record.proposal_path, "proposal")
        return record, "validate"
    if record.state == VALIDATED:
        _require_artifact(record.proposal_path, "proposal")
        return record, "reviewer"
    if record.state == REVIEW_COMPLETED:
        _require_artifact(record.proposal_path, "proposal")
        _require_artifact(record.review_path, "review")
        return record, "revision"
    if record.state == REVISION_COMPLETED:
        _require_artifact(record.revision_path, "revision")
        return record, "done"
    if record.state == BLOCKED:
        if record.revision_path:
            return record, "done"
        if record.review_path:
            _require_artifact(record.proposal_path, "proposal")
            return record, "revision"
        if record.proposal_path:
            return record, "validate"
        return record, "researcher"

    raise CandidateStateError(f"{candidate_id}: unrecognized state {record.state!r}")
