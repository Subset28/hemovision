"""Phase H — the dry-run research agent pipeline.

memory -> problem selection -> hypothesis -> proposal -> deterministic
redundancy check -> reviewer -> (maybe one bounded revision) -> local schema
validation -> report. This module performs ONLY:
  - reads against research/db.py (OmniLabDB) and research/memory_db.py
    (MemoryDB) — never a write, never an INSERT, never a schema mutation.
  - pure-function calls into research/experiment_spec.py and
    research/experiment_validator.py (validate()/is_queue_eligible()/
    find_rejected_hypothesis_conflicts() — all read-only against the DBs
    they're given and never mutate an ExperimentProposal in place, since
    ExperimentProposal is a frozen dataclass).
  - LLM calls routed through research/llm/router.py (never a hard-coded
    model string here — see `_ROLE_RESEARCHER`/`_ROLE_REVIEWER` constants,
    which are ROLE NAMES from roles.yaml, not model ids).
  - writes exactly one NEW artifact type per run: a JSON file under
    research/dry_run_proposals/DRYRUN-NNNN.json and a markdown report under
    reports/dry_run/YYYY-MM-DD-HHMM.md. Neither path collides with anything
    research/experiment_lifecycle.py or research/db.py ever reads or writes.

This module NEVER, under any circumstance:
  - imports or calls research/orchestrator.py::queue_experiment_from_spec
    (or anything that would insert an execution_status=QUEUED row).
  - imports or calls research/git_isolation.py::create_experiment_branch.
  - imports or calls anything in research/runners.py.
  - writes to ios/, benchmark/config.py, or benchmark/results/baseline/.
  - populates any research/experiment_spec.py::ExperimentResult field.
  - constructs an ExperimentProposal with any of Phase F's 7 human-authority
    approval flags set to True — every one of them is hard-coded False at
    construction time in `_build_proposal`, regardless of what the LLM
    response contained (ProposalResponse has no field for them in the first
    place — see research/llm/structured_output.py).

The dry-run-scoped experiment_id used for the ephemeral, never-persisted
ExperimentProposal object (`_placeholder_experiment_id`) is drawn from the
EXP-9xxx range specifically so it can never collide with (or be mistaken
for) a real, sequentially-allocated EXP-XXXX id from research/db.py's
`next_experiment_id()` — EXP-0006 is never created by this module, and this
id is never passed to `OmniLabDB.create_experiment()`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from research.config import CANONICAL_BASELINE_RUN_ID, REPO_ROOT
from research.dry_run.budget import DryRunCallBudget
from research.experiment_spec import ExperimentProposal, ExperimentSpec
from research.experiment_validator import (
    ValidationResult,
    find_rejected_hypothesis_conflicts,
    is_queue_eligible,
    validate,
)
from research.llm.authorization import AuthorizationLike
from research.llm.base import ErrorCategory, LLMResponse, LLMUnavailableError, RunBudget
from research.llm.injection_guard import flag_suspicious_response
from research.llm.model_catalog import (
    ModelCapabilityError,
    ModelNotFreeError,
    evaluate_model_for_role,
)
from research.llm.privacy_guard import check_payload_safe
from research.llm.router import LLMRouter
from research.llm.structured_output import (
    ProposalResponse,
    ReviewerCritique,
    ValidationError,
    parse_and_validate_proposal,
    parse_and_validate_reviewer_critique,
)
from research.memory_context import generate_context_packet
from research.memory_db import MemoryDB

DRY_RUN_PROPOSALS_DIR = REPO_ROOT / "research" / "dry_run_proposals"
DRY_RUN_REPORTS_DIR = REPO_ROOT / "reports" / "dry_run"

# Role names from research/llm/roles.yaml — never a hard-coded model id here.
_ROLE_RESEARCHER = "researcher"
_ROLE_REVIEWER = "reviewer"

# Every call site below must catch all three of these as one logical "this
# logical step could not be fulfilled" outcome: LLMUnavailableError (a real
# transport/provider failure) and ModelNotFreeError/ModelCapabilityError (a
# zero-network pre-flight rejection from research/llm/model_catalog.py, only
# raised when model_catalog is supplied). All three degrade the same way —
# a graceful `stopped_reason`, never an uncaught crash.
_CALL_UNAVAILABLE = (LLMUnavailableError, ModelNotFreeError, ModelCapabilityError)

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _now_utc_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_prompt_template(name: str) -> str:
    path = _PROMPTS_DIR / name
    return path.read_text(encoding="utf-8")


def _system_policy_text() -> str:
    from research.config import LLM_DIR

    return (LLM_DIR / "prompts" / "system_policy.md").read_text(encoding="utf-8")


def _next_dryrun_id() -> str:
    DRY_RUN_PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(DRY_RUN_PROPOSALS_DIR.glob("DRYRUN-*.json"))
    n = len(existing) + 1
    return f"DRYRUN-{n:04d}"


def _placeholder_experiment_id(dryrun_id: str) -> str:
    """A structurally-valid (matches EXP-\\d{4}) but never-persisted id for
    the ephemeral ExperimentProposal object this dry run builds. Drawn from
    the EXP-9xxx range, disjoint from research/db.py's real sequential
    allocation (EXP-0001..EXP-0005 today) — this id is NEVER inserted into
    research/db.py and NEVER used as a real experiment id."""
    n = int(dryrun_id.split("-")[1])
    return f"EXP-9{n:03d}"


REDUNDANCY_RETRY_INSTRUCTIONS = (
    "\n\n## Your previous proposal was rejected by a DETERMINISTIC local "
    "check (not an LLM judgment)\n\n"
    "Your prior proposal's family + independent_variables matched an "
    "already-REJECTED prior hypothesis from the context packet's "
    "rejected_directions list: {conflicts}. You must now either (a) propose "
    "a genuinely different independent variable/mechanism, or (b) set "
    "acknowledges_rejected_hypothesis_ids to include the matching id(s) "
    "listed above and provide a non-empty, specific materially_new_rationale "
    "explaining what is materially different this time. A vague or "
    "boilerplate rationale will not satisfy a human reviewer even if it "
    "passes the mechanical check."
)


# The A-G failure-category taxonomy (narrow remediation build, section 5):
# distinguishes WHERE a call/parse failed, beyond just "it failed" / a raw
# exception message. `None` on a fully-successful step.
FAILURE_TRANSPORT = "TRANSPORT_FAILURE"  # timeout/network/auth/http/rate-limit/model-unavailable
FAILURE_INVALID_ENVELOPE = "INVALID_ENVELOPE"  # HTTP 200 but body did not parse as JSON at all
FAILURE_MISSING_CHOICES_MESSAGE_CONTENT = "MISSING_CHOICES_MESSAGE_CONTENT"
FAILURE_EMPTY_CONTENT = "EMPTY_CONTENT"
FAILURE_CONTENT_NOT_VALID_JSON = "CONTENT_NOT_VALID_JSON"
FAILURE_JSON_FAILED_CANONICAL_SCHEMA = "JSON_FAILED_CANONICAL_SCHEMA"
FAILURE_LOCAL_VALIDATOR_REJECTION = "LOCAL_VALIDATOR_REJECTION"


def _classify_transport_failure(e: LLMUnavailableError) -> str:
    """Map a raised LLMUnavailableError's category + diagnostics to the A-G
    taxonomy's transport-layer buckets (categories A/B/C)."""
    diag = getattr(e, "diagnostics", None) or {}
    if e.category == ErrorCategory.MALFORMED_RESPONSE:
        if diag.get("envelope_parsed") is False:
            return FAILURE_INVALID_ENVELOPE
        return FAILURE_MISSING_CHOICES_MESSAGE_CONTENT
    if e.category == ErrorCategory.EMPTY_RESPONSE:
        return FAILURE_EMPTY_CONTENT
    return FAILURE_TRANSPORT


