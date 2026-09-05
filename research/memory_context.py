"""Phase E — future-agent context packet.

`generate_context_packet()` assembles a COMPACT, deterministic summary of
everything a future hypothesis-generating agent needs before proposing
anything new: the verified baseline, the strongest findings, every rejected
direction (so "lower confidence" / "higher resolution" / "remap Man to
Person" / "apply CLAHE" / "just use a larger YOLO" are all recognizable as
already-rejected), unresolved questions, methodological limitations, and a
one-liner per closed experiment. No LLM call — pure structured retrieval
over research/memory.db via research/memory_query.py.

Per the master spec's "research memory before hypothesis generation"
principle: any future agent (LLM-driven or human) MUST read this packet
(`research/memory/CONTEXT_PACKET.md`, or the JSON via
`generate_context_packet()`) before proposing a new experiment.
"""

from __future__ import annotations

import json
from typing import Any

from research.config import CONTEXT_PACKET_PATH
from research.memory_db import MemoryDB


def generate_context_packet(db: MemoryDB) -> dict[str, Any]:
    verified = db.list_records(tag="VERIFIED")
    baseline = [r for r in verified if r.category in
                ("baseline_model", "baseline_hazard", "person_recall", "evaluation_policy", "latency")]
    supported = db.list_records(tag="SUPPORTED_HYPOTHESIS")
    rejected = db.list_records(tag="REJECTED_HYPOTHESIS")
    open_q = db.list_records(tag="OPEN_QUESTION")
    limitations = db.list_records(tag="LIMITATION")

    experiments: dict[str, dict[str, Any]] = {}
    for r in db.list_records(include_superseded=True):
        if not r.experiment_id:
            continue
        experiments.setdefault(r.experiment_id, {
            "experiment_id": r.experiment_id,
            "independent_variable": r.independent_variable,
            "verdict": r.verdict,
        })

    packet = {
        "generated_from": "research/memory.db (Phase E structured research memory)",
        "verified_baseline": [
            {"record_id": r.record_id, "claim": r.claim, "artifact_path": r.artifact_path}
            for r in baseline
        ],
        "strongest_findings": [
            {"record_id": r.record_id, "tag": r.tag, "claim": r.claim}
            for r in (verified[:3] + supported)
            if r.category in ("person_failure_modes", "model_representation")
        ],
        "rejected_directions": [
            {
                "record_id": r.record_id,
                "experiment_id": r.experiment_id,
                "claim": r.claim,
            }
            for r in rejected
        ],
        "unresolved_questions": [
            {"record_id": r.record_id, "claim": r.claim} for r in open_q
        ],
        "limitations": [
            {"record_id": r.record_id, "claim": r.claim} for r in limitations
        ],
        "experiments_closed": sorted(experiments.values(), key=lambda d: d["experiment_id"]),
        "note": "Phase D is CLOSED. Do not create EXP-0006 or any new experiment based on this "
                "packet alone without explicit human approval of a new phase.",
    }
    return packet


def render_markdown(packet: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Research Memory — Context Packet")
    lines.append("")
    lines.append("Regenerable artifact — produced by "
                  "`research/memory_context.py::generate_context_packet()`. "
                  "Do not hand-edit; re-run the generator instead.")
    lines.append("")
    lines.append("**Read this before proposing any new experiment.** Phase D (EXP-0001 through "
                  "EXP-0005) is closed. Do not re-propose anything in 'Rejected directions' below.")
    lines.append("")

    lines.append("## Verified baseline")
    for item in packet["verified_baseline"]:
        lines.append(f"- **[{item['record_id']}]** {item['claim']} (`{item['artifact_path']}`)")
    lines.append("")

    lines.append("## Strongest findings")
    for item in packet["strongest_findings"]:
        lines.append(f"- **[{item['record_id']}]** ({item['tag']}) {item['claim']}")
    lines.append("")

    lines.append("## Rejected directions — do not re-propose these")
    for item in packet["rejected_directions"]:
        lines.append(f"- **[{item['record_id']}]** ({item['experiment_id']}) {item['claim']}")
    lines.append("")

    lines.append("## Unresolved questions")
    for item in packet["unresolved_questions"]:
        lines.append(f"- **[{item['record_id']}]** {item['claim']}")
    lines.append("")

    lines.append("## Limitations")
    for item in packet["limitations"]:
        lines.append(f"- **[{item['record_id']}]** {item['claim']}")
    lines.append("")

    lines.append("## Experiments closed (Phase D)")
    for exp in packet["experiments_closed"]:
        lines.append(f"- {exp['experiment_id']}: independent_variable={exp['independent_variable']!r}, "
                      f"verdict={exp['verdict']}")
    lines.append("")
    lines.append(f"> {packet['note']}")
    lines.append("")
    return "\n".join(lines)


def write_context_packet(db: MemoryDB, path=CONTEXT_PACKET_PATH) -> dict[str, Any]:
    packet = generate_context_packet(db)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(packet), encoding="utf-8")
    return packet


def main() -> int:
    db = MemoryDB()
    try:
        packet = write_context_packet(db)
    finally:
        db.close()
    print(json.dumps(packet, indent=2))
    print(f"\nWrote {CONTEXT_PACKET_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
