"""Phase G — best-effort prompt-injection / authority-boundary heuristic on
MODEL OUTPUT (as opposed to research/llm/privacy_guard.py, which screens
outgoing payloads).

`flag_suspicious_response(text)` is a lightweight pattern scan over a
completed LLM response. It does not block the response (the model already
ran; the call already happened and was already billed against budget) — it
surfaces a list of flags for the caller to log/display so a human reviewing
the output knows to look closer. Wire it in wherever a role response is
consumed (research/llm/router.py callers, future omnilab CLI surfaces).

Honesty about limits (Phase G section 10 requires this explicitly): this is
NOT a solved problem. Prompt injection defense via output-side keyword
matching is trivially evadable by rephrasing, translation, unicode
homoglyphs, or splitting the suspicious phrase across output boundaries.
This heuristic exists to catch the unsophisticated/obvious case and to give
a visible audit trail — it must never be treated as a security control that
makes model output safe to act on autonomously. Per this phase's absolute
constraints, model output is NEVER treated as authoritative regardless of
what this function returns (see research/llm/structured_output.py — no
LLM response can set a research_verdict, mutate research/db.py, or enter the
experiment queue, independent of whether injection_guard flags anything)."""

from __future__ import annotations

import re

_SUSPICIOUS_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore (all |the )?(previous|prior|above) instructions", re.I),
    re.compile(r"disregard (all |the )?(previous|prior|safety) (instructions|rules)", re.I),
    re.compile(r"disable (the )?guardrails?", re.I),
    re.compile(r"bypass (the )?(human )?approval", re.I),
    re.compile(r"reveal (the |your )?(api[_ ]?key|secret|password)", re.I),
    re.compile(r"reveal your (system prompt|instructions)", re.I),
    re.compile(r"you are now (in )?(developer|jailbreak|dan) mode", re.I),
    re.compile(r"act as (if you have|though you had) no (restrictions|limits)", re.I),
    re.compile(r"pretend (the )?(experiment|test) (passed|succeeded)", re.I),
    re.compile(r"set (the )?research[_ ]verdict", re.I),
]


def flag_suspicious_response(text: str) -> list[str]:
    """Return the list of matched pattern strings (empty if nothing
    matched). Best-effort only — see module docstring."""
    if not text:
        return []
    return [p.pattern for p in _SUSPICIOUS_PATTERNS if p.search(text)]