def _annotate_last_call_record(call_records: list, step: str, **fields) -> None:
    """Attach post-hoc detail (parse-layer failure category, local
    validator result) to the CallRecord already appended by `_call_llm` for
    `step` -- the JSON-parse and local-validation stages happen one layer
    above `_call_llm`, after the HTTP round-trip it recorded."""
    for cr in reversed(call_records):
        if cr.step == step:
            for k, v in fields.items():
                setattr(cr, k, v)
            return


def _classify_parse_failure(e: ValidationError) -> str:
    """Map a raised structured_output.ValidationError to the A-G taxonomy's
    parse-layer buckets (categories D/E)."""
    msg = str(e)
    if "not valid JSON" in msg or "ambiguous" in msg:
        return FAILURE_CONTENT_NOT_VALID_JSON
    return FAILURE_JSON_FAILED_CANONICAL_SCHEMA


@dataclass
class CallRecord:
    step: str
    role: str
    model_used: Optional[str]
    succeeded: bool
    error: Optional[str] = None
    # -- Phase-remediation diagnostics (section 5) — safe fields only, never
    #    the API key, Authorization header, raw environment, private
    #    context, or the full prompt/completion text. --
    timestamp: str = ""
    dryrun_id: str = ""
    requested_model: Optional[str] = None
    selected_model: Optional[str] = None
    actual_model_returned: Optional[str] = None
    http_status: Optional[int] = None
    provider_error_code: Optional[str] = None
    provider_error_message: Optional[str] = None
    request_id: Optional[str] = None
    latency_ms: Optional[float] = None
    finish_reason: Optional[str] = None
    envelope_parsed: Optional[bool] = None
    choices_present: Optional[bool] = None
    message_present: Optional[bool] = None
    content_present: Optional[bool] = None
    content_length: Optional[int] = None
    structured_parse_result: Optional[str] = None  # one of the FAILURE_* constants, or None
    local_schema_validation_result: Optional[dict] = None  # {"is_valid": bool, "error_count": int}
    token_usage: Optional[dict] = None
    failure_category: Optional[str] = None  # one of the FAILURE_* constants, or None on success


@dataclass
class DryRunResult:
    dryrun_id: str
    placeholder_experiment_id: str
    context_packet: dict
    call_records: list = field(default_factory=list)  # list[CallRecord]
    raw_proposal_response: Optional[ProposalResponse] = None
    redundancy_conflicts: list = field(default_factory=list)  # [(exp_id, mem_id), ...]
    redundancy_rejected_initial: bool = False
    proposal: Optional[ExperimentProposal] = None
    proposal_validation: Optional[ValidationResult] = None
    reviewer_critique: Optional[ReviewerCritique] = None
    revised: bool = False
    revision_reason: str = ""
    final_validation: Optional[ValidationResult] = None
    calls_made: int = 0
    calls_budget: int = 0
    stopped_reason: str = ""


