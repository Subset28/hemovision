# CANDIDATE-0001 Postmortem

**Historical result unchanged and immutable**: CANDIDATE-0001 remains
`REJECTED`. Not registered. Not queued. Not EXP-0006.
`research/candidates/CANDIDATE-0001/` was not modified by this audit
(confirmed: `git status`/`git diff` on that path show nothing). This
document explains what happened, whether the rejection reason was
correctly reasoned, and what an equivalent future proposal would receive
under corrected validator semantics.

## 1. Exact rejection cause (from the preserved artifact, verbatim)

`research/candidates/CANDIDATE-0001/CANDIDATE-0001-proposal.json`:

```
mac_iphone_required: True
mac_iphone_deployment_approved: False
family: "temporal_pipeline"
allowed_path_scope: ["ios/", "research/", "experiments/"]
implementation_scope: "Offline video processing script using PyTorch/OpenCV
  for detection and temporal filtering; no changes to model weights or
  inference code."
dataset_version: "PREREQUISITE: OmniSight-specific video evaluation dataset
  (docs/DATASETS.md Section 8) must be constructed and versioned before
  this experiment can run, as current baseline uses static Images V7
  (MEM-0017) which lacks temporal coherence."
compute_resource_estimate: {"estimated_gpu_hours": 4, "gpu": "RTX 3070 Ti"}
```

No field anywhere states or implies the system is currently attempting to
execute Mac/iPhone/device work — `implementation_scope` explicitly says
"offline ... no changes to model weights or inference code," and
`production_impact: False`. The proposal describes a FUTURE requirement,
never a present action.

Re-running `research/experiment_validator.py::validate()` against this
exact preserved artifact (read-only, no mutation) reproduces the original
result precisely:

```
is_valid: False
errors: [UNAPPROVED_MAC_IPHONE_DEPLOYMENT]
needs_human_review: [SCIENTIFIC_MERIT]
```

## 2. Validator trace (as it existed at the time of the live cycle)

`LLM ProposalResponse` (no `mac_iphone_deployment_approved` field — cannot
exist) → `_build_proposal()` hardcodes `mac_iphone_deployment_approved=False`
regardless of input → `ExperimentProposal(mac_iphone_required=True,
mac_iphone_deployment_approved=False)` → `experiment_validator._validate_proposal()`:

```python
if p.mac_iphone_required and not p.mac_iphone_deployment_approved:
    result.add("ERROR", "UNAPPROVED_MAC_IPHONE_DEPLOYMENT", ...)
```

**Confirmed root cause**: the validator treated `mac_iphone_required=True
AND approval=False` as an `ERROR` (structural/scientific invalidity),
identical in kind to `MISSING_HYPOTHESIS` or `UNKNOWN_FAMILY`. This is
architecturally wrong: `mac_iphone_required=True` with
`mac_iphone_deployment_approved=False` is the ONLY possible state an
honest, non-fabricating autonomous proposal can ever be in — since the
approval flag is hard-coded `False` at every construction site (Phase F
invariant, correctly never touched by this fix), **the pre-existing check
made it structurally impossible for any temporal_pipeline or
application_decision_logic proposal to ever pass validation**, regardless
of scientific quality. Same defect, by construction, applied to
`production_impact`, `data_privacy_classification=="PRIVATE_USER_DATA"`,
and `external_api_required`.

This conflated four genuinely distinct concepts named in this round's
authorization:
- **A** (proposal states a future requirement) and **B** (proposal requests
  approval) are naturally expressed by `mac_iphone_required=True` alone —
  there is no separate "requests approval" field, and none is needed; a
  human reading `mac_iphone_required=True, ...approved=False` already knows
  a request exists.
- **C** (approval actually received) is exactly `mac_iphone_deployment_approved`.
- **D** (system currently executing device work) has **no corresponding
  field or code path in Phase H/Phase I at all** — no code anywhere
  attempts Mac/iPhone/device execution, so D was never actually at risk;
  the old validator was blocking on a stand-in for D (queue/execution
  readiness) at the wrong stage (proposal creation).

## 3. Root cause

`is_valid` (proposal-stage structural/scientific validity) and
`is_queue_eligible` (queue/execution admission) were **the same boolean**
(`is_queue_eligible(result) == result.is_valid`, zero `ERROR`s). Every
authority-gated condition raised `ERROR`, so there was no way for a
proposal to be "scientifically sound but operationally pending" — it was
either fully queue-ready or flatly invalid, with no state in between.

