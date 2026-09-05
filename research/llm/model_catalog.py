"""OpenRouter catalog-metadata gates — free-model enforcement and
capability-aware model selection (narrow remediation build, see
reports/openrouter/OPENROUTER_INTEGRATION_AUDIT.md).

This module reads OpenRouter's PUBLIC, UNAUTHENTICATED `/api/v1/models`
catalog shape (fetched by a caller, e.g. `research/cli.py` or a human/CI
process — see `find_eligible_free_models`'s docstring) and answers two
narrow, purely-local questions from an already-fetched catalog entry:

  1. `is_free_model(model_id, catalog_entry)` — is this model's pricing
     exactly zero for both prompt and completion tokens? FAIL CLOSED:
     missing/malformed/ambiguous pricing data is treated as "not free", not
     "assume free". There is no paid fallback anywhere in this codebase —
     a model that fails this check is rejected, not silently swapped for a
     paid one.

  2. `supports_structured_output(model_id, catalog_entry)` — does this
     model's catalog entry advertise OpenRouter's native `response_format`
     structured-output mechanism (`supported_parameters` containing
     `"response_format"`, per
     https://openrouter.ai/docs/features/structured-outputs and the
     `supported_parameters` field OMNISIGHT's own OPENROUTER_INTEGRATION_AUDIT.md
     already confirmed live for `liquid/lfm-2.5-2.6b:free` vs
     `nvidia/nemotron-3.5-lightning:free` / `poolside/laguna-s-2.1:free`)?
     FAIL CLOSED here too: missing/malformed `supported_parameters` means
     "capability unknown", which is treated as "unsupported", never
     "assume supported".

Both checks are PRE-FLIGHT — they run before any HTTP request is
constructed. `evaluate_model_for_role` below is the single call site meant
to gate a real call: it returns a `ModelSelectionRecord` with full
provenance (requested role/model, which checks ran, pass/fail per check,
selected model — always == requested model, since this module implements
NO substitution logic, see its docstring) or raises `ModelNotFreeError` /
`ModelCapabilityError` (both zero-network, zero-budget failures) before a
caller ever reaches `OpenRouterProvider.complete()`.

No substitution / no auto-routing (explicit design boundary)
-----------------------------------------------------------------------------
This module NEVER silently swaps a rejected model for a different one that
happens to pass. `roles.yaml`'s `preferred_model` remains the single,
explicit, human-reviewed source of truth for what a live call actually
uses. `find_eligible_free_models` (bottom of this file) is an OFFLINE,
ADVISORY discovery helper for a human (or a future, explicitly-designed and
separately-reviewed process) to consult when *choosing* what to put in
`roles.yaml` next — it is NOT imported by `research/dry_run/pipeline.py` or
any other live-call path, and must never be, per the audit's explicit
provenance-risk finding about non-deterministic model selection
(OPENROUTER_INTEGRATION_AUDIT.md section 9's discussion of `openrouter/free`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


class ModelNotFreeError(ValueError):
    """Raised when a model's catalog pricing is not verifiably free (exactly
    zero for both prompt and completion), or pricing data is missing/
    ambiguous (fail-closed). Carries the `ModelSelectionRecord` that
    produced it for full provenance. Never raised after a network call —
    this is always a pre-flight, zero-budget rejection."""

    def __init__(self, message: str, record: "ModelSelectionRecord"):
        super().__init__(message)
        self.record = record


class ModelCapabilityError(ValueError):
    """Raised when a model's catalog entry does not advertise a required
    capability (currently: native structured-output / `response_format`
    support). Carries the `ModelSelectionRecord` for full provenance. Never
    raised after a network call."""

    def __init__(self, message: str, record: "ModelSelectionRecord"):
        super().__init__(message)
        self.record = record


CAPABILITY_STRUCTURED_OUTPUT = "structured_output"


def _to_float_or_none(value: Any) -> Optional[float]:
    """Best-effort numeric parse of an OpenRouter pricing field, which is
    documented/observed as a decimal string (e.g. "0", "0.0000000",
    "0.001"). Returns None (never raises) for anything that doesn't parse —
    callers treat None as "ambiguous", which is fail-closed for pricing."""
    if value is None:
        return None
    if isinstance(value, bool):  # bool is an int subtype -- reject explicitly
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


@dataclass(frozen=True)
class FreeEvidence:
    """The exact pricing fields that determined a free/not-free verdict —
    provenance, not a raw catalog dump."""

    prompt_price_raw: Any
    completion_price_raw: Any
    prompt_price_parsed: Optional[float]
    completion_price_parsed: Optional[float]
    is_free: bool
    reason: str


def is_free_model(model_id: str, catalog_entry: Optional[dict]) -> bool:
    """True iff BOTH prompt and completion pricing are exactly zero. Fail
    closed: a missing `pricing` object, a missing `prompt`/`completion` key,
    or a value that doesn't parse to a number is treated as NOT free."""
    return free_model_evidence(model_id, catalog_entry).is_free