def _call_llm(
    router: LLMRouter,
    role: str,
    prompt: str,
    *,
    authorized: AuthorizationLike,
    run_budget: Optional[RunBudget],
    dry_run_budget: DryRunCallBudget,
    step: str,
    call_records: list,
    max_retries: int = 0,
    dryrun_id: str = "",
    model_catalog: Optional[dict] = None,
    require_structured_output: bool = False,
    response_format: Optional[dict] = None,
) -> LLMResponse:
    """The single choke point for every LLM call this pipeline makes.
    Checks (and records against) the dry-run budget BEFORE/AFTER the call,
    on top of whatever the router's own usage_tracker/run_budget do —
    matching Phase G's policy that a failed attempt still counts.

    IMPORTANT — single real HTTP attempt per logical dry-run call, deliberately
    NOT `router.complete()`'s normal multi-model fallback loop. Discovered
    during Phase H's live demonstration: `LLMRouter.complete()` tries every
    model in `role_cfg.models_in_order()` (preferred + all fallback_models)
    as SEPARATE real HTTP requests within one `complete()` invocation, which
    would let a single logical dry-run step silently consume 2 or 3 real
    OpenRouter requests against Phase H's hard 3-real-HTTP-request-total
    budget for the whole live demonstration — exactly what happened in the
    first live attempt (2026-09-05): one `researcher` call burned all 3 of
    the run's real requests (1 rate-limited, 2 confirmed-stale models)
    before any content was ever produced. This function resolves the role's
    PREFERRED model via the router's own roles.yaml-backed config (still no
    hard-coded model string in this module — section 10) and calls the
    provider directly for exactly one HTTP attempt; a stale/unavailable
    preferred model is reported as a normal failed call (still counted, per
    policy) rather than silently retried against a different model that
    would cost a second real request. Genuine fallback remains available —
    a caller may simply invoke `_call_llm` again for the next logical
    step — it is just never automatic/invisible within one call.

    `model_catalog` (Phase-remediation sections 1/2, optional, default
    None): a `{model_id: catalog_entry}` mapping. When provided, the role's
    `preferred_model` is checked via
    `research/llm/model_catalog.py::evaluate_model_for_role` BEFORE
    anything else in this function — a rejection (not free, or, if
    `require_structured_output=True`, lacking structured-output capability)
    raises immediately, records a CallRecord with zero budget/network
    impact (dry_run_budget/usage_tracker/run_budget are never touched, and
    `router.provider.complete()` is never called), and never falls back to
    a different/paid model. When `model_catalog` is None (the default —
    e.g. no catalog snapshot was fetched for this run), this pre-flight
    check is skipped entirely; `roles.yaml`'s `preferred_model` is used
    as-is, exactly as before this remediation build."""
    role_cfg = router._role_config(role)
    timestamp = _now_utc_str()

    if model_catalog is not None:
        catalog_entry = model_catalog.get(role_cfg.preferred_model)
        try:
            evaluate_model_for_role(
                role, role_cfg.preferred_model, catalog_entry,
                require_structured_output=require_structured_output,
            )
        except (ModelNotFreeError, ModelCapabilityError) as e:
            # Pre-flight rejection: zero network, zero budget consumption --
            # dry_run_budget/usage_tracker/run_budget are deliberately never
            # touched below, and router.provider.complete() is never called.
            call_records.append(CallRecord(
                step=step, role=role, model_used=None, succeeded=False, error=str(e),
                timestamp=timestamp, dryrun_id=dryrun_id,
                requested_model=role_cfg.preferred_model, selected_model=role_cfg.preferred_model,
                failure_category=(
                    "MODEL_NOT_FREE" if isinstance(e, ModelNotFreeError) else "MODEL_CAPABILITY_UNSUPPORTED"
                ),
            ))
            # Re-raises the ORIGINAL ModelNotFreeError/ModelCapabilityError
            # unchanged -- tests/test_dry_run_remediation.py asserts _call_llm
            # itself raises these exact types (its documented low-level
            # contract). Every caller in run_dry_run_cycle below must catch
            # BOTH these types alongside LLMUnavailableError -- see the
            # `_PREFLIGHT_REJECTIONS` tuple and its use at each of the 4 call
            # sites. Bug found via tests/test_dry_run_pipeline.py::
            # TestStructuredOutputWiring::test_capability_gate_blocks_before_
            # network_when_wired: before this fix, run_dry_run_cycle's `except
            # LLMUnavailableError` handlers did not catch these (both
            # ValueError subclasses, not LLMUnavailableError), so a pre-flight
            # rejection propagated uncaught out of the whole pipeline.
            raise

    violations = check_payload_safe(prompt)
    if violations:
        raise ValidationError(f"privacy_guard flagged outgoing prompt for step {step!r}: {violations}")

    dry_run_budget.check()
    router.usage_tracker.check_budget()
    if run_budget is not None:
        run_budget.check()

    call_kwargs: dict = {}
    if role_cfg.max_tokens is not None:
        call_kwargs["max_tokens"] = role_cfg.max_tokens
    if role_cfg.timeout is not None:
        call_kwargs["timeout_sec"] = role_cfg.timeout
    if response_format is not None:
        # Native OpenRouter structured-output request (section 3) -- an
        # ADDITIONAL field on the SAME single request, never a second
        # attempt. Flows straight through OpenRouterProvider.complete()'s
        # existing `body.update(kwargs)`.
        call_kwargs["response_format"] = response_format
        # Phase H token/reasoning audit finding (DRYRUN-0005): OmniLab
        # previously sent NO reasoning-control parameter at all, and
        # OpenRouter's documented reasoning-tokens mechanism
        # (https://openrouter.ai/docs/use-cases/reasoning-tokens) confirms
        # reasoning tokens count against the same completion-token budget
        # and CAN consume it entirely, producing exactly DRYRUN-0005's
        # observed shape (finish_reason="length", empty content) if a model
        # reasons by default. A JSON-schema structured-output answer has no
        # use for a separate reasoning trace anyway, so disabling it via
        # OpenRouter's documented `reasoning.enabled` field is safe and
        # targeted for every structured-output call, not just this one
        # model -- named parameter taken directly from OpenRouter's own
        # docs, not guessed.
        call_kwargs["reasoning"] = {"enabled": False}

    try:
        response = router.provider.complete(
            prompt,
            role,
            model=role_cfg.preferred_model,
            authorized=authorized,
            messages=[{"role": "user", "content": prompt}],
            max_retries=max_retries,
            **call_kwargs,
        )
    except LLMUnavailableError as e:
        router.usage_tracker.record_call()
        if run_budget is not None:
            run_budget.record()
        dry_run_budget.record()
        diag = getattr(e, "diagnostics", None) or {}
        call_records.append(CallRecord(
            # Bug found during the Phase H token/reasoning audit (DRYRUN-0005):
            # `diag.get("usage")`/`diag.get("model_used")` were never read
            # here even after research/llm/openrouter.py started capturing
            # them before the empty-content raise -- meaning a failed call's
            # CallRecord always showed token_usage=None and
            # actual_model_returned=None regardless of what OpenRouter
            # actually reported. Both are now threaded through.
            step=step, role=role, model_used=diag.get("model_used"), succeeded=False, error=str(e),
            timestamp=timestamp, dryrun_id=dryrun_id,
            requested_model=role_cfg.preferred_model, selected_model=role_cfg.preferred_model,
            actual_model_returned=diag.get("model_used"),
            http_status=diag.get("http_status"),
            provider_error_code=diag.get("provider_error_code"),
            provider_error_message=diag.get("provider_error_message"),
            request_id=diag.get("request_id"),
            finish_reason=diag.get("finish_reason"),
            envelope_parsed=diag.get("envelope_parsed"),
            choices_present=diag.get("choices_present"),
            message_present=diag.get("message_present"),
            content_present=diag.get("content_present"),
            content_length=diag.get("content_length"),
            token_usage=diag.get("usage"),
            structured_parse_result=_classify_transport_failure(e),
            failure_category=_classify_transport_failure(e),
        ))
        raise
    else:
        router.usage_tracker.record_call()
        if run_budget is not None:
            run_budget.record()
        dry_run_budget.record()
        diag = response.diagnostics or {}
        call_records.append(CallRecord(
            step=step, role=role, model_used=response.model_used, succeeded=True,
            timestamp=timestamp, dryrun_id=dryrun_id,
            requested_model=role_cfg.preferred_model, selected_model=role_cfg.preferred_model,
            actual_model_returned=response.model_used,
            http_status=diag.get("http_status"),
            request_id=response.request_id,
            latency_ms=response.latency_ms,
            finish_reason=diag.get("finish_reason"),
            envelope_parsed=diag.get("envelope_parsed"),
            choices_present=diag.get("choices_present"),
            message_present=diag.get("message_present"),
            content_present=diag.get("content_present"),
            content_length=diag.get("content_length"),
            token_usage=diag.get("usage"),
        ))
        return response


