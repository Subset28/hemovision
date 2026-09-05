# Phase I Implementation — Proposal-Only Autonomous Research Loop

**Does not rewrite Phase H history.** See `reports/phase_h/PHASE_H_COMPLETION.md`
and `reports/phase_i/PHASE_I_READINESS_AUDIT.md`/`PHASE_I_SAFETY_INVARIANTS.md`
for everything before this document.

## Authority boundary

Phase I is authorized for **proposal / review / bounded-revision only**.
`research/phase_i/loop.py`'s module docstring states this as an absolute:
the module never queues, never creates `EXP-0006` or any `EXP-XXXX` row,
never creates a git branch, never trains, never benchmarks, never downloads
external data, never touches `ios/`/`benchmark/config.py`, and never sets
any of Phase F's 7 human-authority approval flags to `True`.

The terminal output of a Phase I cycle is one of:
- `FINALIZED` — a scientifically reviewed candidate report awaiting human
  decision (never "approved", never "queued").
- `REJECTED` — deterministic validation failed, or the reviewer said REJECT.
- `BLOCKED` — the operational gate (PAUSED/STOPPED) refused an attempt.
- `FAILED` — a transport/parsing failure stopped the cycle.

A candidate becoming an experiment (`EXP-0006`) is a **separate, explicit,
human-invoked step that does not exist anywhere in this module.**

## Reused infrastructure (no second LLM-calling code path)

`research/phase_i/loop.py` calls `research/dry_run/pipeline.py::_call_llm`
directly — the exact same canonical choke point Phase H built and this
round's hardening pass secured:
- `operational_state.check_gate()` as the first statement (CRITICAL #1)
- unconditional free-model-only preflight (CRITICAL #2)
- one-HTTP-request-per-logical-step invariant (never `router.complete()`)
- returned-model provenance check (`ModelProvenanceMismatchError`)
- native structured-output parsing/validation

Phase I adds only: (a) the `CANDIDATE-NNNN` artifact namespace, structurally
distinct from `EXP-XXXX` and `DRYRUN-NNNN`, and (b) the crash/restart-safe
state machine described below.

## Candidate state machine (`research/phase_i/candidate_state.py`)

Deliberately small — one JSON state file per candidate
(`research/candidates/<CANDIDATE-ID>/state.json`), one transition function,
fail-closed on ambiguity. Not a general workflow engine.

States: `CREATED`, `RESEARCHER_COMPLETED`, `VALIDATED`, `REVIEW_COMPLETED`,
`REVISION_COMPLETED`, `FINALIZED`, `REJECTED`, `BLOCKED`, `FAILED`.

`FINALIZED`/`REJECTED`/`FAILED` are true terminals — no transition out is
ever legal. `BLOCKED` is **deliberately not terminal**: it means the
operational gate refused an attempt, a temporary condition, not a verdict —
a candidate can resume onward from `BLOCKED` exactly where it left off.

`ALLOWED_TRANSITIONS` is an explicit table; `transition()` raises
`CandidateStateError` for anything not listed. Every transition persists
immediately (crash-safe: if the process dies right after, the new state is
already on disk).

## Restart / idempotency semantics

`resolve_resume_point(candidate_id)` determines what should happen next by
inspecting which artifact files actually exist on disk (`proposal_path`,
`review_path`, `revision_path`), not by trusting the state label alone for
`BLOCKED` (which could have been recorded at several different points):

- No proposal artifact → resume at `researcher`.
- Proposal exists, no review → resume at `validate` (cheap, no LLM call,
  always safely re-run).
- Review exists, no revision → resume at `revision` (only reached if the
  reviewer said REVISE).
- Revision exists, or state is a true terminal → `done`, nothing to do.

If a state claims an artifact exists but the file is missing, this raises
`CandidateStateError` rather than guessing — fail closed on ambiguity.

This guarantees: a restart after the researcher stage does not repeat the
researcher call; after the reviewer stage, does not repeat the reviewer
call; after the revision stage, does not repeat the revision call; and an
already-`FINALIZED`/`REJECTED`/`FAILED` candidate makes zero further calls
if resumed. All proven by `tests/test_phase_i_loop.py::TestRestartIdempotency`.

## Call budget

Per cycle: researcher ≤1, reviewer ≤1, revision ≤1 (only if reviewer says
REVISE) — enforced by the same `DryRunCallBudget(3)` Phase H uses, restored
from `record.calls_made` on resume so a restart cannot silently gain extra
budget. Retries = 0, fallbacks = 0 (same structural guarantee as Phase H —
`_call_llm` never calls `LLMRouter.complete()`'s fallback loop). The daily
global `UsageTracker` budget remains independently authoritative on top of
this per-cycle cap.

## Reviewer recommendation (ACCEPT / REVISE / REJECT)

Derived deterministically from `ReviewerCritique`'s existing
`worth_running`/`recommends_revision` booleans — no schema change:
- `recommends_revision=True` → `REVISE`
- `recommends_revision=False, worth_running=True` → `ACCEPT`
- `recommends_revision=False, worth_running=False` → `REJECT`

## Human handoff

Every `FINALIZED` cycle writes `<CANDIDATE-ID>-final.json`
(`artifact_type: PHASE_I_FINAL_CANDIDATE`), which explicitly states
`actually_queued: false`, `actually_registered_as_experiment: false`, lists
every human approval still required, and names the file this reconciliation
was checked against. This file — and the underlying proposal/review/
revision artifacts it never overwrites — is the entire Phase I deliverable
for human review.

## Failure behavior

Every stage's `_call_llm` invocation is wrapped to catch, in order:
`ValidationError` (malformed structured output) → `FAILED`;
`operational_state.OperationalGateError` (PAUSED/STOPPED) → `BLOCKED`;
`_CALL_UNAVAILABLE` (transport/capability/pricing/catalog/provenance
failures) → `FAILED`. Every failure path persists the candidate's state and
`stopped_reason` before returning — nothing is lost, nothing crashes
uncaught.
