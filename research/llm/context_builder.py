"""Phase G — thin context assembler for real role calls.

The PREFERRED source for any future LLM call's context is
`research/memory_context.py::generate_context_packet()` (Phase E) — a
compact, deterministic summary of verified baseline findings, rejected
hypotheses, open questions, and limitations. This module wraps that packet
into a bounded, observable payload; it never falls back to dumping raw
repository files, the full memory.db, or research/omnilab.db.

Anything beyond the context packet (an explicit research question/objective,
or a code excerpt) must be PASSED IN by the caller — this module never
reaches into the filesystem to pull additional material on its own. That is
the mechanical enforcement of Phase G's privacy/data-boundary principle:
there is no code path from "build context" to "read an arbitrary file."

`build_context()` also records which categories were actually included
(`categories_included`) and a rough size estimate, so a caller (or a test)
can observe exactly what went into a payload without re-deriving it, and
runs research/llm/privacy_guard.py's check against the assembled text before
returning — a caller must still decide whether to act on a non-empty
`privacy_violations` list (typically: refuse to send), but it never has to
build that check itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from research.llm.privacy_guard import check_payload_safe
from research.memory_context import generate_context_packet


@dataclass(frozen=True)
class BuiltContext:
    text: str
    categories_included: dict
    char_count: int
    approx_token_estimate: int  # crude len(text)//4 heuristic — not a real tokenizer
    privacy_violations: list = field(default_factory=list)

    @property
    def is_safe(self) -> bool:
        return not self.privacy_violations


def build_context(
    db,
    objective: Optional[str] = None,
    code_excerpt: Optional[str] = None,
) -> BuiltContext:
    """Assemble a bounded context object.

    `db` is a research.memory_db.MemoryDB instance (typed loosely here to
    avoid a hard import-time dependency cycle; callers pass the real thing).
    `objective` and `code_excerpt` are optional, caller-supplied strings —
    NEVER auto-derived from the filesystem or environment.
    """
    packet = generate_context_packet(db)
    parts = [json.dumps(packet, indent=2, sort_keys=True)]

    categories_included = {
        "baseline": True,
        "rejected_hypotheses": True,
        "open_questions": True,
        "objective": False,
        "code_excerpt": False,
    }

    if objective:
        parts.append(f"\n## Objective (caller-supplied)\n{objective}")
        categories_included["objective"] = True

    if code_excerpt:
        parts.append(f"\n## Code excerpt (explicitly supplied by caller, never auto-pulled)\n{code_excerpt}")
        categories_included["code_excerpt"] = True

    text = "\n".join(parts)
    violations = check_payload_safe(text)

    return BuiltContext(
        text=text,
        categories_included=categories_included,
        char_count=len(text),
        approx_token_estimate=max(1, len(text) // 4),
        privacy_violations=violations,
    )
