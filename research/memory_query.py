"""Phase E — deterministic, local query interface over research/memory.db.

No LLM call anywhere in this module. Every function is pure structured-data
retrieval (SQL filtering via research/memory_db.py::MemoryDB) and returns a
small, deterministic dict/list — the same query run twice returns identical
output (barring new records being inserted in between). Each function also
has a `render_*` counterpart (or shares one via `render_query_result`) for
human-readable CLI output.

Extend `research/cli.py`'s `memory` subcommand when adding a new question
type here — see QUESTION_TYPES at the bottom for the CLI's dispatch table.
"""

from __future__ import annotations

from typing import Any

from research.memory_db import MemoryDB, MemoryRecord


def _rec_to_dict(r: MemoryRecord) -> dict[str, Any]:
    return {
        "record_id": r.record_id,
        "claim": r.claim,
        "tag": r.tag,
        "status": r.status,
        "experiment_id": r.experiment_id,
        "run_id": r.run_id,
        "artifact_path": r.artifact_path,
        "metric_field": r.metric_field,
        "git_commit": r.git_commit,
        "category": r.category,
        "independent_variable": r.independent_variable,
        "verdict": r.verdict,
        "supersedes": r.supersedes,
        "superseded_by": r.superseded_by,
        "notes": r.notes,
    }


# ---------------------------------------------------------------------------
# 1. What interventions have already been tested for Person recall?
# ---------------------------------------------------------------------------

def tested_interventions_for_person_recall(db: MemoryDB) -> dict[str, Any]:
    recs = [r for r in db.list_records(include_superseded=True) if r.experiment_id]
    # dedupe by experiment_id, keep the most informative (REJECTED_HYPOTHESIS / SUPPORTED_HYPOTHESIS) record
    by_exp: dict[str, MemoryRecord] = {}
    for r in recs:
        prev = by_exp.get(r.experiment_id)
        if prev is None or r.tag in ("REJECTED_HYPOTHESIS", "SUPPORTED_HYPOTHESIS"):
            by_exp[r.experiment_id] = r
    ordered = [by_exp[k] for k in sorted(by_exp)]
    return {
        "question": "What interventions have already been tested for Person recall?",
        "results": [_rec_to_dict(r) for r in ordered],
    }


# ---------------------------------------------------------------------------
# 2. What hypotheses have been rejected?
# ---------------------------------------------------------------------------

def rejected_hypotheses(db: MemoryDB) -> dict[str, Any]:
    recs = db.list_records(tag="REJECTED_HYPOTHESIS")
    return {
        "question": "What hypotheses have been rejected?",
        "results": [_rec_to_dict(r) for r in recs],
    }


# ---------------------------------------------------------------------------
# 3. What are the dominant verified Person failure modes?
# ---------------------------------------------------------------------------

def verified_person_failure_modes(db: MemoryDB) -> dict[str, Any]:
    recs = db.list_records(tag="VERIFIED", category="person_failure_modes")
    return {
        "question": "What are the dominant verified Person failure modes?",
        "results": [_rec_to_dict(r) for r in recs],
    }


# ---------------------------------------------------------------------------
# 4. Which experiments affected TRUE_DETECTOR_MISS?
# ---------------------------------------------------------------------------

def experiments_affecting_true_detector_miss(db: MemoryDB) -> dict[str, Any]:
    recs = [
        r for r in db.list_records(include_superseded=True)
        if r.experiment_id and "TRUE_DETECTOR_MISS" in r.claim
    ]
    return {
        "question": "Which experiments affected TRUE_DETECTOR_MISS?",
        "results": [_rec_to_dict(r) for r in recs],
    }


# ---------------------------------------------------------------------------
# 5. What questions remain unresolved?
# ---------------------------------------------------------------------------

def open_questions(db: MemoryDB) -> dict[str, Any]:
    recs = db.list_records(tag="OPEN_QUESTION")
    return {
        "question": "What questions remain unresolved?",
        "results": [_rec_to_dict(r) for r in recs],
    }


# ---------------------------------------------------------------------------
# 6. What evidence supports the model-representation hypothesis?
# ---------------------------------------------------------------------------

def model_representation_evidence(db: MemoryDB) -> dict[str, Any]:
    recs = db.list_records(tag="SUPPORTED_HYPOTHESIS", category="model_representation")
    return {
        "question": "What evidence supports the model-representation hypothesis?",
        "results": [_rec_to_dict(r) for r in recs],
    }


# ---------------------------------------------------------------------------
# 7. What limitations apply to the current benchmark?
# ---------------------------------------------------------------------------

def limitations(db: MemoryDB) -> dict[str, Any]:
    recs = db.list_records(tag="LIMITATION")
    return {
        "question": "What limitations apply to the current benchmark?",
        "results": [_rec_to_dict(r) for r in recs],
    }


# ---------------------------------------------------------------------------
# Generic: records by experiment id (experiment -> finding linkage)
# ---------------------------------------------------------------------------

def records_for_experiment(db: MemoryDB, experiment_id: str) -> dict[str, Any]:
    recs = db.list_records(experiment_id=experiment_id, include_superseded=True)
    return {
        "question": f"What memory records reference {experiment_id}?",
        "results": [_rec_to_dict(r) for r in recs],
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_query_result(result: dict[str, Any]) -> str:
    lines = [result["question"], "=" * len(result["question"])]
    if not result["results"]:
        lines.append("(no matching records)")
        return "\n".join(lines)
    for r in result["results"]:
        marker = "" if r["status"] == "ACTIVE" else " [SUPERSEDED]"
        lines.append(f"\n[{r['record_id']}] ({r['tag']}{marker})")
        if r["experiment_id"]:
            lines.append(f"  experiment: {r['experiment_id']}  verdict: {r['verdict']}  "
                          f"independent_variable: {r['independent_variable']}")
        lines.append(f"  claim: {r['claim']}")
        lines.append(f"  evidence: run={r['run_id']} artifact={r['artifact_path']} "
                      f"metric={r['metric_field']} commit={r['git_commit']}")
        if r["superseded_by"]:
            lines.append(f"  superseded_by: {r['superseded_by']}")
        if r["supersedes"]:
            lines.append(f"  supersedes: {r['supersedes']}")
    return "\n".join(lines)


QUESTION_TYPES = {
    "person-interventions": tested_interventions_for_person_recall,
    "rejected": rejected_hypotheses,
    "person-failure-modes": verified_person_failure_modes,
    "true-detector-miss": experiments_affecting_true_detector_miss,
    "open-questions": open_questions,
    "model-representation": model_representation_evidence,
    "limitations": limitations,
}