def run_dry_run_cycle(
    *,
    router: LLMRouter,
    authorized: AuthorizationLike,
    run_budget: Optional[RunBudget] = None,
    dry_run_budget: Optional[DryRunCallBudget] = None,
    baseline_run_id: str = CANONICAL_BASELINE_RUN_ID,
    model_catalog: Optional[dict] = None,
    require_structured_output: bool = False,
) -> DryRunResult:
    """Run one full dry-run cycle. Never writes to research/db.py, never
    creates a git branch, never queues anything. Returns a DryRunResult for
    the caller to render into a report (see `render_report`) and persist
    (see `write_artifacts`).

    `model_catalog`/`require_structured_output` (remediation-build wiring,
    optional, default off — a caller that omits them gets the exact
    pre-remediation prompt-and-hope behavior, unchanged): when both are
    provided, every researcher/revision call requests OpenRouter's native
    structured output using `proposal_response_json_schema()`, and the
    reviewer call uses `reviewer_critique_json_schema()` — via
    `_call_llm`'s existing `model_catalog`/`require_structured_output`/
    `response_format` parameters (research/llm/model_catalog.py's
    pre-flight capability/free-pricing gate + research/llm/
    structured_output.py's schema builders, both already implemented and
    tested; this is the wiring between them and the orchestration loop that
    was still missing after that build)."""
    from research.llm.structured_output import build_response_format, proposal_response_json_schema, reviewer_critique_json_schema

    proposal_response_format = (
        build_response_format(proposal_response_json_schema(), "proposal_response")
        if require_structured_output else None
    )
    reviewer_response_format = (
        build_response_format(reviewer_critique_json_schema(), "reviewer_critique")
        if require_structured_output else None
    )

    dry_run_budget = dry_run_budget or DryRunCallBudget(max_calls=3)
    call_records: list = []

    dryrun_id = _next_dryrun_id()
    placeholder_id = _placeholder_experiment_id(dryrun_id)

    # -- Step 1/2: memory context first, no LLM call (section 2). ----------
    memory_db = MemoryDB()
    try:
        context_packet = generate_context_packet(memory_db)
    finally:
        memory_db.close()

    result = DryRunResult(
        dryrun_id=dryrun_id,
        placeholder_experiment_id=placeholder_id,
        context_packet=context_packet,
        call_records=call_records,
        calls_budget=dry_run_budget.max_calls,
    )

    system_policy = _system_policy_text()
    researcher_template = _load_prompt_template("researcher_proposal.md")
    reviewer_template = _load_prompt_template("reviewer_critique.md")
    context_json = json.dumps(context_packet, indent=2, default=str)

    def render_researcher_prompt(extra: str = "") -> str:
        return researcher_template.format(system_policy=system_policy, context_packet_json=context_json) + extra

    # -- Step 3 (part of the researcher call): the LLM proposes. -----------
    try:
        response = _call_llm(
            router, _ROLE_RESEARCHER, render_researcher_prompt(),
            authorized=authorized, run_budget=run_budget, dry_run_budget=dry_run_budget,
            step="initial_proposal", call_records=call_records, dryrun_id=dryrun_id,
            model_catalog=model_catalog, require_structured_output=require_structured_output,
            response_format=proposal_response_format,
        )
    except _CALL_UNAVAILABLE as e:
        result.stopped_reason = f"researcher role unavailable: {e}"
        result.calls_made = dry_run_budget.calls_made
        return result

    flags = flag_suspicious_response(response.text)
    try:
        proposal_response = parse_and_validate_proposal(response.text)
    except ValidationError as e:
        _annotate_last_call_record(
            call_records, "initial_proposal",
            structured_parse_result=_classify_parse_failure(e),
            failure_category=_classify_parse_failure(e),
        )
        result.stopped_reason = f"initial proposal response failed structured-output validation: {e}"
        result.calls_made = dry_run_budget.calls_made
        return result
    result.raw_proposal_response = proposal_response

    proposal = _build_proposal(proposal_response, placeholder_id, baseline_run_id)

    # -- Step 3 continued: deterministic redundancy check (section 3). -----
    from research.db import OmniLabDB

    db = OmniLabDB()
    memory_db = MemoryDB()
    try:
        conflicts = find_rejected_hypothesis_conflicts(proposal, memory_db)
    finally:
        db.close()
        memory_db.close()
    result.redundancy_conflicts = conflicts

    acknowledged = set(proposal.acknowledges_rejected_hypothesis_ids)
    unacknowledged = [
        (eid, mid) for (eid, mid) in conflicts
        if eid not in acknowledged and mid not in acknowledged
    ] or (
        [(eid, mid) for (eid, mid) in conflicts if not proposal.materially_new_rationale.strip()]
        if conflicts else []
    )

    if unacknowledged:
        result.redundancy_rejected_initial = True
        conflict_desc = ", ".join(f"{eid}/{mid}" for eid, mid in unacknowledged)
        if dry_run_budget.remaining() > 0:
            retry_prompt = render_researcher_prompt(
                REDUNDANCY_RETRY_INSTRUCTIONS.format(conflicts=conflict_desc)
            )
            try:
                response = _call_llm(
                    router, _ROLE_RESEARCHER, retry_prompt,
                    authorized=authorized, run_budget=run_budget, dry_run_budget=dry_run_budget,
                    step="redundancy_retry_proposal", call_records=call_records, dryrun_id=dryrun_id,
                    model_catalog=model_catalog, require_structured_output=require_structured_output,
                    response_format=proposal_response_format,
                )
                proposal_response = parse_and_validate_proposal(response.text)
                result.raw_proposal_response = proposal_response
                proposal = _build_proposal(proposal_response, placeholder_id, baseline_run_id)
            except ValidationError as e:
                _annotate_last_call_record(
                    call_records, "redundancy_retry_proposal",
                    structured_parse_result=_classify_parse_failure(e),
                    failure_category=_classify_parse_failure(e),
                )
                result.stopped_reason = (
                    f"initial proposal rejected by deterministic redundancy check "
                    f"({conflict_desc}); retry failed: {e}"
                )
                result.proposal = proposal
                result.calls_made = dry_run_budget.calls_made
                return result
            except _CALL_UNAVAILABLE as e:
                result.stopped_reason = (
                    f"initial proposal rejected by deterministic redundancy check "
                    f"({conflict_desc}); retry failed: {e}"
                )
                result.proposal = proposal
                result.calls_made = dry_run_budget.calls_made
                return result

            # Re-check after retry — do NOT silently accept a still-redundant retry.
            memory_db = MemoryDB()
            try:
                conflicts_after = find_rejected_hypothesis_conflicts(proposal, memory_db)
            finally:
                memory_db.close()
            acknowledged = set(proposal.acknowledges_rejected_hypothesis_ids)
            still_unacknowledged = [
                (eid, mid) for (eid, mid) in conflicts_after
                if eid not in acknowledged and mid not in acknowledged
            ]
            if still_unacknowledged or (conflicts_after and not proposal.materially_new_rationale.strip()):
                result.stopped_reason = (
                    "initial proposal rejected by deterministic redundancy check "
                    f"({conflict_desc}); one bounded retry still did not resolve it — "
                    "surfacing as rejected rather than proceeding as if it were novel."
                )
                result.proposal = proposal
                result.redundancy_conflicts = conflicts_after
                result.calls_made = dry_run_budget.calls_made
                return result
        else:
            result.stopped_reason = (
                f"initial proposal rejected by deterministic redundancy check ({conflict_desc}); "
                "no call budget remaining for a retry — surfacing as rejected."
            )
            result.proposal = proposal
            result.calls_made = dry_run_budget.calls_made
            return result

    result.proposal = proposal

    # -- Step 5/6: local schema validation (never authoritative-by-LLM). --
    spec = ExperimentSpec(proposal=proposal)
    result.proposal_validation = validate(spec)
    _validation_step = "redundancy_retry_proposal" if result.redundancy_rejected_initial else "initial_proposal"
    _annotate_last_call_record(
        call_records, _validation_step,
        local_schema_validation_result={
            "is_valid": result.proposal_validation.is_valid,
            "error_count": len(result.proposal_validation.errors),
        },
        **(
            {"failure_category": FAILURE_LOCAL_VALIDATOR_REJECTION}
            if not result.proposal_validation.is_valid
            else {}
        ),
    )

    # -- Step 7: reviewer call. ---------------------------------------------
    if dry_run_budget.remaining() <= 0:
        result.final_validation = result.proposal_validation
        result.stopped_reason = "call budget exhausted before the reviewer step could run."
        result.calls_made = dry_run_budget.calls_made
        return result

    proposal_json = json.dumps(proposal.to_dict(), indent=2, default=str)
    reviewer_prompt = reviewer_template.format(
        system_policy=system_policy, proposal_json=proposal_json, context_packet_json=context_json
    )
    try:
        response = _call_llm(
            router, _ROLE_REVIEWER, reviewer_prompt,
            authorized=authorized, run_budget=run_budget, dry_run_budget=dry_run_budget,
            step="reviewer_critique", call_records=call_records, dryrun_id=dryrun_id,
            model_catalog=model_catalog, require_structured_output=require_structured_output,
            response_format=reviewer_response_format,
        )
        critique = parse_and_validate_reviewer_critique(response.text)
    except ValidationError as e:
        _annotate_last_call_record(
            call_records, "reviewer_critique",
            structured_parse_result=_classify_parse_failure(e),
            failure_category=_classify_parse_failure(e),
        )
        result.final_validation = result.proposal_validation
        result.stopped_reason = f"reviewer step failed: {e}"
        result.calls_made = dry_run_budget.calls_made
        return result
    except _CALL_UNAVAILABLE as e:
        result.final_validation = result.proposal_validation
        result.stopped_reason = f"reviewer step failed: {e}"
        result.calls_made = dry_run_budget.calls_made
        return result

    result.reviewer_critique = critique

    # -- Step 8: bounded revision loop — at most one more call, and ONLY if
    #    the reviewer actually asked for one (section 8's "don't call
    #    unnecessarily" requirement). --------------------------------------
    if critique.recommends_revision and dry_run_budget.remaining() > 0:
        revision_prompt = render_researcher_prompt(
            "\n\n## Reviewer requested a revision\n\n"
            f"Reviewer notes: {critique.revision_notes}\n\n"
            "Produce a revised proposal (same required JSON schema) addressing this feedback."
        )
        try:
            response = _call_llm(
                router, _ROLE_RESEARCHER, revision_prompt,
                authorized=authorized, run_budget=run_budget, dry_run_budget=dry_run_budget,
                step="revision", call_records=call_records, dryrun_id=dryrun_id,
                model_catalog=model_catalog, require_structured_output=require_structured_output,
                response_format=proposal_response_format,
            )
            revised_response = parse_and_validate_proposal(response.text)
            revised_proposal = _build_proposal(revised_response, placeholder_id, baseline_run_id)
            result.raw_proposal_response = revised_response
            result.proposal = revised_proposal
            result.revised = True
            result.revision_reason = critique.revision_notes
            spec = ExperimentSpec(proposal=revised_proposal)
            result.proposal_validation = validate(spec)
            _annotate_last_call_record(
                call_records, "revision",
                local_schema_validation_result={
                    "is_valid": result.proposal_validation.is_valid,
                    "error_count": len(result.proposal_validation.errors),
                },
                **(
                    {"failure_category": FAILURE_LOCAL_VALIDATOR_REJECTION}
                    if not result.proposal_validation.is_valid
                    else {}
                ),
            )
        except ValidationError as e:
            _annotate_last_call_record(
                call_records, "revision",
                structured_parse_result=_classify_parse_failure(e),
                failure_category=_classify_parse_failure(e),
            )
            result.stopped_reason = f"revision call failed, reporting pre-revision proposal: {e}"
        except _CALL_UNAVAILABLE as e:
            result.stopped_reason = f"revision call failed, reporting pre-revision proposal: {e}"

    result.final_validation = result.proposal_validation
    result.calls_made = dry_run_budget.calls_made
    return result


