# Research Memory

Durable, running record of what this lab knows. Five files:

- `current_state.md` — where things stand right now (baseline numbers, active
  experiments, what's queued/blocked).
- `known_failures.md` — production failure modes and benchmark-surfaced
  weaknesses already established (Phase A/B/B.5 findings).
- `successful_methods.md` — experiments/approaches that PASSED and why.
- `failed_methods.md` — experiments/approaches that FAILED or were REJECTED
  and why (so they aren't re-tried blindly).
- `open_questions.md` — unresolved questions, explicitly including what
  requires resources this phase doesn't have (a live LLM key, a Mac/iPhone).

## Mandatory read/write protocol

**Any experiment proposal step — LLM-driven (research/llm/) or manually
seeded (as in Phase C's initial 5 experiments) — MUST read all five files in
this directory before proposing a new hypothesis.** This is enforced as an
explicit step in `research/orchestrator.py` (`propose()` reads
`research/memory/*.md` before generating/listing candidates), not left as an
unenforced convention.

**After any experiment completes (PASSED/FAILED/REJECTED/INCONCLUSIVE), the
relevant memory file(s) MUST be updated** — `research/orchestrator.py`'s
`experiment()` command has an explicit "update memory" step after the
evaluation-policy verdict and before returning to the main branch. A PASSED
experiment updates `successful_methods.md`; FAILED/REJECTED update
`failed_methods.md`; any experiment that surfaces a new failure mode updates
`known_failures.md`; anything left unresolved goes to `open_questions.md`.
