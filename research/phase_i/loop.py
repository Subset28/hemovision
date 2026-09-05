"""Phase I -- the proposal-only autonomous research cycle.

AUTHORITY BOUNDARY (read this before touching anything below): this module
NEVER queues an experiment, NEVER creates EXP-0006 or any EXP-XXXX row,
NEVER creates a git branch, NEVER trains, NEVER benchmarks, NEVER downloads
external data, NEVER touches ios/ or benchmark/config.py, and NEVER sets any
of Phase F's 7 human-authority approval flags to True. Its one and only
output is a FINALIZED/REJECTED/BLOCKED/FAILED candidate report under
research/candidates/<CANDIDATE-ID>/ -- "a scientifically reviewed candidate
proposal awaiting explicit human authorization", never anything more. A
candidate becoming an experiment is a SEPARATE, explicit, human-invoked step
that does not exist in this module at all.

Cycle: research memory -> researcher proposes ONE experiment (autonomously
selected, never hard-coded to any prior direction) -> deterministic
validation + redundancy check -> independent reviewer -> at most ONE bounded
revision if the reviewer says REVISE -> final candidate report -> STOP.

Reuses the EXACT canonical choke points Phase H already built and this
round's hardening pass already secured -- research/dry_run/pipeline.py's
`_call_llm` (operational-state gate, unconditional free-model preflight,
one-HTTP-request invariant, returned-model provenance check, structured-
output parsing) -- there is no second, competing LLM-calling code path here.
The only things this module adds are: (a) the CANDIDATE-NNNN artifact
namespace (research/candidates/, distinct from research/dry_run_proposals/
and structurally incapable of colliding with an EXP-XXXX id), and (b) the
crash/restart-safe state machine (research/phase_i/candidate_state.py).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from research.config import CANONICAL_BASELINE_RUN_ID
from research.dry_run.budget import DryRunCallBudget
from research.experiment_spec import ExperimentProposal, ExperimentSpec
from research.experiment_validator import (
    ValidationResult,
    find_rejected_hypothesis_conflicts,
    is_queue_eligible,
    validate,
)
from research.llm.authorization import AuthorizationLike
from research.llm.base import RunBudget
from research.llm.router import LLMRouter
from research.llm.structured_output import (
    ProposalResponse,
    ReviewerCritique,
    ValidationError,
    build_response_format,
    parse_and_validate_proposal,
    parse_and_validate_reviewer_critique,
    proposal_response_json_schema,
    reviewer_critique_json_schema,
)
from research.memory_context import generate_context_packet
from research.memory_db import MemoryDB
from research import operational_state
from research.phase_i import candidate_state as cs

# Reuse of Phase H's canonical, already-hardened choke point and helpers --
# no second LLM-calling code path. These are "private" (leading underscore)
# names in that module, imported here deliberately, the same way Phase H's
# own tests already do.
from research.dry_run.pipeline import (
    _CALL_UNAVAILABLE,
    _build_proposal,
    _call_llm,
    _load_prompt_template,
    _now_utc_str,
    _system_policy_text,
)

_ROLE_RESEARCHER = "researcher"
_ROLE_REVIEWER = "reviewer"

# ACCEPT/REVISE/REJECT is derived, not a new schema field -- ReviewerCritique
# already carries `worth_running`/`recommends_revision` (both booleans,
# Phase G/H's structured-output shape, unchanged here). Deterministic
# mapping, never an LLM's own label:
RECOMMENDATION_ACCEPT = "ACCEPT"
RECOMMENDATION_REVISE = "REVISE"
RECOMMENDATION_REJECT = "REJECT"


def _derive_recommendation(critique: ReviewerCritique) -> str:
    if critique.recommends_revision:
        return RECOMMENDATION_REVISE
    if critique.worth_running:
        return RECOMMENDATION_ACCEPT
    return RECOMMENDATION_REJECT


@dataclass
class PhaseICycleResult:
    candidate_id: str
    final_state: str
    call_records: list = field(default_factory=list)
    calls_made: int = 0
    calls_budget: int = 3
    proposal: Optional[ExperimentProposal] = None
    raw_proposal_response: Optional[ProposalResponse] = None
    reviewer_critique: Optional[ReviewerCritique] = None
    recommendation: str = ""
    revised: bool = False
    revised_proposal: Optional[ExperimentProposal] = None
    final_validation: Optional[ValidationResult] = None
    redundancy_conflicts: list = field(default_factory=list)
    stopped_reason: str = ""
    proposal_path: Optional[Path] = None
    review_path: Optional[Path] = None
    revision_path: Optional[Path] = None
    final_report_path: Optional[Path] = None


def _placeholder_experiment_id(candidate_id: str) -> str:
    """Structurally-valid (EXP-\\d{4}) but NEVER-persisted id for the
    ephemeral ExperimentProposal object -- same EXP-9xxx range Phase H uses,
    disjoint from research/db.py's real sequential allocation. Derived from
    the candidate number so it's stable across a restart."""
    n = int(candidate_id.split("-")[1])
    return f"EXP-9{n:03d}"


