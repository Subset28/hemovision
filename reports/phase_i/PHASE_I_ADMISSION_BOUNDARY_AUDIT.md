# Phase I Admission-Boundary Audit (CANDIDATE-0002)

Zero live LLM completion calls were made to produce this document.
CANDIDATE-0001 and CANDIDATE-0002 are unmodified (confirmed: `git status`/
`git diff` on `research/candidates/` show nothing throughout this audit and
its code fixes).

## 1. CANDIDATE-0002's two rejection traces

Re-running `research/experiment_validator.py::validate()` against the
preserved, untouched `CANDIDATE-0002-proposal.json` reproduces exactly:

```
is_valid: False
errors:
  - MAC_IPHONE_REQUIRED_MISMATCH: family 'model_variant' requires
    REQUIRES_MAC per the registry, but mac_iphone_required=False on the
    proposal.
  - UNACKNOWLEDGED_REJECTED_HYPOTHESIS: proposal's family+independent_variables
    closely matches rejected hypothesis MEM-0014 (experiment EXP-0005) --
    set acknowledges_rejected_hypothesis_ids...
needs_human_review: [SCIENTIFIC_MERIT]
candidate_history_conflicts: []  (correctly zero -- different family than CANDIDATE-0001)
```

### A. Missing `acknowledges_rejected_hypothesis_ids`

**Trace**: `find_rejected_hypothesis_conflicts()` matched CANDIDATE-0002's
`independent_variables` ("model_checkpoint (yolov8m-oiv7 vs yolov11m)")
against MEM-0014's stored `independent_variable` text via family+keyword
overlap → `[(EXP-0005, MEM-0014)]`. The proposal's own
`acknowledges_rejected_hypothesis_ids` was `[]`, despite `prior_experiment_ids`
containing `EXP-0005` and `evidence_references` containing `MEM-0014`, and
despite a substantive `materially_new_rationale` explaining the difference
from EXP-0005/EXP-0004.

**Classification: LLM_SUPPLIED, and correctly so — this was a genuine
researcher-compliance gap, not a false rejection.**

The researcher_proposal.md prompt explicitly instructs: *"you MUST either
propose something genuinely different, or explicitly set
`acknowledges_rejected_hypothesis_ids` to the relevant EXP-XXXX/MEM-XXXX
id(s)."* The researcher had this instruction, had already identified the
correct ids (they appear in `prior_experiment_ids`/`evidence_references`),
and simply didn't also populate the one field that exists specifically for
this purpose. This is unlike the mac_iphone_required gap (§ B below) —
there is no undocumented registry fact to memorize here; the field's
purpose was stated plainly and the researcher had already done the
substantive work of identifying the right ids, just not in the right field.