def _build_proposal(pr: ProposalResponse, experiment_id: str, baseline_run_id: str) -> ExperimentProposal:
    """Construct an ExperimentProposal from LLM-authored content. Every one
    of Phase F's 7 human-authority approval flags is hard-coded False here —
    ProposalResponse has no field for any of them, so this is not merely a
    default, it's the only value that can ever reach this call site."""
    return ExperimentProposal(
        schema_version="1.0",
        experiment_id=experiment_id,
        title=pr.title,
        family=pr.family,
        hypothesis=pr.hypothesis,
        motivation=pr.motivation,
        research_question=pr.research_question,
        evidence_references=tuple(pr.evidence_references),
        prior_experiment_ids=tuple(pr.prior_experiment_ids),
        baseline_run_id=baseline_run_id,
        independent_variables=tuple(pr.independent_variables),
        dependent_variables=tuple(pr.dependent_variables),
        controlled_variables=dict(pr.controlled_variables),
        procedure=pr.procedure,
        control_condition=pr.control_condition,
        baseline_comparison=pr.baseline_comparison,
        success_criteria=dict(pr.success_criteria),
        production_impact=pr.production_impact,
        production_impact_description=pr.production_impact_description,
        data_privacy_classification=pr.data_privacy_classification,
        external_api_required=pr.external_api_required,
        mac_iphone_required=pr.mac_iphone_required,
        supports_hypothesis_if=pr.supports_hypothesis_if,
        rejects_hypothesis_if=pr.rejects_hypothesis_if,
        inconclusive_if=pr.inconclusive_if,
        # -- Hard-coded False, always — never derived from LLM output. --
        production_swift_modification_approved=False,
        coreml_model_replacement_approved=False,
        new_training_approved=False,
        private_user_data_use_approved=False,
        external_upload_approved=False,
        mac_iphone_deployment_approved=False,
        signing_distribution_change_approved=False,
        acknowledges_rejected_hypothesis_ids=tuple(pr.acknowledges_rejected_hypothesis_ids),
        materially_new_rationale=pr.materially_new_rationale,
    )


