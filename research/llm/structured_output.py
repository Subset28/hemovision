"""Phase G — structured-output schemas and validation for LLM role
responses.

Three response shapes, matching the three non-reviewer/analyst prose roles
already defined in research/llm/roles.yaml + research/llm/prompts/:
  - `HypothesisResponse`  (researcher role)
  - `ReviewerResponse`    (reviewer role)
  - `AnalysisResponse`    (analyst role)

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
from dataclasses import dataclass
from typing import Any

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


def _parse_json_object(raw_text: str) -> dict:
    try:
        data = json.loads(raw_text)
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


_DISPATCH = {
    "hypothesis": parse_and_validate_hypothesis,
    "reviewer": parse_and_validate_reviewer,
    "analysis": parse_and_validate_analysis,
}


def parse_and_validate(raw_text: str, shape: str) -> Any:
    """Dispatch to the validator for `shape` ("hypothesis" | "reviewer" |
    "analysis"). Raises ValidationError for an unknown shape or any
    malformed/adversarial payload."""
    fn = _DISPATCH.get(shape)
    if fn is None:
        raise ValidationError(f"unknown structured-output shape: {shape!r}")
    return fn(raw_text)