**Considered and rejected**: broadening the "acknowledged" set to include
`prior_experiment_ids`/`evidence_references` (Option B/a loose form of C in
the authorization's framing). Rejected because those two fields are
populated by *every* proposal that cites prior work as normal background
evidence — including proposals that ARE just quietly repeating a rejected
direction while citing it as "inspiration." Auto-satisfying acknowledgment
from fields that don't specifically signal "I am aware this may look like a
repeat and here is why it isn't" would materially weaken the exact
protection this field exists to provide. **Decision: keep Model A
(explicit, LLM-supplied, dedicated field) unchanged.**

### B. `mac_iphone_required=False` conflicting with `model_variant`'s registry requirement

**Trace**: `_build_proposal()` (pre-fix) set `mac_iphone_required=pr.mac_iphone_required`
directly from LLM output. The researcher wrote `False`.
`research/experiment_registry.py::REGISTRY["model_variant"]` declares
`production_validation_requirement="REQUIRES_MAC"` (alongside
`windows_evaluatable=True` — Windows-side screening is fine, but eventual
production adoption needs device validation). `validate()`'s
`MAC_IPHONE_REQUIRED_MISMATCH` check compares the proposal's claim against
this registry fact and found a mismatch.

**Classification: DETERMINISTICALLY_DERIVED — this WAS a false rejection**
caused by asking the researcher to reproduce metadata OmniLab already knows
authoritatively, exactly the pattern this round's authorization warned
against (§3). Confirmed by precedent: `research/experiment_specs/EXP-0005.json`
(a real, historically-executed, Windows-only-screened `model_variant`
experiment) was itself correctly backfilled with `mac_iphone_required=True`
at Phase F time — establishing that in this codebase, `mac_iphone_required`
means "this family's eventual production validation needs a device,"
**not** "this specific screening run needs a device right now." The
researcher was never told this registry semantic anywhere in its prompt.

**Fix applied**: `research/dry_run/pipeline.py::_family_requires_mac_iphone()`
derives the deterministic floor from the registry; `_build_proposal()` now
computes `mac_iphone_required = pr.mac_iphone_required OR
_family_requires_mac_iphone(pr.family)` — an OR, never a downgrade, so an
LLM that independently flags `True` for an out-of-band reason is never
silently reset to `False`.

## 2. Distinguishing the three device-related concepts (section 4)

- **Eventual device validation required if candidate succeeds** — this is
  what `mac_iphone_required=True` now deterministically and correctly
  represents for `model_variant`/`temporal_pipeline`/`application_decision_logic`.
- **Device work required during the proposed screening experiment itself**
  — NOT what `mac_iphone_required` means for these families; `model_variant`
  is `windows_evaluatable=True`, meaning the actual proposed screening
  (CANDIDATE-0002's 4-condition Windows benchmark run) needs no device at
  all. No separate field currently distinguishes "needs device now" from
  "needs device eventually" — for the 3 device-adjacent families, "now" is
  always `False` and "eventually" is always `True` per the registry, so one
  field suffices today. If a future family existed where "screening itself"
  legitimately needs a device, a second field would be warranted; not
  needed yet.
- **Approval to perform device work now** — `mac_iphone_deployment_approved`,
  entirely separate, always `False`, never touched by this fix.

## 3. Field-responsibility matrix

| Field | Classification | Notes |
|---|---|---|
| `family` (experiment_family) | LLM_SUPPLIED | Scientific choice; validated against the registry's known family list (ERROR if unknown) |
| `hypothesis` | LLM_SUPPLIED | |
| mechanism (embedded in `hypothesis`/`motivation` prose) | LLM_SUPPLIED | No dedicated schema field; free text only — see §7 recommendation |
| `independent_variables` | LLM_SUPPLIED | |
| `control_condition` / `controlled_variables` | LLM_SUPPLIED | |
| failure bucket targeted (embedded in `motivation`/`dependent_variables`) | LLM_SUPPLIED | No dedicated enum field tying a proposal to the canonical TRUE_DETECTOR_MISS/LOW_CONFIDENCE_PERSON/SEMANTIC_CLASS_CONFUSION/LOCALIZATION_FAILURE taxonomy — free text only |
| `dataset_version` | HYBRID | LLM states a real value or an explicit PREREQUISITE sentence; validator placeholder-rejects bare "TBD"/"unknown" (Phase H fix) |
| `isolation_requirements` | HYBRID | LLM designs the isolation procedure (scientific judgment); validator placeholder-rejects garbage |
| `model_config_ref` | HYBRID | LLM states a real value or PREREQUISITE; not cross-checked against `benchmark/results/baseline/run_metadata.json`'s `model_sha256` today (a possible future enhancement, not implemented) |
| `compute_resource_estimate` | LLM_SUPPLIED | Explicitly documented as a proposal-stage estimate, never a measured value |
| `mac_iphone_required` | **DETERMINISTICALLY_DERIVED** (as of this fix) | Floored from `experiment_registry`; OR-ed with LLM's own claim, never downgraded |
| `production_impact` | LLM_SUPPLIED | Judgment call on whether the experiment touches production |
| `external_api_required` | LLM_SUPPLIED | Also covers "external data acquisition" — Phase F does not have a separate field distinguishing "calls an external API" from "acquires external data"; both are represented by this one flag today |
| `data_privacy_classification` | LLM_SUPPLIED | Enum (`NONE`/`INTERNAL`/`PRIVATE_USER_DATA`) |
| `coreml_replacement_required` | LLM_SUPPLIED | **New this round** — closes the representation gap (§6) |
| `signing_distribution_change_required` | LLM_SUPPLIED | **New this round** |
| `acknowledges_rejected_hypothesis_ids` | LLM_SUPPLIED | Deliberately kept LLM-supplied (§1.A) — the deterministic layer independently *detects* conflicts (`find_rejected_hypothesis_conflicts`) and *verifies* whether they were acknowledged, but never invents or auto-populates an acknowledgment |
| 7 human-authority `*_approved` flags | HUMAN_SUPPLIED | Always hard-coded `False` at every construction site; only `ExperimentSpec.amend()` (human-invoked) can ever change one |
| `allowed_path_scope` | DETERMINISTICALLY_DERIVED | From `experiment_registry` (Phase H fix) |
| `baseline_run_id` | DETERMINISTICALLY_DERIVED | Pipeline parameter (`CANONICAL_BASELINE_RUN_ID`) |
| `baseline_metrics` | DETERMINISTICALLY_DERIVED | Real artifact lookup (Phase H fix) |

## 4. CoreML / signing representation — fixed

Both flags previously had **no** schema field allowing a proposal to
describe the requirement independently of the (always-False) approval
flag — the exact condition the authorization said must be fixed. Added
`coreml_replacement_required`/`signing_distribution_change_required` to
`ExperimentProposal`, `ProposalResponse`, the native structured-output JSON
schema, and two new `NEEDS_HUMAN_APPROVAL` validator checks
(`UNAPPROVED_COREML_REPLACEMENT`, `UNAPPROVED_SIGNING_DISTRIBUTION_CHANGE`).
Approval flags themselves remain human-only and hard-coded `False` —
unaffected.

**Side effect found and fixed**: adding these two fields to
`ExperimentProposal` exposed a latent Phase F freeze/hash defect — any
additive field makes `asdict()`-based `frozen_hash` verification fail for
historical specs (EXP-0001..0005) frozen before the field existed, because
`to_dict()` always materializes every *current* dataclass field regardless
of what the original frozen JSON contained. `research/experiment_spec.py::
verify_integrity()` now tolerates this narrowly: a mismatch is forgiven
*only* if every field in `_FIELDS_ADDED_AFTER_PHASE_F_FREEZE` is at its
class default AND the hash matches once those fields are excluded from the
comparison — genuine tampering of any field, new or original, still raises
`FrozenProposalTamperedError`. This is a real, well-scoped fix for a defect
that would have broken the *next* legitimate schema addition regardless of
this round's specific cause; see `tests/test_schema_hash_tolerance.py`.

## 5. CANDIDATE-0002 scientific audit (no LLM — human/deterministic reading of the preserved artifact)

**Classification: PLAUSIBLE_BUT_UNDERJUSTIFIED**

What's genuinely strong:
- **The design is a full 2×2 factorial**, not a combined-arm-only
  comparison: `procedure` specifies all four conditions — (1) baseline,
  (2) baseline+gamma, (3) YOLO11m alone, (4) YOLO11m+gamma. This DOES allow
  computing main effects and an interaction effect, correctly anticipating
  the concern in the authorization's §6/§7 about combined-only comparisons.
- Guardrails preserved unchanged (`min_meaningful_delta=0.03`,
  `hazard.precision` floor referenced at `0.757` in both
  `supports_hypothesis_if` and `rejects_hypothesis_if`).
- Dataset/checkpoint provenance honestly represented as prerequisites
  (`yolov11m-oiv7.pt` explicitly "does not yet exist"), no fabrication.
- Deterministic train/eval isolation specified (SHA256 hash exclusion).

What's genuinely weak:
- **No mechanistic argument for complementarity is given beyond
  restating that each intervention individually showed *some* effect.**
  The hypothesis asserts YOLO11m addresses "learned-representation
  limitations" and gamma addresses "local contrast deficits" and calls
  these "complementary mechanisms" — but never argues, or proposes to
  check, whether the specific TRUE_DETECTOR_MISS cases each intervention
  recovers are actually different (non-overlapping) subsets. Two
  interventions that each recover the SAME easy subset of misses are not
  complementary merely because both show a nonzero individual effect.
- **The proposal does not engage with EXP-0005's own most severe finding**:
  YOLO11m alone already collapsed `hazard.precision` to ≈0.454 (well below
  the 0.757 floor), and the "precision-matched Person-recall advantage
  largely disappeared" once re-thresholded to match baseline precision —
  i.e., EXP-0005's own conclusion already suggests YOLO11m's apparent
  recall gain may not survive a fair precision-matched comparison at all.
  Gamma preprocessing (an input pixel-intensity remap) has no described,
  or plausible, mechanism for repairing a *model's* systemic
  false-positive/precision problem — precision collapse is a property of
  the model's learned decision boundary and calibration, not of input
  contrast. The hypothesis asserts precision will be "maintained" without
  offering any causal story for why combining with gamma would prevent the
  exact collapse EXP-0005 already measured for YOLO11m alone.
- **Given this, the combined arm is likely — on existing evidence alone,
  before running anything — to fail the same precision guardrail EXP-0005
  already failed**, and the proposal doesn't acknowledge or address this as
  a risk, a competing explanation, or a reason the current design might
  simply reproduce a known negative result under a new label.

Success-criteria adequacy (section 6, last bullet): the SUCCESS CRITERIA
fields are formally adequate — `hazard.precision ≥0.757` is present in both
`supports_hypothesis_if` and `rejects_hypothesis_if`, so ">17/92 recovered"
is never treated as sufficient on its own. The gap is not in the criteria's
structure; it's that the *hypothesis itself* doesn't grapple with strong
existing evidence that the precision guardrail is unlikely to be cleared by
any design that includes YOLO11m as a full replacement checkpoint.

**This is exactly the kind of issue a reviewer should catch** — mechanistic
plausibility, whether prior evidence is honestly engaged with, and whether
a claimed synergy is justified beyond "both individually did something" —
none of it is a schema/structural defect, and none of it should be
deterministically validated. CANDIDATE-0002 never reached a reviewer
(correctly stopped by two genuine admission issues before that stage), so
this analysis substitutes, this one time, for the reviewer step this
specific candidate never got to.

## 6. Factorial-design discipline recommendation

**Do not add a universal deterministic factorial-design requirement.**
CANDIDATE-0002 itself disproves the premise that researchers need to be
forced into this — it independently chose a full 2×2 design without any
instruction to do so. Mandating one universally would be "unnecessary
abstraction" for proposals that don't claim synergy at all (most won't).

**Recommendation**: this remains a **reviewer responsibility**
(`ReviewerCritique.confounding_notes`/`scientific_validity_assessment`
already exist for exactly this). The reviewer prompt (`reviewer_critique.md`)
should be understood to require assessing, when a proposal claims
combined/complementary effects: (a) whether the design includes each
individual-factor arm plus the combination (not combined-only), and (b)
whether a genuine causal/mechanistic argument for interaction — not just
"both showed an effect separately" — is given. No deterministic code
addition is proposed for this; it is exactly the "mechanistic plausibility"
category in §7 below.

## 7. Deterministic-validator vs. reviewer responsibility

| Belongs to deterministic validation | Belongs to reviewer judgment |
|---|---|
| Schema completeness, required fields present | Mechanistic plausibility of a claimed effect |
| Known metric names, contradictory success criteria | Whether a claimed synergy/interaction is justified beyond "both individually helped" |
| Family exists in the registry | Hidden confounding not visible from field values alone |
| `mac_iphone_required` vs. registry mismatch (now floored, not just checked) | Whether an experiment has enough information value to be worth running |
| Redundancy against rejected hypotheses (keyword/family overlap) | Deeper semantic novelty beyond keyword overlap |
| Approval flags present/absent vs. requirement flags (`NEEDS_HUMAN_APPROVAL`) | Whether controls genuinely isolate the claimed causal variable |
| Placeholder-garbage rejection (`TBD`/`unknown`) | Whether prior negative evidence (e.g. EXP-0005's precision collapse) is honestly engaged with |
| Provenance/isolation FIELDS are populated | Whether the isolation PROCEDURE described is actually sufficient |

## 8. Implications for a third cycle

If CANDIDATE-0003 selects `model_variant`/`temporal_pipeline`/
`application_decision_logic`, `mac_iphone_required` will now be correctly
`True` automatically regardless of what the researcher writes — that
specific false-rejection mode cannot recur. `acknowledges_rejected_hypothesis_ids`
remains a genuine researcher-compliance requirement — a future candidate
citing a rejected direction must still populate this field explicitly; that
is not being relaxed, and a repeat of CANDIDATE-0002's exact omission would
still correctly reject. A proposal claiming CoreML replacement or a
signing/distribution change can now say so and receive
`NEEDS_HUMAN_APPROVAL` (reviewable) rather than having no way to represent
the requirement at all.