## 4. Code changed — yes

`research/experiment_validator.py`:
- New level `NEEDS_HUMAN_APPROVAL`, added alongside the existing
  `ERROR`/`WARNING`/`NEEDS_HUMAN_REVIEW`, with a new
  `ValidationResult.needs_human_approval` property.
- `UNAPPROVED_PRODUCTION_IMPACT`, `UNAPPROVED_MAC_IPHONE_DEPLOYMENT`,
  `UNAPPROVED_PRIVATE_DATA_USE`, `UNAPPROVED_EXTERNAL_API` all changed from
  `ERROR` to `NEEDS_HUMAN_APPROVAL`.
- New `UNAPPROVED_NEW_TRAINING` check (`family=="training_data"` and
  `not new_training_approved`) — generalizing the same fix to training,
  which had no gate at all before (see §7 gap note).
- `is_valid` **unchanged in definition** (zero `ERROR`s) — now correctly
  excludes approval-only issues.
- `is_queue_eligible()` **changed**: now requires zero `ERROR`s **AND**
  zero `NEEDS_HUMAN_APPROVAL` issues — queue admission is strictly harder
  to satisfy than before for any proposal missing a required approval,
  never weaker.

`research/phase_i/loop.py`: no change to the admissibility gate itself (it
already used `is_valid`, not `is_queue_eligible` — this was already the
better of the two, and now `is_valid` means what it should). Added
`_authorization_assessment()` — a deterministic `REQUIRED`/`APPROVED`/
`NOT_REQUIRED` status per Phase F flag, included in every `-final.json`
report going forward.

## 5. New validation-layer semantics