def _validation_to_dict(v: Optional[ValidationResult]) -> Optional[dict]:
    if v is None:
        return None
    return {
        "errors": [vars(i) for i in v.errors],
        "warnings": [vars(i) for i in v.warnings],
        "needs_human_review": [vars(i) for i in v.needs_human_review],
        "is_valid": v.is_valid,
    }


def _write_json_artifact(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return path


def run_phase_i_cycle(
    *,
    router: LLMRouter,
    authorized: AuthorizationLike,
    run_budget: Optional[RunBudget] = None,
    model_catalog: Optional[dict] = None,
    resume_candidate_id: Optional[str] = None,
    baseline_run_id: str = CANONICAL_BASELINE_RUN_ID,
) -> PhaseICycleResult:
    """Run (or resume) exactly one Phase I candidate cycle. Never creates a
    second candidate for the same call, never queues, never trains, never
    creates a branch. Structured output is always required here -- unlike
    Phase H's dry-run command, there is no "off by default" legacy mode to
    preserve.

    Restart safety: if `resume_candidate_id` is given, resumes from
    `candidate_state.resolve_resume_point()` -- an already-completed stage
    is never repeated, and an ambiguous persisted state raises
    CandidateStateError rather than guessing."""
    call_records: list = []

    if resume_candidate_id is not None:
        record, resume_stage = cs.resolve_resume_point(resume_candidate_id)
    else:
        record = cs.create_candidate()
        resume_stage = "researcher"

    dry_run_budget = DryRunCallBudget(max_calls=record.calls_budget)
    dry_run_budget.calls_made = record.calls_made  # restart-safe: preserve prior spend

    result = PhaseICycleResult(
        candidate_id=record.candidate_id, final_state=record.state,
        calls_budget=record.calls_budget, calls_made=record.calls_made,
    )

    def _finish(new_state: str, reason: str = "") -> PhaseICycleResult:
        cs.transition(record, new_state, reason=reason)
        result.final_state = new_state
        result.stopped_reason = reason
        result.calls_made = dry_run_budget.calls_made
        result.call_records = call_records
        return result

    placeholder_id = _placeholder_experiment_id(record.candidate_id)
    memory_db = MemoryDB()
    try:
        context_packet = generate_context_packet(memory_db)
    finally:
        memory_db.close()

    system_policy = _system_policy_text()
    researcher_template = _load_prompt_template("researcher_proposal.md")
    reviewer_template = _load_prompt_template("reviewer_critique.md")
    context_json = json.dumps(context_packet, indent=2, default=str)

    proposal_response_format = build_response_format(proposal_response_json_schema(), "proposal_response")
    reviewer_response_format = build_response_format(reviewer_critique_json_schema(), "reviewer_critique")

    proposal: Optional[ExperimentProposal] = None
    proposal_response: Optional[ProposalResponse] = None

    # -- Stage 1: researcher (autonomous problem selection). ----------------
    if resume_stage == "researcher":
        researcher_prompt = researcher_template.format(system_policy=system_policy, context_packet_json=context_json)
        try:
            response = _call_llm(
                router, _ROLE_RESEARCHER, researcher_prompt,
                authorized=authorized, run_budget=run_budget, dry_run_budget=dry_run_budget,
                step="phase_i_researcher", call_records=call_records, dryrun_id=record.candidate_id,
                model_catalog=model_catalog, require_structured_output=True,
                response_format=proposal_response_format,
            )
            proposal_response = parse_and_validate_proposal(response.text)
        except ValidationError as e:
            record.calls_made = dry_run_budget.calls_made
            cs.save(record)
            return _finish(cs.FAILED, f"researcher response failed structured-output validation: {e}")
        except operational_state.OperationalGateError as e:
            record.calls_made = dry_run_budget.calls_made
            cs.save(record)
            return _finish(cs.BLOCKED, f"operational gate blocked researcher call: {e}")
        except _CALL_UNAVAILABLE as e:
            record.calls_made = dry_run_budget.calls_made
            cs.save(record)
            return _finish(cs.FAILED, f"researcher call unavailable: {e}")

        proposal = _build_proposal(proposal_response, placeholder_id, baseline_run_id)
        proposal_path = cs._candidate_dir(record.candidate_id) / f"{record.candidate_id}-proposal.json"
        _write_json_artifact(proposal_path, {
            "candidate_id": record.candidate_id,
            "artifact_type": "PHASE_I_PROPOSAL",
            "generated_at": _now_utc_str(),
            "actually_queued": False,
            "call_records": [vars(c) for c in call_records],
            "proposal": proposal.to_dict(),
            "raw_selected_problem": proposal_response.selected_problem,
            "raw_selection_rationale": proposal_response.selection_rationale,
        })
        record.proposal_path = str(proposal_path)
        record.calls_made = dry_run_budget.calls_made
        cs.transition(record, cs.RESEARCHER_COMPLETED)
        result.proposal_path = proposal_path
        resume_stage = "validate"
    else:
        # Resuming past the researcher stage -- load the already-written
        # proposal artifact rather than re-calling.
        with open(record.proposal_path, encoding="utf-8") as f:
            saved = json.load(f)
        proposal = ExperimentProposal(**{
            k: v for k, v in saved["proposal"].items() if k in ExperimentProposal.__dataclass_fields__
        })
        result.proposal_path = Path(record.proposal_path)

    result.proposal = proposal
    result.raw_proposal_response = proposal_response

    # -- Stage 2: deterministic validation + redundancy (no LLM call). ------
    if resume_stage == "validate":
        spec = ExperimentSpec(proposal=proposal)
        proposal_validation = validate(spec)
        memory_db = MemoryDB()
        try:
            conflicts = find_rejected_hypothesis_conflicts(proposal, memory_db)
        finally:
            memory_db.close()
        result.redundancy_conflicts = conflicts

        acknowledged = set(proposal.acknowledges_rejected_hypothesis_ids)
        unacknowledged = [
            (eid, mid) for (eid, mid) in conflicts
            if eid not in acknowledged and mid not in acknowledged
        ]
        admissible = proposal_validation.is_valid and (
            not conflicts or (not unacknowledged and proposal.materially_new_rationale.strip())
        )
        if not admissible:
            result.final_validation = proposal_validation
            reason = (
                f"deterministic admission failed: is_valid={proposal_validation.is_valid}, "
                f"unacknowledged_redundancy_conflicts={unacknowledged}"
            )
            record.calls_made = dry_run_budget.calls_made
            cs.save(record)
            return _finish(cs.REJECTED, reason)

        cs.transition(record, cs.VALIDATED)
        resume_stage = "reviewer"

    # -- Stage 3: independent reviewer. -------------------------------------
    if resume_stage == "reviewer":
        proposal_json = json.dumps(proposal.to_dict(), indent=2, default=str)
        reviewer_prompt = reviewer_template.format(
            system_policy=system_policy, proposal_json=proposal_json, context_packet_json=context_json,
        )
        try:
            response = _call_llm(
                router, _ROLE_REVIEWER, reviewer_prompt,
                authorized=authorized, run_budget=run_budget, dry_run_budget=dry_run_budget,
                step="phase_i_reviewer", call_records=call_records, dryrun_id=record.candidate_id,
                model_catalog=model_catalog, require_structured_output=True,
                response_format=reviewer_response_format,
            )
            critique = parse_and_validate_reviewer_critique(response.text)
        except ValidationError as e:
            record.calls_made = dry_run_budget.calls_made
            cs.save(record)
            return _finish(cs.FAILED, f"reviewer response failed structured-output validation: {e}")
        except operational_state.OperationalGateError as e:
            record.calls_made = dry_run_budget.calls_made
            cs.save(record)
            return _finish(cs.BLOCKED, f"operational gate blocked reviewer call: {e}")
        except _CALL_UNAVAILABLE as e:
            record.calls_made = dry_run_budget.calls_made
            cs.save(record)
            return _finish(cs.FAILED, f"reviewer call unavailable: {e}")

        result.reviewer_critique = critique
        recommendation = _derive_recommendation(critique)
        result.recommendation = recommendation

        review_path = cs._candidate_dir(record.candidate_id) / f"{record.candidate_id}-review.json"
        _write_json_artifact(review_path, {
            "candidate_id": record.candidate_id,
            "artifact_type": "PHASE_I_REVIEW",
            "generated_at": _now_utc_str(),
            "actually_queued": False,
            "call_records": [vars(c) for c in call_records],
            "reviewer_critique": vars(critique),
            "recommendation": recommendation,
        })
        record.review_path = str(review_path)
        record.calls_made = dry_run_budget.calls_made
        cs.transition(record, cs.REVIEW_COMPLETED)
        result.review_path = review_path

        if recommendation == RECOMMENDATION_ACCEPT:
            result.final_validation = validate(ExperimentSpec(proposal=proposal))
            final_path = _write_final_report(record, result, proposal)
            result.final_report_path = final_path
            record.final_report_path = str(final_path)
            record.calls_made = dry_run_budget.calls_made
            cs.save(record)
            return _finish(cs.FINALIZED, "reviewer ACCEPT -- finalized without revision")

        if recommendation == RECOMMENDATION_REJECT:
            record.calls_made = dry_run_budget.calls_made
            cs.save(record)
            return _finish(cs.REJECTED, "reviewer REJECT -- terminated without a queueable candidate")

        resume_stage = "revision"
    elif record.state not in cs.TERMINAL_STATES and resume_stage == "revision":
        # Resuming directly into "revision" (reviewer already completed on a
        # prior run) -- load the persisted critique rather than re-calling.
        with open(record.review_path, encoding="utf-8") as f:
            saved_review = json.load(f)
        result.reviewer_critique = ReviewerCritique(**{
            k: v for k, v in saved_review["reviewer_critique"].items()
            if k in ReviewerCritique.__dataclass_fields__
        })
        result.recommendation = saved_review["recommendation"]

    # -- Stage 4: at most ONE bounded revision, only if reviewer said REVISE.
    if resume_stage == "revision" and record.state not in cs.TERMINAL_STATES:
        critique = result.reviewer_critique
        revision_prompt = researcher_template.format(system_policy=system_policy, context_packet_json=context_json) + (
            "\n\n## Revision request -- respond to an independent reviewer's critique\n\n"
            "Your prior proposal was independently reviewed. The reviewer recommended REVISE. "
            "Produce a revised proposal in the exact same required JSON schema, addressing the "
            "critique below. Do not merely reword the proposal while leaving the underlying "
            "confound intact -- either resolve it with a genuinely different design, or make the "
            "unresolved issue an explicit blocking prerequisite. Do not fabricate an answer to any "
            "fact that remains unknown.\n\n"
            f"### Your original proposal\n\n```json\n{json.dumps(proposal.to_dict(), indent=2, default=str)}\n```\n\n"
            f"### Independent reviewer critique\n\n```json\n{json.dumps(vars(critique), indent=2, default=str)}\n```\n"
        )
        try:
            response = _call_llm(
                router, _ROLE_RESEARCHER, revision_prompt,
                authorized=authorized, run_budget=run_budget, dry_run_budget=dry_run_budget,
                step="phase_i_revision", call_records=call_records, dryrun_id=record.candidate_id, max_retries=0,
                model_catalog=model_catalog, require_structured_output=True,
                response_format=proposal_response_format,
            )
            revised_response = parse_and_validate_proposal(response.text)
        except ValidationError as e:
            record.calls_made = dry_run_budget.calls_made
            cs.save(record)
            return _finish(cs.FAILED, f"revision response failed structured-output validation: {e}")
        except operational_state.OperationalGateError as e:
            record.calls_made = dry_run_budget.calls_made
            cs.save(record)
            return _finish(cs.BLOCKED, f"operational gate blocked revision call: {e}")
        except _CALL_UNAVAILABLE as e:
            record.calls_made = dry_run_budget.calls_made
            cs.save(record)
            return _finish(cs.FAILED, f"revision call unavailable: {e}")

        revised_proposal = _build_proposal(revised_response, placeholder_id, baseline_run_id)
        result.revised = True
        result.revised_proposal = revised_proposal
        result.raw_proposal_response = revised_response

        revised_validation = validate(ExperimentSpec(proposal=revised_proposal))
        memory_db = MemoryDB()
        try:
            revised_conflicts = find_rejected_hypothesis_conflicts(revised_proposal, memory_db)
        finally:
            memory_db.close()
        result.final_validation = revised_validation
        result.redundancy_conflicts = revised_conflicts

        revision_path = cs._candidate_dir(record.candidate_id) / f"{record.candidate_id}-revision.json"
        _write_json_artifact(revision_path, {
            "candidate_id": record.candidate_id,
            "artifact_type": "PHASE_I_REVISION",
            "generated_at": _now_utc_str(),
            "actually_queued": False,
            "call_records": [vars(c) for c in call_records],
            "revised_proposal": revised_proposal.to_dict(),
            "final_validation": _validation_to_dict(revised_validation),
            "redundancy_conflicts": revised_conflicts,
            "reviewer_issue_reconciliation": _reconcile(critique, revised_proposal),
        })
        record.revision_path = str(revision_path)
        record.calls_made = dry_run_budget.calls_made
        cs.transition(record, cs.REVISION_COMPLETED)
        result.revision_path = revision_path

        final_path = _write_final_report(record, result, revised_proposal)
        result.final_report_path = final_path
        record.final_report_path = str(final_path)
        record.calls_made = dry_run_budget.calls_made
        cs.save(record)
        return _finish(cs.FINALIZED, "reviewer REVISE -- revision completed, finalized")

    result.call_records = call_records
    result.calls_made = dry_run_budget.calls_made
    result.final_state = record.state
    return result


def _reconcile(critique: ReviewerCritique, revised_proposal: ExperimentProposal) -> dict:
    """Deterministic (NOT LLM-judged) reconciliation of the revision against
    the reviewer's material criticisms -- text-presence heuristics only,
    always reported as a starting point for human judgment, never as a
    substitute for it."""
    provenance_addressed = "provenance" in (revised_proposal.baseline_comparison or "").lower() or \
        "prerequisite" in (revised_proposal.model_config_ref or "").lower()
    return {
        "leakage_risk_notes_from_reviewer": critique.leakage_risk_notes,
        "isolation_requirements_now_populated": bool(revised_proposal.isolation_requirements.strip()),
        "provenance_language_present_in_revision": provenance_addressed,
        "note": "Deterministic text-presence heuristic only -- final judgment on whether "
                "reviewer issues are RESOLVED/PARTIALLY_RESOLVED/UNRESOLVED remains a human "
                "review responsibility, never automated.",
    }


def _write_final_report(record: "cs.CandidateRecord", result: PhaseICycleResult, final_proposal: ExperimentProposal) -> Path:
    """Write the terminal candidate synthesis -- a NEW, separate artifact,
    never overwriting the proposal/review/revision files it summarizes."""
    path = cs._candidate_dir(record.candidate_id) / f"{record.candidate_id}-final.json"
    data = {
        "candidate_id": record.candidate_id,
        "artifact_type": "PHASE_I_FINAL_CANDIDATE",
        "generated_at": _now_utc_str(),
        "actually_queued": False,
        "actually_registered_as_experiment": False,
        "recommendation": result.recommendation,
        "revised": result.revised,
        "final_proposal": final_proposal.to_dict(),
        "final_validation": _validation_to_dict(result.final_validation),
        "queue_eligible_in_principle": (
            is_queue_eligible(result.final_validation) if result.final_validation is not None else False
        ),
        "redundancy_conflicts": result.redundancy_conflicts,
        "calls_made": result.calls_made,
        "calls_budget": result.calls_budget,
        "human_approvals_required": [
            "new_training_approved", "production_swift_modification_approved",
            "coreml_model_replacement_approved", "external_upload_approved",
            "private_user_data_use_approved", "mac_iphone_deployment_approved",
            "signing_distribution_change_approved",
        ],
        "note": "This is a candidate report only. It has NOT been registered as an experiment, "
                "NOT queued, NOT executed. Registration as EXP-0006 (or any EXP-XXXX) requires a "
                "separate, explicit human decision outside this module.",
    }
    return _write_json_artifact(path, data)
