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
    BOTH `"response_format"` (the request-time field OmniLab actually sends)
    AND `"structured_outputs"` (per OpenRouter's own structured-outputs docs
    -- https://openrouter.ai/docs/features/structured-outputs -- THIS is the
    documented capability indicator, not `response_format` alone: "This is
    the documented way to confirm support—not the presence of
    response_format alone. The response_format parameter is what you *use*
    in requests, but structured_outputs is what *indicates* the capability
    exists."). A prior version of this function checked `response_format`
    only -- a confirmed bug found during Phase H's catalog-verification
    audit (deterministic re-check of inclusionai/ling-3.0-flash-sante:free,
    which has NEITHER field, via raw requests.get, not WebFetch/LLM
    summarization). Fail closed: missing/malformed `supported_parameters`,
    or either field absent, means unsupported."""
    return structured_output_capability_evidence(model_id, catalog_entry).supports_structured_output


def structured_output_capability_evidence(model_id: str, catalog_entry: Optional[dict]) -> CapabilityEvidence:
    if not isinstance(catalog_entry, dict):
        return CapabilityEvidence(None, False, "no catalog entry available for model")

    params = catalog_entry.get("supported_parameters")
    if not isinstance(params, list):
        return CapabilityEvidence(params, False, "catalog entry has no 'supported_parameters' list")

    has_response_format = "response_format" in params
    has_structured_outputs = "structured_outputs" in params
    supported = has_response_format and has_structured_outputs
    if supported:
        reason = "'response_format' and 'structured_outputs' both present in supported_parameters"
    elif not has_structured_outputs:
        reason = "'structured_outputs' absent from supported_parameters (the documented OpenRouter capability indicator)"
    else:
        reason = "'response_format' absent from supported_parameters"
    return CapabilityEvidence(params, supported, reason)


# The A-F reasoning-capability-negotiation categories (Phase H follow-up,
# DRYRUN-0006's HTTP 400 root cause: liquid/lfm-2.5-2.6b:free's catalog
# entry is `"reasoning": {"mandatory": true}` -- no supported_efforts, no
# supports_max_tokens, nothing to negotiate -- and OmniLab previously sent
# `reasoning: {"enabled": false}` unconditionally, which OpenRouter/the
# provider rejected outright for a model where disabling isn't a valid
# option at all). Never guess a control the catalog doesn't advertise.
REASONING_NONE = "NONE"                        # A: no reasoning object at all -- send nothing
REASONING_DISABLED = "DISABLED"                # B: mandatory is explicitly False -- disable it
REASONING_EFFORT = "EFFORT"                    # D: supported_efforts includes a low-cost option
REASONING_MAX_TOKENS = "MAX_TOKENS"            # E: supports_max_tokens is True -- bound the budget
REASONING_MANDATORY_UNBOUNDED = "MANDATORY_UNBOUNDED"  # C: mandatory, nothing to bound it with
REASONING_UNKNOWN = "UNKNOWN"                  # F: reasoning object present but ambiguous shape


@dataclass(frozen=True)
class ReasoningDecision:
    """What (if anything) to put in the request body's `reasoning` field
    for this model, and why. `request_field` is `None` whenever sending
    nothing is the safe choice (categories A, C, F) -- never a guessed
    value. `category` is one of the REASONING_* constants above."""

    category: str
    request_field: Optional[dict]
    reason: str


_LOW_EFFORT_PREFERENCE = ("minimal", "low")  # cheapest-first; see docstring below


def build_reasoning_decision(
    model_id: str, catalog_entry: Optional[dict], *, max_reasoning_tokens_headroom: int = 512,
) -> ReasoningDecision:
    """Decide what `reasoning` field (if any) is safe to send for
    `model_id`, using ONLY the catalog's own `reasoning` sub-object --
    never inferred from the model's name/description containing the word
    "reasoning" (liquid/lfm-2.5-2.6b:free's own description calls it "a
    compact reasoning model", which tells you nothing about whether/how
    its reasoning can be configured; only the structured `reasoning` field
    does). Preference order, per Phase H's stated policy:
      1. mandatory is explicitly False -> officially disable it (category B).
      2. `supported_efforts` includes "minimal" or "low" -> use the cheapest
         of those (category D) -- even if reasoning is mandatory, a low
         effort level still leaves more room for the actual answer.
      3. `supports_max_tokens` is True -> bound the reasoning budget to
         `max_reasoning_tokens_headroom` tokens (category E), same
         rationale.
      4. reasoning is mandatory and none of the above controls exist ->
         nothing safe to send; category C, `request_field=None` (sending a
         guessed field caused DRYRUN-0006's HTTP 400) -- the caller should
         treat this as a signal to prefer a different model for a live
         attempt, not silently proceed hoping for the best.
      5. no `reasoning` key in the catalog entry at all -> category A,
         nothing to send (matches every non-reasoning model already in use).
      6. `reasoning` present but not a dict, or `mandatory` present but not
         a bool -> category F, fail closed (send nothing) rather than guess."""
    if not isinstance(catalog_entry, dict):
        return ReasoningDecision(REASONING_UNKNOWN, None, "no catalog entry available for model")

    reasoning_meta = catalog_entry.get("reasoning")
    if reasoning_meta is None:
        return ReasoningDecision(REASONING_NONE, None, "model has no 'reasoning' catalog metadata")
    if not isinstance(reasoning_meta, dict):
        return ReasoningDecision(
            REASONING_UNKNOWN, None,
            f"'reasoning' catalog field has unexpected shape ({type(reasoning_meta).__name__}); failing closed",
        )

    mandatory = reasoning_meta.get("mandatory")
    supported_efforts = reasoning_meta.get("supported_efforts")
    supports_max_tokens = reasoning_meta.get("supports_max_tokens")

    if mandatory is False:
        return ReasoningDecision(
            REASONING_DISABLED, {"enabled": False},
            "catalog reasoning.mandatory=false -- disabling is an officially supported control",
        )

    if isinstance(supported_efforts, list):
        for effort in _LOW_EFFORT_PREFERENCE:
            if effort in supported_efforts:
                return ReasoningDecision(
                    REASONING_EFFORT, {"effort": effort},
                    f"catalog reasoning.supported_efforts includes {effort!r} -- using the lowest available effort",
                )

    if supports_max_tokens is True:
        return ReasoningDecision(
            REASONING_MAX_TOKENS, {"max_tokens": max_reasoning_tokens_headroom},
            f"catalog reasoning.supports_max_tokens=true -- bounding reasoning to {max_reasoning_tokens_headroom} tokens",
        )

    if mandatory is True:
        return ReasoningDecision(
            REASONING_MANDATORY_UNBOUNDED, None,
            "catalog reasoning.mandatory=true with no supported_efforts/supports_max_tokens to bound it -- "
            "nothing safe to configure; consider a different model for a live attempt",
        )

    return ReasoningDecision(
        REASONING_UNKNOWN, None,
        f"'reasoning' catalog metadata present but ambiguous (mandatory={mandatory!r}); failing closed",
    )


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


CATALOG_SNAPSHOT_SOURCE = "https://openrouter.ai/api/v1/models"


def save_catalog_snapshot(
    model_id: str,
    catalog_entry: Optional[dict],
    *,
    eligibility_result: str,
    rejection_reason: Optional[str] = None,
    snapshot_dir: Optional["Path"] = None,
) -> "Path":
    """Persist a small, sanitized, PUBLIC-metadata-only snapshot of one
    model's catalog entry at decision time (Phase H catalog-verification
    audit, section 5: "the previous process has exposed an evidence-quality
    problem" -- an earlier WebFetch/LLM-summarized check claimed
    capabilities a deterministic raw fetch later contradicted, and no raw
    evidence survived to adjudicate which was right). Every field here is
    already public on openrouter.ai/models -- never the API key, never a
    request/response body, never a prompt.

    Does NOT store the full ~400+ model catalog -- one small JSON file per
    snapshot, named by model + timestamp, under `research/catalog_snapshots/`
    (gitignored, like other local runtime state -- this is an audit trail
    for THIS machine's decisions, not a source-controlled artifact).
    """
    import json

    from research.config import RESEARCH_DIR

    snapshot_dir = snapshot_dir or (RESEARCH_DIR / "catalog_snapshots")
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    entry = catalog_entry if isinstance(catalog_entry, dict) else {}
    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "catalog_source": CATALOG_SNAPSHOT_SOURCE,
        "model_id": model_id,
        "pricing": entry.get("pricing"),
        "supported_parameters": entry.get("supported_parameters"),
        "reasoning": entry.get("reasoning"),
        "context_length": entry.get("context_length"),
        "top_provider": entry.get("top_provider"),
        "eligibility_result": eligibility_result,  # e.g. "ELIGIBLE" / "REJECTED"
        "rejection_reason": rejection_reason,
    }

    safe_name = model_id.replace("/", "_").replace(":", "_")
    ts_compact = snapshot["timestamp"].replace(":", "").replace("-", "").split(".")[0]
    path = snapshot_dir / f"{safe_name}_{ts_compact}.json"
    path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return path
