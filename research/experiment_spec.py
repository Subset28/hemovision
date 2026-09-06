"""Phase F — canonical, machine-validated experiment specification.

This module is a SCHEMA/VALIDATION layer that sits ON TOP OF the existing,
already-working infrastructure — it does not replace `research/db.py`'s
execution-status/research-verdict machinery, `research/experiment_schema.py`'s
per-experiment markdown/YAML file generator, or `research/experiment_registry.py`'s
family registry. See `research/PHASE_F_AUDIT.md` (or research/README.md's
Phase F section) for the full field-by-field audit this design is based on.

Implementation choice — dataclasses + hand-rolled validation, NOT Pydantic
-----------------------------------------------------------------------------
The project already standardizes on "dataclasses + stdlib, no ORM/heavy
validation framework" for both `research/db.py::Experiment` and
`research/memory_db.py::MemoryRecord`. Adding Pydantic here would mean two
different validation philosophies living side by side for structurally
similar problems (a typed record with invariants, loaded from/serialized to
JSON), plus a new runtime dependency, for a schema that:
  - has no need for Pydantic's main value-adds (coercion from loosely-typed
    external input, OpenAPI generation, high-throughput validation) — the
    only "external" input here is JSON round-tripped from this same codebase,
    plus (in a future phase, NOT this one) LLM-authored JSON, which needs
    exactly the kind of explicit, auditable, hand-written rejection rules
    `research/experiment_validator.py` implements, not a generic type coercer
    that would silently coerce a wrong-shaped value into a plausible one.
  - benefits from `dataclasses.replace()` for the freeze/amend mechanism
    (see `ExperimentSpec.amend`), which is simplest when the payload really
    is a plain dataclass.
This is a deliberate call, not an oversight — flagged again in
research/README.md's Phase F section.

Two-part split (Phase F item #3): `ExperimentProposal` (everything
pre-registered, before any execution) vs. `ExperimentResult` (everything only
knowable after execution). They are separate dataclasses on purpose — an
`ExperimentProposal` object structurally CANNOT hold a metric, a verdict, or
a conclusion; there is no field for it. The one place an LLM-or-human-authored
JSON blob for a *proposal* could still smuggle in a result-shaped key is at
deserialization time (`ExperimentProposal.from_dict`), so that path explicitly
rejects any key that collides with an `ExperimentResult` field name — see
`check_no_result_fields_in_proposal` and `ProposalContainsResultFieldsError`.

Freeze / amendment (Phase F item #4)
-----------------------------------------------------------------------------
`ExperimentProposal` is a frozen dataclass. `ExperimentSpec.freeze()` moves
`status` from DRAFT to VALIDATED or APPROVED (distinct axis from
`research/db.py`'s `execution_status`, which is about the RUN once queued —
see docstring on `SPEC_STATUSES` below) and snapshots a hash of the frozen
proposal payload. Any subsequent change MUST go through `ExperimentSpec.amend()`,
which creates a fully traceable `Amendment` record (old value, new value,
reason, timestamp, approved_by) and re-freezes at the new hash — it never
silently overwrites the old value in place. `ExperimentSpec.verify_integrity()`
recomputes the hash and raises `FrozenProposalTamperedError` if a loaded
record's proposal payload doesn't match its recorded `frozen_hash`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime, timezone
from typing import Any, Optional

SCHEMA_VERSION = "1.0"

EXPERIMENT_ID_RE = re.compile(r"^EXP-\d{4}$")

# Spec lifecycle axis — deliberately distinct from research/db.py's
# execution_status (which is about whether the RUN happened). This axis is
# about whether the PROPOSAL's pre-registered content is still mutable.
#   DRAFT     -> content may be freely edited (no freeze() called yet).
#   VALIDATED -> validate() has produced zero errors and freeze() was called;
#                content is now frozen (amend() required for any change).
#   APPROVED  -> a human (or future authorized role) has additionally signed
#                off on a VALIDATED spec being queue-eligible; content is
#                frozen exactly as under VALIDATED. Kept as a distinct value
#                (not folded into VALIDATED) because "internally consistent"
#                and "a human said yes" are different facts.
SPEC_STATUSES = ("DRAFT", "VALIDATED", "APPROVED")

# Historical-backfill markers (Phase F item #7's migration policy — see
# research/README.md "Phase F — backfill migration policy" for the full
# policy this implements):
#   LEGACY_UNKNOWN  — the concept plausibly existed in spirit but was not
#                      captured as a discrete, separately-authored field at
#                      the time (e.g. supports_hypothesis_if/rejects_hypothesis_if/
#                      inconclusive_if were never written as separate
#                      pre-registered conditions for EXP-0001..0005, even
#                      though hypothesis.md's prose gestures at some of this).
#   NOT_RECORDED    — the concept did not exist at all at the time (e.g.
#                      evidence_references pointing at Phase-E memory finding
#                      IDs — Phase E's memory DB did not exist when
#                      EXP-0001..0005 were queued).
#   NOT_APPLICABLE  — the field is meaningful for this schema in general but
#                      does not apply to this particular experiment (e.g.
#                      mac_iphone_required=False experiments have no
#                      applicable mac_iphone_deployment_approved need).
LEGACY_UNKNOWN = "LEGACY_UNKNOWN"
NOT_RECORDED = "NOT_RECORDED"
NOT_APPLICABLE = "NOT_APPLICABLE"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProposalContainsResultFieldsError(ValueError):
    """Raised when a dict destined to become an ExperimentProposal contains
    one or more keys that belong to ExperimentResult (Phase F item #3's
    'reject observed numbers supplied as part of a proposal' requirement)."""


class FrozenProposalTamperedError(ValueError):
    """Raised when a loaded ExperimentSpec's proposal payload does not match
    its recorded frozen_hash — i.e. the frozen content was mutated outside
    amend()."""


class SpecStatusError(ValueError):
    """Raised on an illegal spec-status operation (e.g. amend() on a DRAFT
    spec with no baseline to amend against, or freeze() called twice)."""


class SchemaVersionError(ValueError):
    """Raised for a missing/unsupported schema_version. Never silently
    guessed — see research/experiment_spec_migrations.py."""


# ---------------------------------------------------------------------------
# ExperimentResult — everything ONLY populated post-execution.
# ---------------------------------------------------------------------------


@dataclass
class ExperimentResult:
    execution_run_id: Optional[str] = None
    metrics: Optional[dict] = None
    benchmark_artifact_paths: tuple = ()
    code_diff_path: Optional[str] = None
    test_results_summary: Optional[str] = None
    # Mirrors research/db.py's two axes exactly (same value sets) — this is
    # a MIRROR for spec-level bookkeeping, not a replacement; the DB row
    # remains the single source of truth for a QUEUED/RUNNING experiment's
    # live state.
    execution_status: Optional[str] = None
    research_verdict: Optional[str] = None
    conclusion: Optional[str] = None
    limitations: tuple = ()

    def is_empty(self) -> bool:
        """True iff no result-only field has been populated — the state
        every ExperimentResult must be in until execution actually happens."""
        return self == ExperimentResult()


_RESULT_FIELD_NAMES = frozenset(f.name for f in fields(ExperimentResult))


def check_no_result_fields_in_proposal(data: dict) -> None:
    """Raise ProposalContainsResultFieldsError if `data` (a raw dict destined
    to become an ExperimentProposal, e.g. LLM- or human-authored JSON)
    contains any key that belongs to ExperimentResult. This is the concrete
    mechanism behind Phase F item #3: it is structurally impossible to smuggle
    an observed metric/verdict/conclusion into a proposal through this path."""
    offending = sorted(_RESULT_FIELD_NAMES & set(data.keys()))
    if offending:
        raise ProposalContainsResultFieldsError(
            "proposal payload contains result-only field(s), which must "
            f"never be pre-registered: {offending}. A proposal is pre-"
            "registration only — observed metrics/verdicts/conclusions may "
            "only be recorded on ExperimentResult, after real execution."
        )


# ---------------------------------------------------------------------------
# ExperimentProposal — everything pre-registered, frozen once approved.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExperimentProposal:
    # -- Identity --
    schema_version: str
    experiment_id: str
    title: str
    family: str

    # -- Research basis --
    hypothesis: str
    motivation: str
    research_question: str
    evidence_references: tuple = ()  # Phase-E memory_db.py record IDs (MEM-XXXX)
    prior_experiment_ids: tuple = ()  # EXP-XXXX ids this proposal builds on

    # -- Baseline (must resolve to a real artifact, not hand-typed numbers) --
    baseline_run_id: str = ""
    baseline_metrics: dict = field(default_factory=dict)

    # -- Variables --
    independent_variables: tuple = ()
    dependent_variables: tuple = ()
    controlled_variables: dict = field(default_factory=dict)

    # -- Methodology --
    procedure: str = ""
    dataset_version: str = ""
    model_config_ref: str = ""
    implementation_scope: str = ""
    expected_artifacts: tuple = ()
    reproducibility_requirements: str = ""

    # -- Controls --
    control_condition: str = ""
    baseline_comparison: str = ""
    isolation_requirements: str = ""

    # -- Success criteria (structured, machine-checkable) --
    # e.g. {"min_meaningful_delta": 0.03, "precision_floor": 0.75,
    #       "max_latency_regression_pct": 50.0, "required_tests_pass": True,
    #       "sample_size_requirements": {"person": 100}}
    success_criteria: dict = field(default_factory=dict)

    # -- Risk / safety --
    production_impact: bool = False
    production_impact_description: str = ""
    data_privacy_classification: str = "NONE"  # NONE | INTERNAL | PRIVATE_USER_DATA
    external_api_required: bool = False
    mac_iphone_required: bool = False
    # Phase-I CANDIDATE-0002 admission-boundary audit (section 11): before
    # this fix, a proposal had NO way to describe "this requires CoreML
    # replacement" / "this requires a signing/distribution change"
    # independently of the (always-False) approval flag -- the requirement
    # and the approval were structurally indistinguishable, since only the
    # approval field existed. These two REQUIREMENT fields close that gap,
    # mirroring mac_iphone_required/external_api_required's existing
    # pattern (requirement flag, LLM-supplied, separate from the approval
    # flag it gates). LLM-authorable; never implies the corresponding
    # *_approved flag, which remains hard-coded False regardless.
    coreml_replacement_required: bool = False
    signing_distribution_change_required: bool = False
    compute_resource_estimate: dict = field(default_factory=dict)
    allowed_path_scope: tuple = ()  # extends experiment_registry.FamilySpec.allowed_path_prefixes

    # -- Expected interpretation (pre-registration) --
    supports_hypothesis_if: str = ""
    rejects_hypothesis_if: str = ""
    inconclusive_if: str = ""

    # -- Human authority flags (Phase F item #10; default False = not approved) --
    production_swift_modification_approved: bool = False
    coreml_model_replacement_approved: bool = False
    new_training_approved: bool = False
    private_user_data_use_approved: bool = False
    external_upload_approved: bool = False
    mac_iphone_deployment_approved: bool = False
    signing_distribution_change_approved: bool = False

    # -- Rejected-hypothesis acknowledgment (Phase F item #8) --
    acknowledges_rejected_hypothesis_ids: tuple = ()
    materially_new_rationale: str = ""

    def __post_init__(self) -> None:
        if not EXPERIMENT_ID_RE.match(self.experiment_id):
            raise ValueError(
                f"malformed experiment_id {self.experiment_id!r} — must match EXP-\\d{{4}}"
            )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ExperimentProposal":
        """Construct a proposal from a raw dict (e.g. parsed JSON). Rejects
        (does not silently drop) any result-only field present in `data` —
        see check_no_result_fields_in_proposal."""
        check_no_result_fields_in_proposal(data)
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data.keys()) - known)
        if unknown:
            raise ValueError(f"unknown proposal field(s): {unknown}")
        # tuples round-trip as lists through JSON — normalize back.
        normalized = dict(data)
        for f in fields(cls):
            if f.default == () and isinstance(normalized.get(f.name), list):
                normalized[f.name] = tuple(normalized[f.name])
        return cls(**normalized)


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def _proposal_hash(proposal: ExperimentProposal, *, exclude: frozenset = frozenset()) -> str:
    data = proposal.to_dict()
    for k in exclude:
        data.pop(k, None)
    return hashlib.sha256(_canonical_json(data).encode("utf-8")).hexdigest()


# Fields added to ExperimentProposal AFTER research/experiment_specs/
# EXP-0001..0005.json were originally frozen (Phase-I CANDIDATE-0002
# admission-boundary audit, section 11: coreml_replacement_required/
# signing_distribution_change_required). Explicit and auditable, never
# derived automatically -- a historical frozen_hash computed before one of
# these fields existed is still considered valid IF the loaded proposal's
# value for that field is exactly its listed default (i.e. the field
# simply didn't exist at freeze time, nothing was silently changed). If a
# historical record's value differs from the default, this grace does NOT
# apply and FrozenProposalTamperedError still raises -- this narrows the
# tolerance to exactly "a new field appeared", never to "an old field was
# edited outside amend()".
_FIELDS_ADDED_AFTER_PHASE_F_FREEZE: dict = {
    "coreml_replacement_required": False,
    "signing_distribution_change_required": False,
}


# ---------------------------------------------------------------------------
# Amendment — append-only, traceable record of a post-freeze change.
# ---------------------------------------------------------------------------


@dataclass
class Amendment:
    field_name: str
    old_value: Any
    new_value: Any
    reason: str
    approved_by: str
    timestamp: str = field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# ExperimentSpec — the full proposal+result container.
# ---------------------------------------------------------------------------


@dataclass
class ExperimentSpec:
    proposal: ExperimentProposal
    result: ExperimentResult = field(default_factory=ExperimentResult)
    status: str = "DRAFT"
    amendments: list = field(default_factory=list)  # list[Amendment]
    frozen_hash: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status not in SPEC_STATUSES:
            raise ValueError(f"invalid spec status: {self.status!r} (must be one of {SPEC_STATUSES})")

    # -- freeze / amend -----------------------------------------------------

    def freeze(self, to_status: str = "VALIDATED") -> None:
        """Move status from DRAFT to VALIDATED or APPROVED and snapshot a
        hash of the current proposal payload. From this point on, the
        proposal's content may only change via amend()."""
        if to_status not in ("VALIDATED", "APPROVED"):
            raise SpecStatusError(f"freeze() target must be VALIDATED or APPROVED, got {to_status!r}")
        if self.status != "DRAFT" and self.frozen_hash is not None:
            # re-freezing (e.g. VALIDATED -> APPROVED) is fine as long as the
            # payload hasn't silently drifted since the last freeze.
            self.verify_integrity()
        self.status = to_status
        self.frozen_hash = _proposal_hash(self.proposal)

    def is_frozen(self) -> bool:
        return self.status != "DRAFT"

    def verify_integrity(self) -> None:
        """Raise FrozenProposalTamperedError if the current proposal payload
        does not match the hash recorded at freeze time.

        Tolerates additive schema evolution (Phase-I CANDIDATE-0002
        admission-boundary audit): if a field in
        _FIELDS_ADDED_AFTER_PHASE_F_FREEZE didn't exist when this record was
        originally frozen, its value loads as the dataclass default -- that
        alone must never be mistaken for tampering. The hash is recomputed
        with those fields excluded and compared again ONLY as a fallback;
        if the loaded value for any such field differs from its default,
        this fallback does not apply and a genuine mismatch still raises."""
        if self.frozen_hash is None:
            return
        current = _proposal_hash(self.proposal)
        if current == self.frozen_hash:
            return
        at_default = all(
            getattr(self.proposal, name, default) == default
            for name, default in _FIELDS_ADDED_AFTER_PHASE_F_FREEZE.items()
        )
        if at_default:
            legacy = _proposal_hash(self.proposal, exclude=frozenset(_FIELDS_ADDED_AFTER_PHASE_F_FREEZE))
            if legacy == self.frozen_hash:
                return
        raise FrozenProposalTamperedError(
            f"{self.proposal.experiment_id}: proposal payload does not match its "
            f"frozen_hash — recorded={self.frozen_hash} current={current}. A frozen "
            "proposal must only change via ExperimentSpec.amend()."
        )

    def amend(self, field_name: str, new_value: Any, reason: str, approved_by: str = "human via CLI") -> Amendment:
        """Create a new versioned proposal record with `field_name` changed
        to `new_value`, and append a fully traceable Amendment (old value,
        new value, reason, timestamp, approved_by) to self.amendments.
        Requires the spec to already be frozen (VALIDATED/APPROVED) — amend()
        is the ONLY legal way to change a frozen proposal's content; direct
        attribute assignment on the frozen dataclass raises on its own
        (dataclasses.FrozenInstanceError), and this method is the sanctioned
        path around that."""
        if self.status == "DRAFT":
            raise SpecStatusError(
                "amend() requires a frozen spec (VALIDATED/APPROVED) — a DRAFT "
                "proposal may simply be edited directly and re-frozen."
            )
        if not reason:
            raise ValueError("amend() requires a non-empty reason")
        self.verify_integrity()
        if not hasattr(self.proposal, field_name):
            raise ValueError(f"unknown proposal field: {field_name!r}")
        old_value = getattr(self.proposal, field_name)
        self.proposal = replace(self.proposal, **{field_name: new_value})
        amendment = Amendment(
            field_name=field_name, old_value=old_value, new_value=new_value,
            reason=reason, approved_by=approved_by,
        )
        self.amendments.append(amendment)
        self.frozen_hash = _proposal_hash(self.proposal)
        return amendment

    # -- serialization (deterministic) --------------------------------------

    def to_dict(self) -> dict:
        return {
            "proposal": self.proposal.to_dict(),
            "result": asdict(self.result),
            "status": self.status,
            "amendments": [asdict(a) for a in self.amendments],
            "frozen_hash": self.frozen_hash,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, default=str)

    @classmethod
    def from_dict(cls, data: dict) -> "ExperimentSpec":
        from research.experiment_spec_migrations import migrate_proposal_dict

        proposal_data = migrate_proposal_dict(dict(data["proposal"]))
        proposal = ExperimentProposal.from_dict(proposal_data)
        result_data = dict(data.get("result") or {})
        for k in ("benchmark_artifact_paths", "limitations"):
            if isinstance(result_data.get(k), list):
                result_data[k] = tuple(result_data[k])
        result = ExperimentResult(**result_data)
        spec = cls(
            proposal=proposal,
            result=result,
            status=data.get("status", "DRAFT"),
            amendments=[Amendment(**a) for a in data.get("amendments", [])],
            frozen_hash=data.get("frozen_hash"),
        )
        if spec.frozen_hash is not None:
            spec.verify_integrity()
        return spec

    @classmethod
    def from_json(cls, text: str) -> "ExperimentSpec":
        return cls.from_dict(json.loads(text))