# ---------------------------------------------------------------------------
# Artifacts — NEW artifact type, structurally distinct from a real queued
# experiment (never under experiments/, never a research/db.py row).
# ---------------------------------------------------------------------------


def write_artifacts(result: DryRunResult) -> tuple[Path, Path]:
    """Write the JSON proposal artifact and the markdown report. Neither
    path is under experiments/ and neither operation touches research/db.py.
    Returns (json_path, report_path)."""
    DRY_RUN_PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    DRY_RUN_REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    json_path = DRY_RUN_PROPOSALS_DIR / f"{result.dryrun_id}.json"
    json_path.write_text(json.dumps(_result_to_dict(result), indent=2, sort_keys=True, default=str), encoding="utf-8")

    # Include dryrun_id, not just a minute-resolution timestamp: two runs in
    # the same clock-minute (a real occurrence during the Phase H completion
    # retry -- DRYRUN-0003 and DRYRUN-0004 both landed at 2026-09-05 16:06)
    # would otherwise collide on filename and silently overwrite each
    # other's report, defeating the requirement that every dry-run attempt
    # -- including failed ones -- stay historically inspectable.
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M")
    report_path = DRY_RUN_REPORTS_DIR / f"{ts}-{result.dryrun_id}.md"
    report_path.write_text(render_report(result), encoding="utf-8")
    return json_path, report_path


