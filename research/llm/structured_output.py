"""Phase G — structured-output schemas and validation for LLM role
responses.

Three response shapes, matching the three non-reviewer/analyst prose roles
already defined in research/llm/roles.yaml + research/llm/prompts/:
  - `HypothesisResponse`  (researcher role)
  - `ReviewerResponse`    (reviewer role)
  - `AnalysisResponse`    (analyst role)

Phase H adds two more shapes for the dry-run research agent
(research/dry_run/):
  - `ProposalResponse`  (researcher role, full Phase F ExperimentProposal-
    shaped content). Structurally excludes all 7 of Phase F's human-authority
    approval flags (`production_swift_modification_approved`,
    `coreml_model_replacement_approved`, `new_training_approved`,
    `private_user_data_use_approved`, `external_upload_approved`,
    `mac_iphone_deployment_approved`, `signing_distribution_change_approved`)
    — there is no field on this dataclass an LLM response could populate to
    set any of them; research/dry_run/pipeline.py additionally hard-codes
    all 7 to False when constructing the real ExperimentProposal, regardless
    of what raw JSON the model returned, so this is defense in depth, not
    the only gate.
  - `ReviewerCritique`  (reviewer role, dry-run-specific). Structurally
    excludes any field capable of setting a `research_verdict` or any of the
    7 human-authority approval flags — see `FORBIDDEN_REVIEWER_FIELDS`
    below and research/dry_run/pipeline.py's docstring for the mechanical
    test that enforces this.

Chain-of-custody contract (Phase G section 9 — this is the load-bearing
part of this module, not the dataclasses themselves): a response shape here
must NOT contain any Phase F result-only field (`metrics`,
`research_verdict`, `verdict`, `observed_results`, `pass_fail`, ...) — those
belong to `research/experiment_spec.py::ExperimentResult`, which is only
ever populated from real benchmark execution, never from LLM output. This
reuses the exact proposal/result separation principle Phase F already
built for `ExperimentProposal.from_dict()` (see
`research/experiment_spec.py::check_no_result_fields_in_proposal`) — this
module is the LLM-output-side twin of that check, one layer earlier.

`parse_and_validate(raw_text, shape)` returns a validated dataclass or
raises `ValidationError`. Malformed input (not JSON, wrong type, missing
required fields, or a forbidden result-only field) always raises — there is
no code path here that returns a partially-trusted object. Nothing in this
module writes to research/db.py, research/experiment_validator.py's queue
gate, or any benchmark-evidence artifact; a caller wanting to act on a
validated response must explicitly do that separately, and even then
`research/experiment_spec.py::ExperimentProposal.from_dict()` enforces the
same forbidden-field check independently — this is defense in depth, not
the only gate.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Native OpenRouter structured-output support (narrow remediation build --
# see reports/openrouter/OPENROUTER_INTEGRATION_AUDIT.md sections 2/4/16).
#
# `build_response_format(schema, name)` builds OpenRouter's documented
# request-time opt-in shape (https://openrouter.ai/docs/features/structured-outputs):
#   {"type": "json_schema", "json_schema": {"name": ..., "strict": True, "schema": {...}}}
# This is a CONFORMANCE AID, never authoritative -- every response, native
# structured-output or not, still passes through this module's
# parse_and_validate_* functions AND research/experiment_validator.py's
# deterministic validate() unchanged. See research/dry_run/pipeline.py.
# ---------------------------------------------------------------------------


def build_response_format(schema: dict, name: str, *, strict: bool = True) -> dict:
    """Build OpenRouter's native `response_format: {type: "json_schema", ...}`
    request field for a given JSON Schema. Pass the result as the
    `response_format` kwarg to `OpenRouterProvider.complete()` (it flows
    straight into the request body via that method's existing
    `body.update(kwargs)` -- no other wiring is required)."""
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "strict": strict, "schema": schema},
    }


def proposal_response_json_schema() -> dict:
    """A JSON Schema constraining the shape of `ProposalResponse` -- the
    LLM-authorable subset of research/experiment_spec.py::ExperimentProposal
    (title, family, research_question, hypothesis, motivation,
    evidence_references, prior_experiment_ids, independent_variables,
    dependent_variables, controls, methodology fields, success criteria,
    expected-interpretation fields; deliberately excludes ALL 7 human-
    authority approval flags and any ExperimentResult field -- there is no
    property here that could hold one).

    Simplifications (documented per the task spec): nested list/dict fields
    (`independent_variables`, `dependent_variables`, `success_criteria`,
    `controlled_variables`, `evidence_references`, `prior_experiment_ids`,
    `acknowledges_rejected_hypothesis_ids`) are typed as generic
    `array`/`object` rather than fully-specified nested schemas -- OpenRouter
    JSON Schema strict mode has practical limits on deeply-nested
    `additionalProperties: false` objects with heterogeneous value types, and
    this codebase's own local validators (`structured_output.py`'s
    `_require_*` helpers + `research/experiment_validator.py::validate`)
    already enforce the real per-field invariants after parsing -- this
    schema only needs to meaningfully constrain the *shape* well enough to
    make native structured-output mode worth using, not to duplicate every
    local check OpenRouter has no way to express anyway."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "selected_problem",
            "selection_rationale",
            "title",
            "family",
            "research_question",
            "hypothesis",
            "motivation",
            "independent_variables",
            "dependent_variables",
            "control_condition",
            "baseline_comparison",
            "success_criteria",
            "supports_hypothesis_if",
            "rejects_hypothesis_if",
            "inconclusive_if",
            "evidence_references",
            "prior_experiment_ids",
            "controlled_variables",
            "procedure",
            "production_impact",
            "production_impact_description",
            "data_privacy_classification",
            "external_api_required",
            "mac_iphone_required",
            "acknowledges_rejected_hypothesis_ids",
            "materially_new_rationale",
        ],
        "properties": {
            "selected_problem": {"type": "string"},
            "selection_rationale": {"type": "string"},
            "title": {"type": "string"},
            "family": {"type": "string"},
            "research_question": {"type": "string"},
            "hypothesis": {"type": "string"},
            "motivation": {"type": "string"},
            "independent_variables": {"type": "array", "items": {"type": "string"}},
            "dependent_variables": {"type": "array", "items": {"type": "string"}},
            "control_condition": {"type": "string"},
            "baseline_comparison": {"type": "string"},
            "success_criteria": {"type": "object"},
            "supports_hypothesis_if": {"type": "string"},
            "rejects_hypothesis_if": {"type": "string"},
            "inconclusive_if": {"type": "string"},
            "evidence_references": {"type": "array", "items": {"type": "string"}},
            "prior_experiment_ids": {"type": "array", "items": {"type": "string"}},
            "controlled_variables": {"type": "object"},
            "procedure": {"type": "string"},
            "production_impact": {"type": "boolean"},
            "production_impact_description": {"type": "string"},
            "data_privacy_classification": {"type": "string"},
            "external_api_required": {"type": "boolean"},
            "mac_iphone_required": {"type": "boolean"},
            "acknowledges_rejected_hypothesis_ids": {"type": "array", "items": {"type": "string"}},
            "materially_new_rationale": {"type": "string"},
        },
    }


