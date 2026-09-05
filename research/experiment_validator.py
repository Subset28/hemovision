"""Phase F — deterministic validation and queue-eligibility gate for
ExperimentProposal/ExperimentSpec objects (research/experiment_spec.py).

No LLM call anywhere in this module, ever. Every check here is a plain
Python function over structured data and on-disk/DB artifacts.

`validate(spec)` returns a `ValidationResult` (a LIST of issues, not a bare
bool) — every issue is tagged ERROR / WARNING / NEEDS_HUMAN_REVIEW. Anything
this module cannot mechanically check is emitted as an explicit
NEEDS_HUMAN_REVIEW issue naming what it could not check — never silently
treated as passing.

`is_queue_eligible(result)` is the single gate: True iff there are zero
ERROR-level issues. Warnings/NEEDS_HUMAN_REVIEW may still block a human
reviewer's judgment call, but they do not block the mechanical gate itself.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from research.config import REPO_ROOT
from research.experiment_registry import REGISTRY
from research.experiment_spec import EXPERIMENT_ID_RE, ExperimentProposal, ExperimentSpec

# ---------------------------------------------------------------------------
# Known metric vocabulary — reused/extended from what
# research/evaluation_policy.py's default_hazard_policy() and the historical
# EXP-0001..0005 results.json files actually reference. evaluation_policy.py
# has no single enumerated vocabulary object of its own (it validates dotted
# paths structurally, not against a fixed list), so this list is built
# directly from its concrete usage (primary_metric="person.recall",
# guardrails on "hazard.precision"/"hazard.recall"/"latency.p95_ms",
# sample_size_floors on "stairs"/"truck"/"bus"/"motorcycle") plus the full
# 8-class hazard vocabulary documented in research/README.md
# ("person, car, truck, bus, bicycle, motorcycle, stairs, dog").
# ---------------------------------------------------------------------------

KNOWN_METRIC_GROUPS = (
    "hazard", "person", "car", "truck", "bus", "bicycle", "motorcycle", "stairs", "dog", "latency",
)
KNOWN_METRIC_SUFFIXES = ("precision", "recall", "num_gt", "p50_ms", "p95_ms", "p99_ms", "mean_ms")


def is_known_metric(dotted: str) -> bool:
    parts = dotted.split(".")
    if len(parts) != 2:
        return False
    group, suffix = parts
    return group in KNOWN_METRIC_GROUPS and suffix in KNOWN_METRIC_SUFFIXES


# ---------------------------------------------------------------------------
# Semantic-completeness: placeholder-garbage rejection (Phase H schema-
# mapping fix, post-DRYRUN-0007-revision audit). A proposal must not become
# queue-eligible merely because every field contains SOME string — a bare
# "TBD"/"unknown"/"N/A" carries zero information a human or future
# automation could act on, and is structurally different from a real,
# explicit prerequisite/limitation sentence (e.g. "provenance is UNKNOWN —
# blocking prerequisite: ..."), which IS legitimate and must never be
# rejected. This is an EXACT-MATCH check on the stripped/lowercased whole
# field value, deliberately not a substring scan — a real sentence that
# happens to contain the word "unknown" mid-sentence is not a placeholder.
# ---------------------------------------------------------------------------

_PLACEHOLDER_VALUES = frozenset({
    "tbd", "to be determined", "n/a", "na", "unknown", "none", "...", "todo",
    "placeholder", "tba", "pending",
})


def _is_placeholder(text: str) -> bool:
    return text.strip().lower() in _PLACEHOLDER_VALUES


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------

# "ERROR" | "WARNING" | "NEEDS_HUMAN_REVIEW" | "NEEDS_HUMAN_APPROVAL"
#
# NEEDS_HUMAN_APPROVAL (Phase-I CANDIDATE-0001-postmortem addition, see
# reports/phase_i/CANDIDATE_0001_POSTMORTEM.md) is DELIBERATELY DISTINCT
# from ERROR. It answers a different question:
#   ERROR                = the proposal is structurally/scientifically
#                           invalid (missing hypothesis, unknown family,
#                           contradictory success criteria, ...).
#   NEEDS_HUMAN_APPROVAL  = the proposal is scientifically fine but
#                           DESCRIBES an operation (production Swift change,
#                           Mac/iPhone deployment, private-data use, external
#                           API/data acquisition, new training) that requires
#                           an explicit human-authority approval flag which
#                           is not yet granted. This is never conflated with
#                           "the proposal is malformed" -- a scientifically
#                           valid proposal MUST be allowed to say "this needs
#                           future human approval" without that fact alone
#                           making the proposal invalid. See is_valid() vs.
#                           is_queue_eligible() below: is_valid() ignores
#                           NEEDS_HUMAN_APPROVAL entirely (so a reviewer can
#                           still assess an otherwise-sound design);
#                           is_queue_eligible() requires BOTH zero ERRORs AND
#                           zero NEEDS_HUMAN_APPROVAL issues (so a missing
#                           approval still, and always, blocks the queue).
Level = str


@dataclass
class ValidationIssue:
    level: Level
    code: str
    message: str


@dataclass
class ValidationResult:
    issues: list = field(default_factory=list)  # list[ValidationIssue]

    def add(self, level: Level, code: str, message: str) -> None:
        self.issues.append(ValidationIssue(level=level, code=code, message=message))

    @property
    def errors(self) -> list:
        return [i for i in self.issues if i.level == "ERROR"]

    @property
    def warnings(self) -> list:
        return [i for i in self.issues if i.level == "WARNING"]

    @property
    def needs_human_review(self) -> list:
        return [i for i in self.issues if i.level == "NEEDS_HUMAN_REVIEW"]

    @property
    def needs_human_approval(self) -> list:
        return [i for i in self.issues if i.level == "NEEDS_HUMAN_APPROVAL"]

    @property
    def is_valid(self) -> bool:
        """Structural/scientific validity ONLY -- deliberately does NOT
        consider NEEDS_HUMAN_APPROVAL issues. A proposal that correctly
        describes a future need for human authorization (e.g.
        mac_iphone_required=True with the approval not yet granted) is
        still `is_valid=True`: it is a well-formed, reviewable proposal,
        just not yet queue-eligible. See is_queue_eligible()."""
        return len(self.errors) == 0

    def __bool__(self) -> bool:
        return self.is_valid


# ---------------------------------------------------------------------------
# Baseline resolution — must resolve to a real artifact, never a hand-typed
# number. Mirrors research/db.py::OmniLabDB.resolve_baseline_run_dir's logic
# but works for a not-yet-queued proposal (no Experiment row required).
# ---------------------------------------------------------------------------


def resolve_baseline_run_dir(baseline_run_id: str) -> Optional[Path]:
    candidates = [
        REPO_ROOT / "benchmark" / "results" / "baseline",
        REPO_ROOT / "benchmark" / "results" / "diagnostics",
    ]
    for c in candidates:
        meta = c / "run_metadata.json"
        if meta.exists():
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("run_id") == baseline_run_id:
                return c
    return None


# ---------------------------------------------------------------------------
# Rejected-hypothesis overlap (Phase F item #8) — pure deterministic
# family + keyword-overlap metadata matching. No semantic/LLM similarity.
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset({
    "a", "an", "the", "of", "to", "and", "or", "at", "in", "on", "for", "with",
    "alone", "only", "level", "time", "value", "single", "one", "simple",
})


def _keywords(text: str) -> set:
    tokens = re.split(r"[^a-z0-9]+", text.lower())
    return {t for t in tokens if t and t not in _STOPWORDS}


def find_rejected_hypothesis_conflicts(proposal: ExperimentProposal, memory_db) -> list:
    """Return a list of (experiment_id, memory_record_id) pairs for
    REJECTED_HYPOTHESIS memory records whose owning experiment shares
    `proposal.family` AND whose stored `independent_variable` text overlaps
    (by keyword) with the proposal's own independent variables, dependent
    variables, and control/baseline condition text. Pure deterministic
    metadata matching — family match is exact, keyword overlap is a plain
    set intersection over lowercased, tokenized text.

    THIS IS A GUARDRAIL, NOT PROOF OF NOVELTY (Phase-I-readiness MEDIUM
    finding #8): it catches a proposal that reuses recognizable vocabulary
    from an already-rejected direction, nothing more. It cannot, and is not
    intended to, detect a genuinely-rejected idea reworded with zero shared
    keywords -- that residual risk is accepted and named here, not hidden.
    Deeper novelty assessment remains the reviewer role's responsibility
    (see research/dry_run/prompts/reviewer_critique.md's novelty_assessment
    field) -- this function is deliberately NOT an LLM call and never will
    be, per the absolute rule that deterministic checks, not LLM judgment,
    gate the mechanical redundancy check."""
    from research.db import ExperimentNotFoundError, OmniLabDB

    conflicts = []
    proposal_keywords = set()
    for iv in proposal.independent_variables:
        proposal_keywords |= _keywords(iv)
    # Broadened signal (Phase-I-readiness MEDIUM finding #8): dependent
    # variables (a proxy for the targeted failure bucket/metric) and the
    # control/baseline condition text also contribute keywords -- purely
    # additive (can only catch MORE recognizable overlap, never less; the
    # family match above still has to hold too).
    for dv in proposal.dependent_variables:
        proposal_keywords |= _keywords(dv)
    proposal_keywords |= _keywords(proposal.control_condition)
    proposal_keywords |= _keywords(proposal.baseline_comparison)
    if not proposal_keywords:
        return conflicts

    with OmniLabDB() as db:
        for rec in memory_db.list_records(tag="REJECTED_HYPOTHESIS", include_superseded=False):
            if not rec.experiment_id:
                continue
            try:
                exp = db.get_experiment(rec.experiment_id)
            except ExperimentNotFoundError:
                continue
            if exp.experiment_family != proposal.family:
                continue
            rec_keywords = _keywords(rec.independent_variable or "")
            if proposal_keywords & rec_keywords:
                conflicts.append((rec.experiment_id, rec.record_id))
    return conflicts


# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------


def validate(spec: ExperimentSpec, db=None, memory_db=None) -> ValidationResult:
    """Validate an ExperimentSpec's proposal (and, if populated, its result)
    against every mechanical check listed in Phase F's spec. `db`/`memory_db`
    are optional pre-opened OmniLabDB/MemoryDB instances (for test injection);
    if omitted, this function opens/closes its own against the real DBs."""
    result = ValidationResult()
    p = spec.proposal

    _own_db = db is None
    _own_memory_db = memory_db is None
    if _own_db:
        from research.db import OmniLabDB
        db = OmniLabDB()
    if _own_memory_db:
        from research.memory_db import MemoryDB
        memory_db = MemoryDB()

    try:
        _validate_proposal(p, result, db, memory_db)
        _validate_result(spec, result)
    finally:
        if _own_db:
            db.close()
        if _own_memory_db:
            memory_db.close()

    return result


def _validate_proposal(p: ExperimentProposal, result: ValidationResult, db, memory_db) -> None:
    # -- malformed experiment ID --
    if not EXPERIMENT_ID_RE.match(p.experiment_id):
        result.add("ERROR", "MALFORMED_ID", f"experiment_id {p.experiment_id!r} does not match EXP-\\d{{4}}")

    # -- duplicate experiment ID --
    from research.db import ExperimentNotFoundError
    try:
        db.get_experiment(p.experiment_id)
        result.add("ERROR", "DUPLICATE_ID", f"experiment_id {p.experiment_id!r} already exists in research/db.py")
    except ExperimentNotFoundError:
        pass

    # -- missing hypothesis / motivation --
    if not p.hypothesis.strip():
        result.add("ERROR", "MISSING_HYPOTHESIS", "hypothesis is missing/empty")
    if not p.motivation.strip():
        result.add("ERROR", "MISSING_MOTIVATION", "motivation is missing/empty")

    # -- unsupported family --
    if p.family not in REGISTRY:
        result.add("ERROR", "UNKNOWN_FAMILY", f"experiment family {p.family!r} is not in research/experiment_registry.py")
    else:
        family_spec = REGISTRY[p.family]
        # -- invalid execution requirements: mac/iphone flag vs. family --
        if p.mac_iphone_required and family_spec.windows_evaluatable and family_spec.production_validation_requirement == "OFFLINE_SIMULATABLE":
            result.add(
                "WARNING", "MAC_IPHONE_MISMATCH",
                f"mac_iphone_required=True but family {p.family!r} is windows_evaluatable with "
                "production_validation_requirement=OFFLINE_SIMULATABLE — confirm this is intentional.",
            )
        if not p.mac_iphone_required and family_spec.production_validation_requirement in ("REQUIRES_MAC", "REQUIRES_IPHONE"):
            result.add(
                "ERROR", "MAC_IPHONE_REQUIRED_MISMATCH",
                f"family {p.family!r} requires {family_spec.production_validation_requirement} per the registry, "
                "but mac_iphone_required=False on the proposal.",
            )

    # -- baseline_run_id must resolve to a real artifact --
    if not p.baseline_run_id:
        result.add("ERROR", "MISSING_BASELINE", "baseline_run_id is required")
    elif resolve_baseline_run_dir(p.baseline_run_id) is None:
        result.add(
            "ERROR", "BAD_BASELINE_REF",
            f"baseline_run_id {p.baseline_run_id!r} does not resolve to a real run directory under "
            "benchmark/results/baseline/ or benchmark/results/diagnostics/",
        )

    # -- prior_experiment_ids must resolve --
    for exp_id in p.prior_experiment_ids:
        try:
            db.get_experiment(exp_id)
        except ExperimentNotFoundError:
            result.add("ERROR", "BAD_PRIOR_EXPERIMENT_REF", f"prior_experiment_ids references nonexistent experiment {exp_id!r}")

    # -- evidence_references must resolve to real memory records --
    from research.memory_db import MemoryRecordNotFoundError
    for mem_id in p.evidence_references:
        try:
            memory_db.get(mem_id)
        except MemoryRecordNotFoundError:
            result.add("ERROR", "BAD_EVIDENCE_REF", f"evidence_references references nonexistent memory finding {mem_id!r}")

    # -- variables --
    if not p.independent_variables:
        result.add("ERROR", "MISSING_INDEPENDENT_VARIABLE", "independent_variables is empty")
    if not p.dependent_variables:
        result.add("ERROR", "MISSING_DEPENDENT_VARIABLES", "dependent_variables is empty")

    # -- controls --
    if not p.control_condition.strip():
        result.add("ERROR", "MISSING_CONTROL_CONDITION", "control_condition is missing/empty")
    if not p.baseline_comparison.strip():
        result.add("ERROR", "MISSING_BASELINE_COMPARISON", "baseline_comparison is missing/empty")

    # -- success criteria: missing/empty, contradictory, invalid metric names --
    if not p.success_criteria:
        result.add("ERROR", "MISSING_SUCCESS_CRITERIA", "success_criteria is empty")
    else:
        sc = p.success_criteria
        mmd = sc.get("min_meaningful_delta")
        if mmd is not None and mmd < 0:
            result.add("ERROR", "CONTRADICTORY_SUCCESS_CRITERIA", f"min_meaningful_delta must be >= 0, got {mmd!r}")
        pf = sc.get("precision_floor")
        if pf is not None and (pf < 0 or pf > 1.0):
            result.add("ERROR", "CONTRADICTORY_SUCCESS_CRITERIA", f"precision_floor must be within [0, 1], got {pf!r}")
        max_lat = sc.get("max_latency_regression_pct")
        if max_lat is not None and max_lat < 0:
            result.add("ERROR", "CONTRADICTORY_SUCCESS_CRITERIA", f"max_latency_regression_pct must be >= 0, got {max_lat!r}")
        # a concrete (non-exhaustive) mutual-exclusion check: a required
        # minimum delta that is itself set higher than a simultaneously
        # declared "no regression allowed" ceiling of 0 can never both be
        # satisfied by any real improving result once floored by a 0%
        # allowed regression alongside a nonzero required delta on the SAME
        # metric direction — flagged here as the one concrete contradiction
        # example named in the Phase F spec; not an exhaustive SAT solver.
        if mmd is not None and max_lat == 0 and mmd > 0 and sc.get("primary_metric") == "latency.p95_ms":
            result.add(
                "ERROR", "CONTRADICTORY_SUCCESS_CRITERIA",
                "primary_metric is latency.p95_ms with min_meaningful_delta > 0 (an improvement is required) "
                "but max_latency_regression_pct=0 (no regression allowed) — these cannot both gate the same "
                "metric direction consistently; clarify which one is authoritative.",
            )
        # invalid metric names
        for key in ("primary_metric",):
            metric = sc.get(key)
            if metric is not None and not is_known_metric(metric):
                result.add("ERROR", "INVALID_METRIC_NAME", f"success_criteria.{key} {metric!r} is not a known metric (see KNOWN_METRIC_GROUPS/KNOWN_METRIC_SUFFIXES)")
        for g in sc.get("guardrail_metrics", []):
            if not is_known_metric(g):
                result.add("ERROR", "INVALID_METRIC_NAME", f"success_criteria.guardrail_metrics contains unknown metric {g!r}")

    # -- Human-authority approval gates (Phase-I CANDIDATE-0001 postmortem
    #    fix): these are NEEDS_HUMAN_APPROVAL, never ERROR. A proposal that
    #    correctly DESCRIBES a future need for one of these approvals is
    #    scientifically/structurally fine -- it is not yet QUEUE-eligible
    #    (is_queue_eligible() below checks these too), but it IS reviewable
    #    (is_valid ignores this level entirely). See this module's Level
    #    comment above for the full rationale; see
    #    reports/phase_i/CANDIDATE_0001_POSTMORTEM.md for the incident that
    #    prompted this fix -- CANDIDATE-0001 was incorrectly REJECTED
    #    (treated as scientifically invalid) purely for accurately stating
    #    mac_iphone_required=True with no fabricated approval.
    if p.production_impact and not p.production_swift_modification_approved:
        result.add(
            "NEEDS_HUMAN_APPROVAL", "UNAPPROVED_PRODUCTION_IMPACT",
            "production_impact=True but production_swift_modification_approved=False — "
            "a production-impacting proposal requires explicit human approval before it can be queue-eligible. "
            "The proposal itself is not thereby invalid.",
        )
    if p.mac_iphone_required and not p.mac_iphone_deployment_approved:
        result.add(
            "NEEDS_HUMAN_APPROVAL", "UNAPPROVED_MAC_IPHONE_DEPLOYMENT",
            "mac_iphone_required=True but mac_iphone_deployment_approved=False — this proposal correctly "
            "describes a future device-validation need; it requires human approval before queueing, but is "
            "not thereby an invalid proposal.",
        )
    if p.family == "training_data" and not p.new_training_approved:
        result.add(
            "NEEDS_HUMAN_APPROVAL", "UNAPPROVED_NEW_TRAINING",
            f"family={p.family!r} implies new training but new_training_approved=False — requires human "
            "approval before queueing, but is not thereby an invalid proposal.",
        )

    # -- unapproved external-data/privacy path -- same NEEDS_HUMAN_APPROVAL
    #    treatment as above, same rationale.
    if p.data_privacy_classification == "PRIVATE_USER_DATA" and not p.private_user_data_use_approved:
        result.add(
            "NEEDS_HUMAN_APPROVAL", "UNAPPROVED_PRIVATE_DATA_USE",
            "data_privacy_classification=PRIVATE_USER_DATA but private_user_data_use_approved=False.",
        )
    if p.external_api_required and not p.external_upload_approved:
        result.add(
            "NEEDS_HUMAN_APPROVAL", "UNAPPROVED_EXTERNAL_API",
            "external_api_required=True but external_upload_approved=False. NOTE: the presence of "
            "OPENROUTER_API_KEY in the environment has no bearing on this flag whatsoever — see "
            "research/experiment_validator.py's module docstring and tests/test_experiment_spec.py's "
            "decoupling test.",
        )

    # -- rejected-hypothesis acknowledgment (Phase F item #8) --
    conflicts = find_rejected_hypothesis_conflicts(p, memory_db)
    acknowledged = set(p.acknowledges_rejected_hypothesis_ids)
    for exp_id, mem_id in conflicts:
        if exp_id not in acknowledged and mem_id not in acknowledged:
            result.add(
                "ERROR", "UNACKNOWLEDGED_REJECTED_HYPOTHESIS",
                f"proposal's family+independent_variables closely matches rejected hypothesis "
                f"{mem_id} (experiment {exp_id}) — set acknowledges_rejected_hypothesis_ids to include "
                f"{exp_id!r} or {mem_id!r} and provide a non-empty materially_new_rationale, or revise the proposal.",
            )
        elif not p.materially_new_rationale.strip():
            result.add(
                "ERROR", "MISSING_MATERIALLY_NEW_RATIONALE",
                f"proposal acknowledges rejected hypothesis {mem_id} ({exp_id}) but materially_new_rationale is empty.",
            )

    # -- placeholder-garbage rejection (Phase H schema-mapping fix): a bare
    #    "TBD"/"unknown"/"N/A" is an ERROR, never merely a review flag — it
    #    is indistinguishable from "nobody thought about this field", which
    #    must not pass silently just because the field is non-empty. A real
    #    explicit-prerequisite sentence is unaffected (see _is_placeholder's
    #    docstring above: exact-match only, not a substring scan).
    for field_name in (
        "dataset_version", "model_config_ref", "isolation_requirements",
        "reproducibility_requirements", "implementation_scope",
    ):
        value = getattr(p, field_name)
        if value and _is_placeholder(value):
            result.add(
                "ERROR", "PLACEHOLDER_VALUE",
                f"{field_name} is a bare placeholder ({value!r}) — state a real value or an "
                "explicit prerequisite/limitation sentence, never an empty stand-in.",
            )

    # -- items not mechanically checkable: explicit NEEDS_HUMAN_REVIEW --
    if not p.procedure.strip():
        result.add("NEEDS_HUMAN_REVIEW", "PROCEDURE_QUALITY", "procedure narrative is empty — cannot mechanically judge methodology soundness; human review required.")
    if not p.reproducibility_requirements.strip():
        result.add("NEEDS_HUMAN_REVIEW", "REPRODUCIBILITY_QUALITY", "reproducibility_requirements is empty — cannot mechanically judge reproducibility; human review required.")
    if not p.isolation_requirements.strip():
        result.add("NEEDS_HUMAN_REVIEW", "ISOLATION_REQUIREMENTS_QUALITY", "isolation_requirements is empty — cannot mechanically judge train/eval isolation adequacy; human review required.")
    if not p.dataset_version.strip():
        result.add("NEEDS_HUMAN_REVIEW", "DATASET_VERSION_QUALITY", "dataset_version is empty — cannot mechanically judge dataset provenance/version adequacy; human review required.")
    if not p.model_config_ref.strip():
        result.add("NEEDS_HUMAN_REVIEW", "MODEL_CONFIG_REF_QUALITY", "model_config_ref is empty — cannot mechanically judge model/config provenance; human review required.")
    if not p.compute_resource_estimate:
        result.add("NEEDS_HUMAN_REVIEW", "COMPUTE_ESTIMATE_QUALITY", "compute_resource_estimate is empty — cannot mechanically judge resource feasibility; human review required.")
    result.add(
        "NEEDS_HUMAN_REVIEW", "SCIENTIFIC_MERIT",
        "Whether this hypothesis is scientifically interesting/worth the resource spend is not "
        "mechanically checkable by this validator — always requires human review regardless of "
        "whether every other check passes.",
    )


def _validate_result(spec: ExperimentSpec, result: ValidationResult) -> None:
    """Delegate to the proposal/result separation invariant (Phase F item #3):
    a spec still in DRAFT/VALIDATED pre-execution state must have an empty
    ExperimentResult. This complements (does not replace)
    check_no_result_fields_in_proposal, which catches the same problem at
    the raw-dict/deserialization boundary."""
    if spec.result.execution_status is None and not spec.result.is_empty():
        result.add(
            "ERROR", "PREMATURE_RESULT_FIELDS",
            "ExperimentResult has populated field(s) but execution_status is None — observed "
            "results must never be supplied before real execution has happened.",
        )


# ---------------------------------------------------------------------------
# Queue gate (Phase F item #9)
# ---------------------------------------------------------------------------


def is_queue_eligible(validation_result: ValidationResult) -> bool:
    """True iff validate() produced zero ERROR-level AND zero
    NEEDS_HUMAN_APPROVAL issues. Warnings and NEEDS_HUMAN_REVIEW flags may
    still require a human to look before actual approval, but they do not
    block this mechanical gate.

    NEEDS_HUMAN_APPROVAL is included here deliberately (Phase-I
    CANDIDATE-0001 postmortem fix): a proposal that accurately describes a
    still-missing human authorization (production impact, Mac/iPhone
    deployment, private data use, external API/data, new training) must
    NEVER become queue-eligible merely because is_valid() (structural/
    scientific validity only) is True. Queue admission requires BOTH."""
    return validation_result.is_valid and not validation_result.needs_human_approval