def _result_to_dict(result: DryRunResult) -> dict:
    return {
        "dryrun_id": result.dryrun_id,
        "placeholder_experiment_id": result.placeholder_experiment_id,
        "generated_at": _now_utc_str(),
        "artifact_type": "DRY_RUN_PROPOSAL",
        "actually_queued": False,
        "call_records": [vars(c) for c in result.call_records],
        "calls_made": result.calls_made,
        "calls_budget": result.calls_budget,
        "redundancy_conflicts": result.redundancy_conflicts,
        "redundancy_rejected_initial": result.redundancy_rejected_initial,
        "proposal": result.proposal.to_dict() if result.proposal else None,
        "proposal_validation": _validation_to_dict(result.proposal_validation),
        "reviewer_critique": vars(result.reviewer_critique) if result.reviewer_critique else None,
        "revised": result.revised,
        "revision_reason": result.revision_reason,
        "final_validation": _validation_to_dict(result.final_validation),
        "queue_eligible_in_principle": (
            is_queue_eligible(result.final_validation) if result.final_validation is not None else False
        ),
        "stopped_reason": result.stopped_reason,
    }


def _validation_to_dict(v: Optional[ValidationResult]) -> Optional[dict]:
    if v is None:
        return None
    return {
        "errors": [vars(i) for i in v.errors],
        "warnings": [vars(i) for i in v.warnings],
        "needs_human_review": [vars(i) for i in v.needs_human_review],
        "is_valid": v.is_valid,
    }