def reviewer_critique_json_schema() -> dict:
    """A JSON Schema constraining the shape of `ReviewerCritique` --
    structurally distinct from `proposal_response_json_schema()` (different
    fields entirely). Deliberately excludes any field that could set a
    research verdict or grant a human-authority approval flag (see
    FORBIDDEN_REVIEWER_FIELDS) -- there is no property here for any of
    them."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "novelty_assessment",
            "scientific_validity_assessment",
            "targets_verified_failure_mode",
            "success_criteria_deterministic",
            "confounding_notes",
            "dataset_can_answer_question",
            "sample_size_adequate",
            "leakage_risk_notes",
            "privacy_safety_ok",
            "feasibility_notes",
            "worth_running",
            "recommends_revision",
            "revision_notes",
            "summary",
        ],
        "properties": {
            "novelty_assessment": {"type": "string"},
            "scientific_validity_assessment": {"type": "string"},
            "targets_verified_failure_mode": {"type": "boolean"},
            "success_criteria_deterministic": {"type": "boolean"},
            "confounding_notes": {"type": "string"},
            "dataset_can_answer_question": {"type": "boolean"},
            "sample_size_adequate": {"type": "boolean"},
            "leakage_risk_notes": {"type": "string"},
            "privacy_safety_ok": {"type": "boolean"},
            "feasibility_notes": {"type": "string"},
            "worth_running": {"type": "boolean"},
            "recommends_revision": {"type": "boolean"},
            "revision_notes": {"type": "string"},
            "summary": {"type": "string"},
        },
    }

# Mirrors the field vocabulary of research/experiment_spec.py::ExperimentResult
# (Phase F's execution-only side of the proposal/result split). Kept as a
# local, explicit list rather than importing ExperimentResult's dataclass
# fields directly, so this module has no import-time dependency on Phase F's
# internals — but the two lists must be kept conceptually in sync; see
# research/README.md's Phase G section.
RESULT_ONLY_FIELDS = frozenset(
    {
        "metrics",
        "research_verdict",
        "verdict",
        "observed_results",
        "pass_fail",
        "conclusion",
        "actual_outcome",
    }
)


class ValidationError(ValueError):
    """Raised for any malformed/adversarial LLM structured-output payload:
    not valid JSON, wrong top-level type, a missing/invalid required field,
    or a forbidden result-only field. Always raised before any dataclass is
    constructed — there is no partially-valid return value."""


@dataclass(frozen=True)
class HypothesisResponse:
    hypothesis: str
    evidence: str
    experiment_family: str


@dataclass(frozen=True)
class ReviewerResponse:
    scope_ok: bool
    flagged_issues: list
    summary: str


@dataclass(frozen=True)
class AnalysisResponse:
    summary: str
    memory_updates: list


# ---------------------------------------------------------------------------
# Phase H — dry-run research agent shapes.
# ---------------------------------------------------------------------------

# Phase F's 7 human-authority approval flags (research/experiment_spec.py::
# ExperimentProposal). Neither ProposalResponse nor ReviewerCritique may ever
# carry any of these — an LLM response containing one is rejected outright,
# never silently dropped, so a malicious/confused model cannot even attempt
# to smuggle an approval through this path.
APPROVAL_FLAG_FIELDS = frozenset(
    {
        "production_swift_modification_approved",
        "coreml_model_replacement_approved",
        "new_training_approved",
        "private_user_data_use_approved",
        "external_upload_approved",
        "mac_iphone_deployment_approved",
        "signing_distribution_change_approved",
    }
)

# Fields that would let a response set a scientific verdict directly — never
# permitted from reviewer (or any other) LLM output. `research_verdict` and
# `verdict` are already covered by RESULT_ONLY_FIELDS; listed again here
# explicitly so ReviewerCritique's own forbidden-field set is self-contained
# and readable without cross-referencing another module.
FORBIDDEN_REVIEWER_FIELDS = APPROVAL_FLAG_FIELDS | RESULT_ONLY_FIELDS


def _reject_forbidden_fields(data: dict, forbidden: frozenset, what: str) -> None:
    present = forbidden.intersection(data.keys())
    if present:
        raise ValidationError(
            f"{what} contains forbidden field(s), never permitted from LLM output: "
            f"{sorted(present)}"
        )


@dataclass(frozen=True)
class ProposalResponse:
    """Researcher-role, dry-run proposal content — a subset of
    research/experiment_spec.py::ExperimentProposal's fields: everything an
    LLM may legitimately author. Deliberately has NO field for any of the 7
    human-authority approval flags (APPROVAL_FLAG_FIELDS) or any
    ExperimentResult field (RESULT_ONLY_FIELDS) — both are rejected at parse
    time if present in the raw JSON, and there is no attribute here to hold
    them even if that check were somehow bypassed."""

    selected_problem: str
    selection_rationale: str
    title: str
    family: str
    research_question: str
    hypothesis: str
    motivation: str
    independent_variables: list
    dependent_variables: list
    control_condition: str
    baseline_comparison: str
    success_criteria: dict
    supports_hypothesis_if: str
    rejects_hypothesis_if: str
    inconclusive_if: str
    evidence_references: list = field(default_factory=list)
    prior_experiment_ids: list = field(default_factory=list)
    controlled_variables: dict = field(default_factory=dict)
    procedure: str = ""
    production_impact: bool = False
    production_impact_description: str = ""
    data_privacy_classification: str = "NONE"
    external_api_required: bool = False
    mac_iphone_required: bool = False
    acknowledges_rejected_hypothesis_ids: list = field(default_factory=list)
    materially_new_rationale: str = ""


@dataclass(frozen=True)
class ReviewerCritique:
    """Reviewer-role, dry-run critique of a ProposalResponse. Structurally
    cannot set a research_verdict or grant any human-authority approval flag
    — see FORBIDDEN_REVIEWER_FIELDS. `worth_running`/`recommends_revision`
    are the reviewer's OPINION, surfaced in the report alongside (never in
    place of) research/experiment_validator.py's deterministic
    validate()/is_queue_eligible() result — the local, mechanical result is
    always what the pipeline reports as authoritative."""

    novelty_assessment: str
    scientific_validity_assessment: str
    targets_verified_failure_mode: bool
    success_criteria_deterministic: bool
    confounding_notes: str
    dataset_can_answer_question: bool
    sample_size_adequate: bool
    leakage_risk_notes: str
    privacy_safety_ok: bool
    feasibility_notes: str
    worth_running: bool
    recommends_revision: bool
    revision_notes: str
    summary: str


_FENCE_RE = re.compile(r"^```(?:[a-zA-Z0-9_+-]*)\s*\n?(.*?)\n?```$", re.DOTALL)


def _strip_markdown_fence(text: str) -> str:
    """Strip a SINGLE markdown code fence that wraps the ENTIRE trimmed
    string (` ```json ... ``` ` or generic ` ``` ... ``` `). Returns the
    input unchanged if it is not fully fence-wrapped -- this is narrow,
    mechanical fence-stripping, not a scanner for fences anywhere in the
    text."""
    stripped = text.strip()
    m = _FENCE_RE.match(stripped)
    if m:
        return m.group(1).strip()
    return stripped


def _find_balanced_json_object_candidates(text: str) -> list[str]:
    """Scan `text` for top-level, brace-balanced `{...}` substrings (string
    literals respected so a `{`/`}` inside a JSON string value doesn't
    confuse the brace count). Returns every such candidate found -- callers
    decide what "exactly one" vs "ambiguous" means. This is a mechanical
    brace-balance scan, not a heuristic guesser: it does not attempt to
    validate JSON syntax itself, only to find balanced-brace spans."""
    candidates: list[str] = []
    depth = 0
    start: int | None = None
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    candidates.append(text[start : i + 1])
                    start = None
    return candidates


def _parse_json_object(raw_text: str) -> dict:
    """Extract and parse exactly one top-level JSON object from `raw_text`.

    Handles, in order (Phase-remediation section 4 -- documented boundary,
    read this before "improving" it):
      1. Plain JSON (unchanged, already worked).
      2. A SINGLE markdown fence (` ```json ... ``` ` or generic
         ` ``` ... ``` `) wrapping the ENTIRE trimmed response -- stripped
         before parsing.
      3. Leading/trailing whitespace -- trimmed.
      4. Brief surrounding prose ONLY if, after fence-stripping and
         whitespace-trimming, exactly ONE top-level, brace-balanced `{...}`
         block is found in the text. If direct parsing of the (fence-
         stripped, trimmed) text already succeeds, that result is used and
         candidate-scanning is skipped entirely.

    Explicitly refuses to guess in two cases -- these are hard failures,
    not best-effort extraction:
      - Zero JSON-object-shaped candidates found anywhere in the text.
      - MORE THAN ONE top-level candidate found (ambiguous -- which one did
        the model mean?). This module will never scan for "any braces
        anywhere" and pick the first/largest/likeliest one; an ambiguous
        response is a parser failure, reported as such, never guessed at.
    """
    if not isinstance(raw_text, str):
        raise ValidationError(f"response is not valid JSON: expected str, got {type(raw_text).__name__}")

    text = _strip_markdown_fence(raw_text)

    # Fast path: the (fence-stripped, trimmed) text is itself valid JSON.
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        data = None
        parse_ok = False
    else:
        parse_ok = True

    if not parse_ok:
        candidates = _find_balanced_json_object_candidates(text)
        if len(candidates) == 0:
            raise ValidationError("response is not valid JSON: no JSON object found in response text")
        if len(candidates) > 1:
            raise ValidationError(
                f"response contains {len(candidates)} ambiguous top-level JSON object "
                "candidates -- refusing to guess which one was intended"
            )
        try:
            data = json.loads(candidates[0])
        except (json.JSONDecodeError, TypeError) as e:
            raise ValidationError(f"response is not valid JSON: {e}") from e

    if not isinstance(data, dict):
        raise ValidationError(
            f"response must be a JSON object at the top level, got {type(data).__name__}"
        )
    return data


def _reject_result_only_fields(data: dict) -> None:
    present = RESULT_ONLY_FIELDS.intersection(data.keys())
    if present:
        raise ValidationError(
            "response contains result-only field(s) not permitted from an "
            f"LLM proposal/review/analysis: {sorted(present)} — these belong "
            "to ExperimentResult (research/experiment_spec.py), populated "
            "only from real benchmark execution."
        )


def _require_str(data: dict, field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"missing or invalid required string field: {field!r}")
    return value


def _require_list(data: dict, field: str) -> list:
    value = data.get(field)
    if not isinstance(value, list):
        raise ValidationError(f"missing or invalid required list field: {field!r}")
    return value


def _require_bool(data: dict, field: str) -> bool:
    value = data.get(field)
    if not isinstance(value, bool):
        raise ValidationError(f"missing or invalid required boolean field: {field!r}")
    return value


def parse_and_validate_hypothesis(raw_text: str) -> HypothesisResponse:
    data = _parse_json_object(raw_text)
    _reject_result_only_fields(data)
    return HypothesisResponse(
        hypothesis=_require_str(data, "hypothesis"),
        evidence=_require_str(data, "evidence"),
        experiment_family=_require_str(data, "experiment_family"),
    )


def parse_and_validate_reviewer(raw_text: str) -> ReviewerResponse:
    data = _parse_json_object(raw_text)
    _reject_result_only_fields(data)
    return ReviewerResponse(
        scope_ok=_require_bool(data, "scope_ok"),
        flagged_issues=_require_list(data, "flagged_issues"),
        summary=_require_str(data, "summary"),
    )


def parse_and_validate_analysis(raw_text: str) -> AnalysisResponse:
    data = _parse_json_object(raw_text)
    _reject_result_only_fields(data)
    return AnalysisResponse(
        summary=_require_str(data, "summary"),
        memory_updates=_require_list(data, "memory_updates"),
    )


def _require_dict(data: dict, field_name: str) -> dict:
    value = data.get(field_name)
    if not isinstance(value, dict):
        raise ValidationError(f"missing or invalid required object field: {field_name!r}")
    return value


def parse_and_validate_proposal(raw_text: str) -> ProposalResponse:
    data = _parse_json_object(raw_text)
    _reject_result_only_fields(data)
    _reject_forbidden_fields(data, APPROVAL_FLAG_FIELDS, "proposal response")

    known = {f.name for f in ProposalResponse.__dataclass_fields__.values()}
    unknown = sorted(set(data.keys()) - known)
    if unknown:
        raise ValidationError(f"proposal response contains unknown field(s): {unknown}")

    return ProposalResponse(
        selected_problem=_require_str(data, "selected_problem"),
        selection_rationale=_require_str(data, "selection_rationale"),
        title=_require_str(data, "title"),
        family=_require_str(data, "family"),
        research_question=_require_str(data, "research_question"),
        hypothesis=_require_str(data, "hypothesis"),
        motivation=_require_str(data, "motivation"),
        independent_variables=_require_list(data, "independent_variables"),
        dependent_variables=_require_list(data, "dependent_variables"),
        control_condition=_require_str(data, "control_condition"),
        baseline_comparison=_require_str(data, "baseline_comparison"),
        success_criteria=_require_dict(data, "success_criteria"),
        supports_hypothesis_if=_require_str(data, "supports_hypothesis_if"),
        rejects_hypothesis_if=_require_str(data, "rejects_hypothesis_if"),
        inconclusive_if=_require_str(data, "inconclusive_if"),
        evidence_references=list(data.get("evidence_references") or []),
        prior_experiment_ids=list(data.get("prior_experiment_ids") or []),
        controlled_variables=dict(data.get("controlled_variables") or {}),
        procedure=str(data.get("procedure") or ""),
        production_impact=bool(data.get("production_impact") or False),
        production_impact_description=str(data.get("production_impact_description") or ""),
        data_privacy_classification=str(data.get("data_privacy_classification") or "NONE"),
        external_api_required=bool(data.get("external_api_required") or False),
        mac_iphone_required=bool(data.get("mac_iphone_required") or False),
        acknowledges_rejected_hypothesis_ids=list(data.get("acknowledges_rejected_hypothesis_ids") or []),
        materially_new_rationale=str(data.get("materially_new_rationale") or ""),
    )


def parse_and_validate_reviewer_critique(raw_text: str) -> ReviewerCritique:
    data = _parse_json_object(raw_text)
    _reject_forbidden_fields(data, FORBIDDEN_REVIEWER_FIELDS, "reviewer critique")

    known = {f.name for f in ReviewerCritique.__dataclass_fields__.values()}
    unknown = sorted(set(data.keys()) - known)
    if unknown:
        raise ValidationError(f"reviewer critique contains unknown field(s): {unknown}")

    return ReviewerCritique(
        novelty_assessment=_require_str(data, "novelty_assessment"),
        scientific_validity_assessment=_require_str(data, "scientific_validity_assessment"),
        targets_verified_failure_mode=_require_bool(data, "targets_verified_failure_mode"),
        success_criteria_deterministic=_require_bool(data, "success_criteria_deterministic"),
        confounding_notes=_require_str(data, "confounding_notes"),
        dataset_can_answer_question=_require_bool(data, "dataset_can_answer_question"),
        sample_size_adequate=_require_bool(data, "sample_size_adequate"),
        leakage_risk_notes=_require_str(data, "leakage_risk_notes"),
        privacy_safety_ok=_require_bool(data, "privacy_safety_ok"),
        feasibility_notes=_require_str(data, "feasibility_notes"),
        worth_running=_require_bool(data, "worth_running"),
        recommends_revision=_require_bool(data, "recommends_revision"),
        revision_notes=str(data.get("revision_notes") or ""),
        summary=_require_str(data, "summary"),
    )


_DISPATCH = {
    "hypothesis": parse_and_validate_hypothesis,
    "reviewer": parse_and_validate_reviewer,
    "analysis": parse_and_validate_analysis,
    "proposal": parse_and_validate_proposal,
    "reviewer_critique": parse_and_validate_reviewer_critique,
}


def parse_and_validate(raw_text: str, shape: str) -> Any:
    """Dispatch to the validator for `shape` ("hypothesis" | "reviewer" |
    "analysis"). Raises ValidationError for an unknown shape or any
    malformed/adversarial payload."""
    fn = _DISPATCH.get(shape)
    if fn is None:
        raise ValidationError(f"unknown structured-output shape: {shape!r}")
    return fn(raw_text)