def free_model_evidence(model_id: str, catalog_entry: Optional[dict]) -> FreeEvidence:
    if not isinstance(catalog_entry, dict):
        return FreeEvidence(None, None, None, None, False, "no catalog entry available for model")

    pricing = catalog_entry.get("pricing")
    if not isinstance(pricing, dict):
        return FreeEvidence(None, None, None, None, False, "catalog entry has no 'pricing' object")

    prompt_raw = pricing.get("prompt")
    completion_raw = pricing.get("completion")
    prompt_parsed = _to_float_or_none(prompt_raw)
    completion_parsed = _to_float_or_none(completion_raw)

    if prompt_parsed is None or completion_parsed is None:
        return FreeEvidence(
            prompt_raw, completion_raw, prompt_parsed, completion_parsed, False,
            "pricing field missing or non-numeric (ambiguous pricing is treated as ineligible)",
        )

    is_free = prompt_parsed == 0.0 and completion_parsed == 0.0
    reason = (
        "prompt and completion pricing both exactly zero"
        if is_free
        else f"non-zero pricing (prompt={prompt_parsed}, completion={completion_parsed})"
    )
    return FreeEvidence(prompt_raw, completion_raw, prompt_parsed, completion_parsed, is_free, reason)


@dataclass(frozen=True)
class CapabilityEvidence:
    supported_parameters_raw: Any
    supports_structured_output: bool
    reason: str


def supports_structured_output(model_id: str, catalog_entry: Optional[dict]) -> bool:
    """True iff the catalog entry's `supported_parameters` list contains
    `"response_format"` — the field OpenRouter's structured-outputs docs
    (https://openrouter.ai/docs/features/structured-outputs) document as the
    request-time opt-in, and the exact field OMNISIGHT's own audit used to
    distinguish `liquid/lfm-2.5-2.6b:free` (supported) from
    `nvidia/nemotron-3.5-lightning:free` / `poolside/laguna-s-2.1:free` (not
    supported). Fail closed: missing/malformed `supported_parameters` means
    "unknown", treated as unsupported."""
    return structured_output_capability_evidence(model_id, catalog_entry).supports_structured_output


def structured_output_capability_evidence(model_id: str, catalog_entry: Optional[dict]) -> CapabilityEvidence:
    if not isinstance(catalog_entry, dict):
        return CapabilityEvidence(None, False, "no catalog entry available for model")

    params = catalog_entry.get("supported_parameters")
    if not isinstance(params, list):
        return CapabilityEvidence(params, False, "catalog entry has no 'supported_parameters' list")

    supported = "response_format" in params
    reason = (
        "'response_format' present in supported_parameters"
        if supported
        else "'response_format' absent from supported_parameters"
    )
    return CapabilityEvidence(params, supported, reason)


@dataclass(frozen=True)
class ModelSelectionRecord:
    """Full provenance for one model-selection decision. Preserved even on
    rejection, so a caller can report exactly why a model was refused
    without re-deriving it from scratch."""

    role: str
    requested_model: str
    selected_model: str  # ALWAYS == requested_model in this build -- no substitution logic exists.
    free_check_performed: bool
    free_evidence: Optional[FreeEvidence]
    structured_output_required: bool
    capability_evidence: Optional[CapabilityEvidence]
    passed: bool
    reason: str