def render_report(result: DryRunResult) -> str:
    lines: list[str] = []
    lines.append(f"# Dry-Run Research Proposal — {result.dryrun_id}")
    lines.append("")
    lines.append("**DRY RUN ONLY — NOT EXECUTED**")
    lines.append("")
    lines.append(f"Generated: {_now_utc_str()}")
    lines.append(f"Placeholder experiment id (never persisted to research/db.py): `{result.placeholder_experiment_id}`")
    lines.append(f"External LLM calls made: {result.calls_made} / {result.calls_budget}")
    lines.append("")

    if result.stopped_reason:
        lines.append("## Pipeline stopped early")
        lines.append("")
        lines.append(result.stopped_reason)
        lines.append("")

    lines.append("## Redundant/rejected directions explicitly considered")
    lines.append("")
    if result.redundancy_conflicts:
        for eid, mid in result.redundancy_conflicts:
            lines.append(f"- Matches rejected hypothesis `{mid}` (experiment `{eid}`).")
        if result.redundancy_rejected_initial:
            lines.append("- The initial proposal was rejected by the deterministic redundancy "
                          "check for the reason above before being sent to the reviewer.")
    else:
        lines.append("- No overlap detected with any REJECTED_HYPOTHESIS record's family + "
                      "independent variables (deterministic keyword/family match).")
    lines.append("")

    p = result.proposal
    if p is not None:
        lines.append("## Selected problem")
        lines.append("")
        if result.raw_proposal_response:
            lines.append(f"**Problem**: {result.raw_proposal_response.selected_problem}")
            lines.append("")
            lines.append(f"**Rationale**: {result.raw_proposal_response.selection_rationale}")
            lines.append("")

        lines.append("## Hypothesis")
        lines.append("")
        lines.append(p.hypothesis)
        lines.append("")

        lines.append("## Experiment design")
        lines.append("")
        lines.append(f"- Family: `{p.family}`")
        lines.append(f"- Research question: {p.research_question}")
        lines.append(f"- Motivation: {p.motivation}")
        lines.append(f"- Independent variables: {list(p.independent_variables)}")
        lines.append(f"- Dependent variables: {list(p.dependent_variables)}")
        lines.append(f"- Control condition: {p.control_condition}")
        lines.append(f"- Baseline comparison: {p.baseline_comparison}")
        lines.append(f"- Baseline run id: `{p.baseline_run_id}`")
        lines.append(f"- Success criteria: {p.success_criteria}")
        lines.append(f"- supports_hypothesis_if: {p.supports_hypothesis_if}")
        lines.append(f"- rejects_hypothesis_if: {p.rejects_hypothesis_if}")
        lines.append(f"- inconclusive_if: {p.inconclusive_if}")
        lines.append(f"- acknowledges_rejected_hypothesis_ids: {list(p.acknowledges_rejected_hypothesis_ids)}")
        lines.append(f"- materially_new_rationale: {p.materially_new_rationale or '(none)'}")
        lines.append("")

    if result.reviewer_critique is not None:
        c = result.reviewer_critique
        lines.append("## Reviewer critique")
        lines.append("")
        lines.append(f"- Novelty: {c.novelty_assessment}")
        lines.append(f"- Scientific validity: {c.scientific_validity_assessment}")
        lines.append(f"- Targets a verified failure mode: {c.targets_verified_failure_mode}")
        lines.append(f"- Success criteria deterministic: {c.success_criteria_deterministic}")
        lines.append(f"- Confounding notes: {c.confounding_notes}")
        lines.append(f"- Dataset can answer question: {c.dataset_can_answer_question}")
        lines.append(f"- Sample size adequate: {c.sample_size_adequate}")
        lines.append(f"- Leakage risk notes: {c.leakage_risk_notes}")
        lines.append(f"- Privacy/safety ok: {c.privacy_safety_ok}")
        lines.append(f"- Feasibility notes: {c.feasibility_notes}")
        lines.append(f"- Worth running (reviewer's opinion only — not authoritative): {c.worth_running}")
        lines.append(f"- Recommends revision: {c.recommends_revision}")
        lines.append(f"- Summary: {c.summary}")
        lines.append("")

    lines.append("## Revision")
    lines.append("")
    if result.revised:
        lines.append(f"Revised once. Reviewer's revision notes: {result.revision_reason}")
    else:
        lines.append("Not revised — the reviewer did not request a revision, or no call budget "
                      "remained (the pipeline never spends a 3rd call merely because budget allows).")
    lines.append("")

    lines.append("## Local, deterministic schema validation (authoritative — NOT the reviewer's opinion)")
    lines.append("")
    v = result.final_validation
    if v is not None:
        lines.append(f"- Schema-valid: {'YES' if v.is_valid else 'NO'}")
        lines.append(f"- Errors: {len(v.errors)}")
        for i in v.errors:
            lines.append(f"  - [{i.code}] {i.message}")
        lines.append(f"- Warnings: {len(v.warnings)}")
        for i in v.warnings:
            lines.append(f"  - [{i.code}] {i.message}")
        lines.append(f"- Needs human review: {len(v.needs_human_review)}")
        for i in v.needs_human_review:
            lines.append(f"  - [{i.code}] {i.message}")
        lines.append("")
        lines.append(f"**Queue-eligible in principle: {'YES' if is_queue_eligible(v) else 'NO'}**")
    else:
        lines.append("- Schema-valid: NO (pipeline stopped before validation could run)")
        lines.append("- Queue-eligible in principle: NO")
    lines.append("")
    lines.append("**Actually queued: NO** (this phase never calls "
                  "research/orchestrator.py::queue_experiment_from_spec or inserts any row into "
                  "research/omnilab.db — see tests/test_dry_run_safety.py)")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("**DRY RUN ONLY — NOT EXECUTED**")
    lines.append("")
    return "\n".join(lines)