| Layer | Question answered | Mechanism |
|---|---|---|
| Structural/scientific validity | Is the proposal internally sound and falsifiable? | `validate()`'s `ERROR`-level checks; `is_valid` |
| Authorization assessment | Which approvals does this proposal need, and are they granted? | `validate()`'s `NEEDS_HUMAN_APPROVAL`-level checks; `_authorization_assessment()` |
| Review eligibility | May the reviewer critique this proposal? | `is_valid` (Phase I loop's admissibility gate) — **NEEDS_HUMAN_APPROVAL no longer blocks this** |
| Queue admission | May this become an experiment/enter the queue? | `is_queue_eligible()` — requires **both** zero `ERROR`s and zero `NEEDS_HUMAN_APPROVAL` |
| Execution admission | May the requested operation run now? | No code path exists for Mac/iPhone/training/external-data/production execution anywhere in `research/`/`benchmark/` today — structurally absent, not merely gated. Recommendation for whenever such a path is built: recheck the relevant approval flag(s) immediately before the operation, not only at queue time. |

Five conceptually distinct questions, four of them (all but "execution
admission", which doesn't exist yet) with a concrete mechanism today.

## 6. Behavior of all 7 human approval flags at proposal stage

| Flag | Deterministic trigger exists? | Behavior |
|---|---|---|
| `production_swift_modification_approved` | Yes (`production_impact`) | `NEEDS_HUMAN_APPROVAL` if required and not approved |
| `mac_iphone_deployment_approved` | Yes (`mac_iphone_required`) | `NEEDS_HUMAN_APPROVAL` if required and not approved |
| `new_training_approved` | Yes (`family=="training_data"`, added this round) | `NEEDS_HUMAN_APPROVAL` if required and not approved |
| `private_user_data_use_approved` | Yes (`data_privacy_classification=="PRIVATE_USER_DATA"`) | `NEEDS_HUMAN_APPROVAL` if required and not approved |
| `external_upload_approved` | Yes (`external_api_required`) | `NEEDS_HUMAN_APPROVAL` if required and not approved |
| `coreml_model_replacement_approved` | **No** — no schema field signals "this proposal replaces CoreML" | Always hard-coded `False`; no `NEEDS_HUMAN_APPROVAL` trigger exists. Documented gap, not silently declared safe — see §"Remaining Phase I blockers." |
| `signing_distribution_change_approved` | **No** — no schema field signals "this proposal changes signing/distribution" | Same as above. |

All 7 remain hard-coded `False` in `_build_proposal` regardless of LLM
output, unconditionally, before and after this fix — **no approval was
granted or made easier to grant by this change.**

## 7. Queue-gate behavior

Unchanged in spirit, strictly enforced correctly for the first time:
`is_queue_eligible()` still requires zero `ERROR`s (as before) and now ALSO
requires zero `NEEDS_HUMAN_APPROVAL` issues. A proposal cannot become
queue-eligible by having a "clean" `is_valid=True` alone — this closes what
would otherwise have been a real gap the fix could have introduced (moving
these checks out of `ERROR` without also gating `is_queue_eligible` on the
new level would have made unapproved device/training/production/external
work **easier** to queue, which is the opposite of the intent).

## 8. Execution-gate behavior

No code path in this repository currently executes Mac/iPhone/device work,
new training, external-data acquisition, or production Swift modification —
`research/runners.py`'s `RUNNERS` dict only implements EXP-0001/EXP-0002
(both Windows-benchmarkable, `OFFLINE_SIMULATABLE`). There is nothing to
"recheck before execution" yet because there is no execution path for these
categories at all. This is a structural absence (fail-closed by omission),
not an implemented-and-verified gate — flagged honestly as a remaining gap
for whenever such a runner is built (see §"Remaining Phase I blockers").

## 9. Reviewer eligibility when approvals are missing

**Now yes** — `research/phase_i/loop.py`'s admissibility check uses
`proposal_validation.is_valid`, which (after this fix) is `True` for a
scientifically sound proposal with a missing approval. Such a candidate
now proceeds to the reviewer exactly as this round's authorization
recommended (§10): "there is value in letting the reviewer assess the
design before a human decides whether the requested expensive/device
action deserves authorization." Safety remains fail-closed because
`is_queue_eligible` (checked only for reporting `queue_eligible_in_principle`
in the final artifact, never for anything that actually queues) still
requires the approval, and nothing in Phase I ever calls
`queue_experiment_from_spec` regardless.

## 10. Candidate-state semantics

Verified from the architecture rather than assumed: **`FINALIZED` is the
correct terminal state for a scientifically-sound-but-approval-pending
candidate, not `BLOCKED`.**

`BLOCKED` (per `research/phase_i/candidate_state.py`'s own docstring, and
`reports/phase_i/PHASE_I_IMPLEMENTATION.md`) means "the operational gate
(PAUSED/STOPPED) refused an attempt" — a **temporary, infrastructure-level**
condition with no scientific content, deliberately non-terminal, and
designed to resume automatically the moment operational state returns to
`RUNNING`, with **no human decision required to un-block it**.

A proposal awaiting `mac_iphone_deployment_approved` is categorically
different: it is fully reviewed and complete, and the only thing missing is
a **deliberate, out-of-band human authorization decision** that must never
be granted automatically just because the operational state happens to be
`RUNNING`. Reusing `BLOCKED` for this would risk exactly the conflation
this whole audit is about — implying "wait a moment and it'll resume
itself" when the true meaning is "a human must explicitly decide this."
`FINALIZED` — "a scientifically reviewed candidate report awaiting human
decision" — already says precisely the right thing, and now correctly
carries the missing-approval fact via `authorization_assessment` in the
`-final.json` artifact instead of hiding it inside a rejection.

## 11. What state an equivalent future CANDIDATE-0001 would reach

Under corrected semantics, re-running the identical researcher output
(hypothetically, not actually re-run — see §13):
1. `validate()` → `is_valid=True` (was `False`), `needs_human_approval=[UNAPPROVED_MAC_IPHONE_DEPLOYMENT]`.
2. Admissible → proceeds to the reviewer (this did NOT happen for the real
   CANDIDATE-0001, which stopped after 1 call).
3. If the reviewer said ACCEPT → `FINALIZED`, `-final.json` would show
   `authorization_assessment: {"mac_iphone_deployment_approved": "REQUIRED", ...}`
   and `queue_eligible_in_principle: false`.
4. **`actually_queued` would still be `false`.** No behavior changed that
   would let this candidate reach the queue or execute.

## 12. CANDIDATE-0001 history — immutable

Confirmed via `git status`/`git diff` on `research/candidates/`: zero
changes. The artifact, state file, and its `REJECTED` result are exactly as
the live cycle produced them. This document supersedes nothing on disk —
it is analysis, not a correction of history.

## 13. Video-dataset prerequisite — exact representation

`dataset_version` field, verbatim: *"PREREQUISITE: OmniSight-specific video
evaluation dataset (docs/DATASETS.md Section 8) must be constructed and
versioned before this experiment can run, as current baseline uses static
Images V7 (MEM-0017) which lacks temporal coherence."*

This correctly represents the dataset as **nonexistent**, an **explicit
prerequisite**, referencing where its future construction is expected to be
documented (`MEM-0025`, cited in `procedure` and `isolation_requirements`).
No claim anywhere states or implies the dataset currently exists.

**One residual gap found by this audit** (not present in the original
rejection reason, and not itself a validator defect): the proposal sets
`data_privacy_classification: "NONE"` while describing a dataset built from
"video streams" in an accessibility-camera context — plausibly involving
real people and potentially private imagery once actually constructed. The
proposal does not flag this as a privacy consideration for the *dataset
construction step itself* (as opposed to the experiment's own inference-only
use of an already-built dataset, which is legitimately NONE). This is a
scientific/completeness gap worth a human reviewer's attention if this
direction is ever pursued further — not fabrication, not a validator bug,
and not something this audit corrects (no dataset is being built).

## 14. No nonexistent dataset was fabricated

Confirmed: the researcher never asserted the video-evaluation dataset
exists, never referenced fabricated metrics computed from it, and
`compute_resource_estimate`/`expected_artifacts` describe planned, not
already-produced, outputs.

## 15. Temporal-methodology details (from `procedure`, verbatim)

1. Extract frame sequences from the (not-yet-built) video evaluation set.
2. Run the baseline detector at `conf=0.4` on each frame independently.
3. **"Apply temporal filter: a detection is retained only if the same
   class (Person) is detected in ≥2 of 3 consecutive frames (using spatial
   overlap via IoU > 0.3 for association)."**
4. Compute `person.recall`/`hazard.precision` against ground truth.
5. Compare to the static-image baseline.

## 16. Does the 2-of-3 hypothesis actually recover TRUE_DETECTOR_MISS cases?

**No — this is a real, independent scientific flaw, confirmed by close
reading of the procedure, not hidden by the authorization rejection.**

Step 3 as written is a **confirmation/suppression filter**: a per-frame
detection is *retained* only if corroborated by ≥2-of-3 frames. Mechanically,
such a filter can only ever **remove** detections that lack neighbor
support — it has no operation that **adds** a detection to a frame where
the per-frame detector produced none. A `TRUE_DETECTOR_MISS` is, by
definition, a frame with **zero** detections above threshold; a filter that
only ever prunes existing detections cannot produce one where none existed.

For this design to actually "recover" a miss, it would need one of:
- **Persistence/carry-forward**: if Person is detected in frame *N-1* and
  *N+1* but missed in frame *N*, explicitly propagate/interpolate a
  detection into frame *N*.
- **Tracking-assisted recovery**: maintain a track across frames and count
  a "detection" for evaluation purposes when the track is alive even if a
  given frame's raw detector output is empty.

The proposal describes **neither** — it describes confirmation filtering
only. As written, the mechanism is most likely to **reduce** apparent
recall (by discarding true-positive but temporally-isolated detections)
while potentially improving precision (by discarding false-positive
temporally-isolated detections) — roughly the opposite emphasis from what
the hypothesis claims to test.

**This is a genuine internal inconsistency between the stated hypothesis
and the described mechanism**, independent of and in addition to the
authorization issue. Had this candidate reached the reviewer under
corrected semantics, this is exactly the kind of confounding/mechanism flaw
an independent reviewer is supposed to catch (`scientific_validity_assessment`,
`confounding_notes` in `ReviewerCritique`) — it never got the chance to,
because the (incorrect) authorization-based rejection stopped the cycle
one step too early. This is itself evidence for why review eligibility
should not depend on approval status (§9/§10 above): the authorization
rejection didn't just block queueing (correct), it also **prevented the
system from surfacing a real methodological flaw** (incorrect side effect).

## 17. Remaining Phase I blockers

- **No deterministic trigger for `coreml_model_replacement_approved` or
  `signing_distribution_change_approved`** — no schema field exists for an
  autonomous proposal to declare "this requires CoreML replacement" or
  "this requires a signing/distribution change." Both flags remain
  hard-coded `False` (safe), but a proposal that implicitly required one of
  these would not get an explicit `NEEDS_HUMAN_APPROVAL` nudge today. Not
  observed in practice yet (no proposal has needed this), documented as a
  known gap rather than silently assumed safe.
- **No execution-gate recheck exists** because no execution code path for
  device/training/external-data/production work exists yet (§8) — correct
  by absence today, but must be added the moment any such runner is built,
  not assumed to carry over automatically.