def evaluate_model_for_role(
    role: str,
    model_id: str,
    catalog_entry: Optional[dict],
    *,
    require_structured_output: bool = False,
) -> ModelSelectionRecord:
    """The single pre-flight gate: evaluate `model_id` (as configured for
    `role`, e.g. `roles.yaml`'s `preferred_model`) against catalog metadata.
    Always checks free-pricing. Checks structured-output capability only if
    `require_structured_output=True`.

    Raises `ModelNotFreeError` or `ModelCapabilityError` (never a bare
    exception) on failure -- both exceptions carry the full
    `ModelSelectionRecord`. Returns a passing `ModelSelectionRecord` on
    success. NEVER makes a network call and NEVER substitutes a different
    model -- `selected_model` is always `model_id` unchanged."""
    free_evidence = free_model_evidence(model_id, catalog_entry)
    if not free_evidence.is_free:
        record = ModelSelectionRecord(
            role=role,
            requested_model=model_id,
            selected_model=model_id,
            free_check_performed=True,
            free_evidence=free_evidence,
            structured_output_required=require_structured_output,
            capability_evidence=None,
            passed=False,
            reason=f"model is not verifiably free: {free_evidence.reason}",
        )
        raise ModelNotFreeError(
            f"role {role!r} model {model_id!r} rejected before any network request — "
            f"not verifiably free ({free_evidence.reason}). No paid fallback exists; "
            "this call consumed zero chat-completion budget.",
            record,
        )

    capability_evidence: Optional[CapabilityEvidence] = None
    if require_structured_output:
        capability_evidence = structured_output_capability_evidence(model_id, catalog_entry)
        if not capability_evidence.supports_structured_output:
            record = ModelSelectionRecord(
                role=role,
                requested_model=model_id,
                selected_model=model_id,
                free_check_performed=True,
                free_evidence=free_evidence,
                structured_output_required=True,
                capability_evidence=capability_evidence,
                passed=False,
                reason=f"model lacks required structured-output capability: {capability_evidence.reason}",
            )
            raise ModelCapabilityError(
                f"role {role!r} model {model_id!r} rejected before any network request — "
                f"lacks required capability {CAPABILITY_STRUCTURED_OUTPUT!r} "
                f"({capability_evidence.reason}). This call consumed zero chat-completion "
                "budget. No silent substitution was performed -- roles.yaml's "
                "preferred_model remains the explicit source of truth; update it manually "
                "if a different model is desired.",
                record,
            )

    return ModelSelectionRecord(
        role=role,
        requested_model=model_id,
        selected_model=model_id,
        free_check_performed=True,
        free_evidence=free_evidence,
        structured_output_required=require_structured_output,
        capability_evidence=capability_evidence,
        passed=True,
        reason="free-pricing check passed"
        + (
            "; structured-output capability check passed" if require_structured_output else ""
        ),
    )


# ---------------------------------------------------------------------------
# Offline/advisory discovery helper -- NOT wired into any live-call path.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelCandidate:
    """One catalog entry that passed the requested eligibility checks, with
    full provenance for each. A discovery HELPER's output — never consumed
    automatically by `research/dry_run/pipeline.py::_call_llm` or any other
    live-call path (see this module's docstring)."""

    model_id: str
    free_evidence: FreeEvidence
    capability_evidence: Optional[CapabilityEvidence]
    catalog_fetch_timestamp: str
    catalog_source: str


def find_eligible_free_models(
    catalog_snapshot: dict,
    required_capabilities: set[str] = frozenset(),
    *,
    catalog_fetch_timestamp: Optional[str] = None,
    catalog_source: str = "https://openrouter.ai/api/v1/models",
) -> list[ModelCandidate]:
    """Deterministic, provenance-recorded discovery over an ALREADY-FETCHED
    catalog snapshot (a dict as returned by OpenRouter's public,
    unauthenticated `GET /api/v1/models` -- fetching it is the caller's
    responsibility, e.g. a human, a CI job, or `research/cli.py`; this
    function performs NO I/O itself and is safe to call from a live-request
    path only in the sense that it makes no network call -- but it is NOT
    intended to be called there, see this module's docstring).

    `catalog_snapshot` is expected to have the shape `{"data": [ {...one
    model entry...}, ... ]}` (OpenRouter's documented catalog response
    shape) OR a plain `{model_id: entry}` mapping -- both are accepted for
    convenience in tests/scripts.

    Returns every candidate that is free (#1) AND (if
    `"structured_output"` is in `required_capabilities`) supports native
    structured output (#2), each with recorded provenance. This is advisory
    output for a human to review before manually updating `roles.yaml` --
    it is explicitly NOT used to auto-select a model for any live call."""
    require_structured = CAPABILITY_STRUCTURED_OUTPUT in required_capabilities
    timestamp = catalog_fetch_timestamp or datetime.now(timezone.utc).isoformat()

    entries: dict[str, dict]
    if isinstance(catalog_snapshot, dict) and isinstance(catalog_snapshot.get("data"), list):
        entries = {}
        for e in catalog_snapshot["data"]:
            if isinstance(e, dict) and isinstance(e.get("id"), str):
                entries[e["id"]] = e
    elif isinstance(catalog_snapshot, dict):
        entries = {k: v for k, v in catalog_snapshot.items() if isinstance(v, dict)}
    else:
        entries = {}

    candidates: list[ModelCandidate] = []
    for model_id, entry in entries.items():
        free_evidence = free_model_evidence(model_id, entry)
        if not free_evidence.is_free:
            continue
        capability_evidence: Optional[CapabilityEvidence] = None
        if require_structured:
            capability_evidence = structured_output_capability_evidence(model_id, entry)
            if not capability_evidence.supports_structured_output:
                continue
        candidates.append(
            ModelCandidate(
                model_id=model_id,
                free_evidence=free_evidence,
                capability_evidence=capability_evidence,
                catalog_fetch_timestamp=timestamp,
                catalog_source=catalog_source,
            )
        )
    return candidates
