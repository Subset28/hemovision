# OmniSight Research Lab — Phase C (experiment infrastructure) + Phase E (research memory)

**Phase D is CLOSED.** EXP-0001 through EXP-0005 all ran to completion
(execution_status=COMPLETED) with FAILED/INCONCLUSIVE research verdicts (one
PASS, EXP-0001, on its confirmatory negative hypothesis — see "EXP-0001's
PASS verdict, explicitly" below). No further experiments will be created
under Phase D; do not create EXP-0006 or unblock/modify any existing
experiment's verdict. See the "Phase E — structured research memory"
section below for what comes after Phase D's closure.

This is orchestration/tooling around the existing, approved `benchmark/`
harness. It is **additive only**. It is a manually-triggered pipeline you
exercise one experiment at a time — it is explicitly NOT unrestricted
autonomous operation (see "What this phase does not do" below).

## Invocation

```
uv run python -m research.cli propose [--dry-run]
uv run python -m research.cli experiment EXP-XXXX
uv run python -m research.cli status
uv run python -m research.cli pause | resume | stop
uv run python -m research.seed_experiments   # one-time: seeds EXP-0001..0005
```

## Safety / permission boundaries

### MAY do
- Create an `experiment/EXP-XXXX` git branch from a clean `master`/`main`
  (`research/git_isolation.py::create_experiment_branch`) and modify files
  required for that experiment's declared independent variable.
- Run `pytest tests/` and `benchmark.evaluate`-style inference as part of an
  experiment's own evaluation method.
- Write/update files under `research/`, `experiments/`.
- Read `OPENROUTER_API_KEY` from the environment for LLM calls, if present.

### MAY NOT do
- Modify anything under `ios/` outside an isolated `experiment/EXP-XXXX`
  branch, and never merge that branch into `master`/`main`/`production`
  itself (`research/git_isolation.py` never calls `merge`/`push`).
- Change signing, App Store submission, `ios/fastlane/Fastfile`'s
  beta/submit/release lanes, or `ios/OmniSightApp/GoogleService-Info.plist`.
- Change `benchmark/config.py`'s real operating-point values (conf=0.4,
  iou=0.7, imgsz=640, model=yolov8m-oiv7.pt) — that is production truth
  forever; diagnostic sweeps live elsewhere.
- Overwrite or delete the canonical baseline run
  (`benchmark/results/baseline/`, run_id `RUN-20260904-002`).
- Access any secret beyond `OPENROUTER_API_KEY` read from env — never
  hardcoded, never logged.
- Submit to the App Store or deploy anything.
- **Delete experiment history.** No `experiments/{queued,running,completed,
  blocked,aborted}/` directory is ever auto-emptied —
  `research/experiment_lifecycle.py::move_to_status` only ever MOVES a
  directory between status folders, never deletes one. Structurally, nothing
  in this package calls `shutil.rmtree` on an experiment directory.

## Execution status vs. research verdict

Two orthogonal axes on every `Experiment` record (`research/db.py`), fixed
in Phase C.5 after EXP-0001 through EXP-0004 exposed a real ambiguity in the
original single-`status` schema:

- **`execution_status`** — did the pipeline run to completion?
  `QUEUED -> RUNNING -> {COMPLETED, ABORTED, BLOCKED}`. This is the axis
  `research/db.py::ALLOWED_TRANSITIONS` governs, and the axis
  `research/experiment_lifecycle.py` uses to place an experiment's directory
  under `experiments/{queued,running,completed,blocked,aborted}/EXP-XXXX/`.
  `ABORTED` means the runner crashed / hit a resource limit / never produced
  a fair, complete result to judge — it is NOT the same thing as a
  `REJECTED` verdict (below).

- **`research_verdict`** — what does the result MEAN, scientifically? Only
  meaningful once `execution_status == "COMPLETED"`
  (`research/db.py::OmniLabDB.set_research_verdict` enforces this and
  refuses to let a verdict be overwritten once set — verdicts are
  immutable, scientific history). Values: `PENDING` (before evaluation),
  `PASS`, `FAIL`, `INCONCLUSIVE`, `REJECTED`.

  `REJECTED` — a structural rejection per `research/rejection.py` (dataset
  tampering, unrelated files touched, test-suite failure on the experiment
  branch, etc.) — lives on the **verdict** axis, not the execution axis,
  even though those checks are "structural" in flavor. The reason: they
  only run AFTER the pipeline has already executed to completion, so the
  experiment's execution_status is genuinely COMPLETED; the result is just
  discarded post-hoc as unfair evidence for the declared hypothesis. Putting
  REJECTED on the execution axis would make execution_status lie about
  whether the run finished.

**Directory placement reflects execution_status ONLY, never the verdict.**
An experiment that ran successfully but got a FAIL/INCONCLUSIVE/REJECTED
verdict lives in `experiments/completed/EXP-XXXX/` next to PASS-verdict
experiments — the verdict is recorded explicitly in that experiment's
`results.json` (`research_verdict` field), `conclusion.md`, and the DB, and
is never to be inferred from which folder an experiment sits in. Automation
(the orchestrator, any future queue processor) reads `research_verdict`
from that metadata; nothing in this package infers a verdict from a
directory name. (An alternative considered and rejected: keeping directory
names encode verdict, e.g. `completed/`, `failed/`, `rejected/` as parallel
buckets to `queued/`/`running/` — this was the ORIGINAL scheme, and it is
exactly what motivated this fix: EXP-0002/EXP-0003 landed in `failed/`
despite executing perfectly correctly, next to a hypothetical crash case
that would have looked identical from the directory name alone.)

**EXP-0001's PASS verdict, explicitly**: EXP-0001 is a confirmatory/control
experiment whose hypothesis is a NEGATIVE claim ("threshold alone cannot
resolve Person recall without unacceptable precision loss"). Its
`research_verdict=PASS` means **the hypothesis was confirmed** — i.e. the
production-unviable conf=0.05 configuration was shown, as predicted, to
trade a precision collapse for a recall gain. It does NOT mean "conf=0.05 is
a good production setting" — the opposite is true, and shipping conf=0.05
is exactly what this PASS verdict argues against. See
`research/runners.py::run_exp_0001`'s docstring and
`experiments/completed/EXP-0001/conclusion.md` for the same statement in
context. Contrast with EXP-0002 (`research_verdict=FAIL` — the resolution
intervention did not clear guardrails) and EXP-0003
(`research_verdict=FAIL` — semantic remapping did not recover recall without
an unacceptable precision cost): those FAILs mean "this production lever
does not work," a different sense of failure entirely from EXP-0001's PASS.
Do not compare EXP-0001's verdict value directly against EXP-0002/EXP-0003's
without this context — the polarity of what PASS/FAIL means is
hypothesis-relative, always documented per-experiment in its
`hypothesis.md`/`conclusion.md`, and deliberately not collapsed into one
project-wide "PASS is good, FAIL is bad" reading.

See `research/migrations/001_split_status_verdict.py` for the one-off
migration that introduced this schema and backfilled EXP-0001..0004 (and
moved EXP-0005, still `BLOCKED`, into `experiments/blocked/`).

## What this phase deliberately does NOT build

- **`omnilab run`** (continuous autonomous queue processing). Only
  `omnilab experiment EXP-XXXX` (one at a time, explicitly named) exists.
  This is a deliberate Phase C boundary, not an oversight — the master spec
  requires one-at-a-time, manually-verified reliability before continuous
  processing is even considered.
- **Live LLM calls.** There is no `OPENROUTER_API_KEY` in this environment.
  `research/llm/` is real, tested plumbing (see `tests/test_llm_router.py`'s
  fake-provider tests) that fails gracefully
  (`research.llm.base.LLMUnavailableError`) rather than crashing anything.
  The initial experiment queue (EXP-0001..0005) was seeded directly from
  already-verified Phase B/B.5 findings, not from an LLM call.
- **Literature-grounded hypothesis generation.** `research/literature/` has
  only a template — see `research/memory/open_questions.md`.
- **Device-validated (Mac/iPhone) execution of anything.** Every experiment
  run in this phase is Windows-only (`OFFLINE_SIMULATABLE`). Family G
  (temporal_pipeline) and the CoreML-deployment aspect of Family E
  (model_variant) are marked `REQUIRES_MAC`/`REQUIRES_IPHONE` in
  `research/experiment_registry.py` and are not attempted here.
- **Mid-experiment graceful suspension.** `pause`/`resume`/`stop`
  (`research/orchestrator.py`) are simple state flags checked before a new
  experiment starts — they do not checkpoint or interrupt an in-flight run.

## Automatic rejection conditions (`research/rejection.py`, invoked from
`research/orchestrator.py::run_experiment`)

- Benchmark/runner execution failure -> execution_status=ABORTED (the run
  never produced a fair, complete result — there is no verdict to record;
  research_verdict stays PENDING). This is the one case here that is NOT a
  research_verdict=REJECTED, since the pipeline did not run to completion.
- Test suite failure on the experiment branch -> execution_status=COMPLETED,
  research_verdict=REJECTED.
- Missing results -> handled by requiring a runner to actually populate
  baseline/candidate metrics before a verdict is computed; surfaces as a
  runner exception (-> ABORTED, see above).
- Unexpected dataset modification: SHA-256 hash of
  `data/manifests/eval_manifest.jsonl` is compared before/after — any change
  -> execution_status=COMPLETED, research_verdict=REJECTED.
- Diff touches files outside the experiment family's declared allowlist
  (`research/experiment_registry.py::FamilySpec.allowed_path_prefixes`) ->
  execution_status=COMPLETED, research_verdict=REJECTED. Heuristic limit:
  this checks path PREFIXES only, not semantic relevance.
- Multiple uncontrolled variables: heuristic check — an experiment must
  declare `independent_variable` and, if its diff touches more than a
  handful of files, must also declare `controls`. Documented as a heuristic,
  not a proof (see `research/rejection.py`'s docstring).
- Resource limits: `research/resources.py::check_resources_or_raise` runs
  BEFORE branch creation — refuses to start rather than launching and OOMing.

## Verification performed for this phase

- `research/git_isolation.py`: tested against a throwaway temp git repo
  (`tests/test_git_isolation.py`), never the real OmniSight repo
  destructively.
- `research/db.py`: status-transition invariant (QUEUED cannot jump straight
  to a terminal verdict) is enforced in code and tested
  (`tests/test_omnilab_db.py`).
- `research/evaluation_policy.py`: tested against concrete before/after
  metric fixtures proving a big-recall/collapsed-precision result does NOT
  auto-pass, a genuine win passes, a noisy/small change is INCONCLUSIVE, and
  a thin-sample class result is downgraded to INCONCLUSIVE
  (`tests/test_evaluation_policy.py`).
- `research/llm/`: graceful-failure behavior confirmed with both a fake
  provider (`tests/test_llm_router.py`) and the real `OpenRouterProvider`
  with no API key set — both raise `LLMUnavailableError`, never crash.
- EXP-0001 was run end-to-end through the real `omnilab experiment`
  pipeline (branch creation -> runner -> tests -> rejection checks ->
  evaluation policy -> DB update -> memory update -> return to master) — see
  the Phase C report-back for the actual verdict and artifact inspection.

## Phase E — structured research memory

Phase D closed with 5 completed, evidence-producing experiments
(EXP-0001..0005) and five loosely-structured markdown memory files
(`research/memory/*.md`). Phase E turns that into a queryable, evidence-
tagged layer ON TOP of the existing record — it adds, never deletes: every
historical file/finding from Phases A-D stays on disk exactly as written.
Phase E is pure synthesis/tooling — **no new experiment, no model training,
no `ios/` change, no live LLM call, no `omnilab run`, no autonomous loop.**

### Schema — `research/memory_db.py` (`research/memory.db`, a sibling DB)

A new, separate SQLite database (NOT new tables in `research/omnilab.db` —
see `research/memory_db.py`'s "Design choice" docstring for why: memory
records have a supersession lifecycle, not an execution state machine, and
keeping them apart avoids entangling `OmniLabDB`'s migration-sensitive
schema with an unrelated concern). One table, `memory_records`, one
dataclass, `MemoryRecord` — same "dataclasses + stdlib sqlite3, no ORM"
pattern as `OmniLabDB`.

**Evidence-level ontology** (`MEMORY_TAGS`):

- `VERIFIED` — a fact directly measured/confirmed against a real artifact.
- `SUPPORTED_HYPOTHESIS` — evidence points this way but is not proven; must
  never be worded as a settled fact (see the model-representation record:
  explicitly NOT "model capacity is the bottleneck").
- `OPEN_QUESTION` — an explicit unresolved question this lab cannot
  currently answer.
- `REJECTED_HYPOTHESIS` — an idea a real experiment's evidence argues
  against. Five mandatory records, one per EXP-0001..0005.
- `LIMITATION` — a methodological constraint on what ANY finding here can
  claim (proxy latency, static-image eval, thin samples, etc), independent
  of any one experiment. Seven mandatory records.

**Mandatory evidence provenance**: every record must carry at least one of
`experiment_id`, `run_id`, or `artifact_path` (plus optional
`metric_field`/`dataset_version`/`git_commit`). `MemoryDB.insert()` calls
`validate_provenance()` and raises `ProvenanceError` on a record with none —
there is no code path that inserts an unsupported claim.

**Supersession**: every record has `status` (`ACTIVE`/`SUPERSEDED`) plus
`supersedes`/`superseded_by` links. `MemoryDB.supersede(old_id, new_id)` is
the one function that changes these — it marks the old record SUPERSEDED
and links both directions. `MemoryDB.list_records()` defaults to
`include_superseded=False` (ACTIVE only — a future agent asking "what's the
class-confusion rate" gets 5.4%, not both numbers with equal weight);
`include_superseded=True` retrieves full history. The flagship case: Phase
B.5's informal "~35% of Person misses are semantic class confusion"
(`reports/baseline/person_failure_analysis.md`) is `status=SUPERSEDED`,
linked to the `status=ACTIVE` record for EXP-0003's rigorous 5.4%
(13/239) figure. See `research/memory_seed.py`'s
`SUPERSESSION` block and `research/memory/known_failures.md` /
`reports/baseline/BASELINE_SCORECARD.md` for pointers added at the old
figure's original locations (the experiment artifacts themselves,
`experiments/completed/EXP-000N/`, are left untouched — historical record).

### Import — `research/memory_seed.py`

One-time import script (`uv run python -m research.memory_seed`),
idempotent-guarded (refuses to reseed a non-empty DB). Populates: baseline
`VERIFIED` facts, one finding record per experiment, the SUPERSESSION pair,
5 `REJECTED_HYPOTHESIS` records, 7 `LIMITATION` records, `OPEN_QUESTION`
records, and the `SUPPORTED_HYPOTHESIS` about architecture/representation.
Every claim cites a concrete git-log-resolved commit hash and on-disk
artifact — see the module for the exact provenance on each record.

### Query — `research/memory_query.py` + `omnilab memory query`

Deterministic, structured retrieval — no LLM call anywhere in this path.
`QUESTION_TYPES` dispatch table backs `uv run python -m research.cli memory
query <question-type>` (`--json` for machine-readable output):
`person-interventions`, `rejected`, `person-failure-modes`,
`true-detector-miss`, `open-questions`, `model-representation`,
`limitations`, `for-experiment --experiment-id EXP-000N`.

### Context packet — `research/memory_context.py`

`generate_context_packet()` assembles a compact JSON/dict summary (verified
baseline, strongest findings, ALL rejected directions, unresolved
questions, limitations, one-liner per closed experiment) for a future
hypothesis-generating agent, and `write_context_packet()` renders it to
`research/memory/CONTEXT_PACKET.md` (`uv run python -m research.cli memory
context`). **Any future agent — LLM-driven or human — MUST read this packet
before proposing a new experiment**, per the master spec's "research memory
before hypothesis generation" principle. Reading it is enough to recognize
"lower confidence" / "higher resolution" / "remap Man to Person" / "apply
CLAHE" / "just use a larger YOLO" as already-rejected (EXP-0001..0005
respectively) without re-deriving or re-reading the full experiment
artifacts.

### Tests

`tests/test_research_memory.py` — insertion, provenance enforcement,
retrieval by tag, experiment linkage, supersession mechanics (including the
35%->5.4% case end-to-end), context-packet structure/determinism, and a
backward-compatibility check confirming Phase E did not disturb
`research/db.py`'s pre-existing schema/behavior (no columns/tables were
added to `research/omnilab.db`).

## Phase F — canonical experiment specification & validation

Phase F is **schema/validation engineering, not a new experiment.** It adds
a canonical, machine-validated `ExperimentSpec` schema that any FUTURE
proposal (human- or, eventually, LLM-authored) must satisfy before it may
enter the executable queue. It does not create EXP-0006, run anything, train
anything, touch `ios/`, or make any OpenRouter/LLM call — every check in this
phase is a plain Python function over structured data and on-disk/DB
artifacts.

### Audit summary (`research/PHASE_F_AUDIT.md`)

See that file for the full field-by-field accounting. Short version: most
"real" experiment content already existed either as `research/db.py::Experiment`
dataclass fields (hypothesis, motivation, independent_variable, controls,
success_criteria, baseline_run_id, metrics, conclusion, execution_status,
research_verdict, ...) or as free-form markdown/YAML per experiment
(`hypothesis.md`, `methodology.md`, `config.yaml`). Nothing was rewritten —
Phase F adds a layer that (a) makes the free-form parts machine-checkable
where they should be (success criteria, variable declarations, evidence
references), (b) explicitly separates "what was pre-registered" from "what
was observed," and (c) formalizes fields that existed only in prose or not
at all (`schema_version`, explicit human-authority approval flags, amendment
records).

### Why dataclasses + a hand-rolled validator, not Pydantic

The project already standardizes on dataclasses + stdlib sqlite3 for
`research/db.py::Experiment` and `research/memory_db.py::MemoryRecord`.
Adding Pydantic here would introduce a second validation philosophy for a
structurally similar problem, plus a new dependency, with none of Pydantic's
main value-adds actually needed (there is no external/loosely-typed input in
this phase — only JSON round-tripped within this codebase, and a future
LLM-authored JSON path that specifically needs explicit, auditable,
hand-written rejection rules, not a generic type coercer). `dataclasses.replace()`
also makes the freeze/amend mechanism (below) simplest as a plain dataclass.
This is a deliberate call — see `research/experiment_spec.py`'s module
docstring for the same argument in code.

### Canonical schema — `research/experiment_spec.py`

`ExperimentProposal` (frozen dataclass, everything pre-registered) and
`ExperimentResult` (everything only populated post-execution) are separate
types — a proposal object structurally cannot hold a metric, verdict, or
conclusion. Field groups: Identity (`experiment_id`, `schema_version`,
`title`, `family`); Research basis (`hypothesis`, `motivation`,
`research_question`, `evidence_references` — Phase-E `MEM-XXXX` ids,
`prior_experiment_ids`); Baseline (`baseline_run_id`, `baseline_metrics`);
Variables (`independent_variables`, `dependent_variables`,
`controlled_variables`); Methodology (`procedure`, `dataset_version`,
`model_config_ref`, `implementation_scope`, `expected_artifacts`,
`reproducibility_requirements`); Controls (`control_condition`,
`baseline_comparison`, `isolation_requirements`); Success criteria
(`success_criteria` dict — `min_meaningful_delta`, `precision_floor`,
`max_latency_regression_pct`, `required_tests_pass`,
`sample_size_requirements`, reusing the guardrail/noise-margin/sample-floor
pattern from `research/evaluation_policy.py`); Risk/safety
(`production_impact` + description, `data_privacy_classification`,
`external_api_required`, `mac_iphone_required`,
`compute_resource_estimate`, `allowed_path_scope`); Expected interpretation
(`supports_hypothesis_if`, `rejects_hypothesis_if`, `inconclusive_if` —
pre-registered BEFORE execution); the 7 human-authority approval flags (see
below); and `acknowledges_rejected_hypothesis_ids`/`materially_new_rationale`.
`ExperimentResult` fields: `execution_run_id`, `metrics`,
`benchmark_artifact_paths`, `code_diff_path`, `test_results_summary`,
`execution_status`, `research_verdict`, `conclusion`, `limitations` — all
`None`/empty until real execution happens.

### Proposal/result separation (item #3)

`check_no_result_fields_in_proposal()` raises
`ProposalContainsResultFieldsError` if a raw dict destined to become an
`ExperimentProposal` contains any `ExperimentResult` field name —
`ExperimentProposal.from_dict()` calls it unconditionally. Separately,
`experiment_validator.py::validate()` rejects an `ExperimentSpec` whose
`result` has populated fields while `result.execution_status is None`
(`PREMATURE_RESULT_FIELDS`). See `tests/test_experiment_spec.py::
test_result_fields_rejected_from_proposal_dict` and
`test_result_fields_populated_before_execution_status_rejected`.

### Freeze / amendment (item #4)

`ExperimentSpec.freeze(to_status)` moves a spec from `DRAFT` to `VALIDATED`
or `APPROVED` (a spec-lifecycle axis, deliberately distinct from
`research/db.py`'s `execution_status`, which is about the RUN once queued)
and snapshots a SHA-256 hash of the frozen proposal payload
(`frozen_hash`). Once frozen, the proposal is a genuinely frozen dataclass —
direct attribute assignment raises outright. The only sanctioned path to
change a frozen field is `ExperimentSpec.amend(field_name, new_value, reason,
approved_by)`, which appends a fully traceable `Amendment` (old value, new
value, reason, timestamp, `approved_by` — `"human via CLI"` today, since
there is no live LLM role yet) and re-freezes at the new hash.
`verify_integrity()` recomputes the hash and raises
`FrozenProposalTamperedError` on any mismatch (silent out-of-band mutation).
See `tests/test_experiment_spec.py::test_freeze_then_amend_produces_traceable_record`,
`test_frozen_proposal_tampering_detected`, `test_success_criteria_frozen_after_approval`.

### Deterministic validation — `research/experiment_validator.py`

`validate(spec) -> ValidationResult` returns a LIST of `ValidationIssue`
(level `ERROR`/`WARNING`/`NEEDS_HUMAN_REVIEW`, never a bare bool). It checks:
missing hypothesis/motivation; `baseline_run_id` resolution against real
`benchmark/results/{baseline,diagnostics}/run_metadata.json` artifacts (never
a hand-typed number); `prior_experiment_ids` against `research/db.py`;
`evidence_references` against `research/memory_db.py`; missing
independent/dependent variables; missing control_condition/baseline_comparison;
missing/contradictory `success_criteria` (negative `min_meaningful_delta`,
`precision_floor` outside `[0,1]`, and one concrete named mutual-exclusion
example — documented as not exhaustive); invalid metric names against
`KNOWN_METRIC_GROUPS`/`KNOWN_METRIC_SUFFIXES` (built directly from
`evaluation_policy.py`'s actual usage plus the documented 8-class hazard
vocabulary, since `evaluation_policy.py` itself has no single enumerated
list); `mac_iphone_required` vs. the family's registry requirement;
production-impact/mac-iphone/private-data/external-API changes without the
matching human-authority flag; malformed (`EXP-\d{4}`) and duplicate
experiment IDs; unsupported family; the rejected-hypothesis-acknowledgment
check (below); and the proposal/result-separation check. Anything not
mechanically checkable (procedure/reproducibility narrative quality,
overall scientific merit) is emitted as an explicit `NEEDS_HUMAN_REVIEW`
issue naming what could not be checked — never silently passed.

### Experiment families (8, was 7) — `research/experiment_registry.py`

Families A-G are unchanged. **New: H, `application_decision_logic`**
("Application-Level Decision Logic") — user-facing announcement/decision
logic layered on top of detection (TTS/announcement cadence, hazard-to-speech
priority ordering, per-class cooldown), genuinely distinct from G
(`temporal_pipeline`, which is about tracking/temporal smoothing of
detections, not what gets spoken). `windows_evaluatable=False`,
`production_validation_requirement="REQUIRES_IPHONE"` — same structural
limitation as G. This is a **registry entry only** — no runner exists for
family H, in this phase or any prior one. **Known gap, flagged explicitly**:
`research/db.py::EXPERIMENT_FAMILIES` (the tuple backing `Experiment`'s SQL
CHECK constraint) was deliberately NOT extended to include
`application_decision_logic` in this phase — no family-H experiment is
queued or queueable as a real DB row yet, so widening that CHECK constraint
was unnecessary surface area for Phase F to touch; a future phase that
actually proposes a family-H experiment must add it there first.

### Queue gate (item #9)

`research/experiment_validator.py::is_queue_eligible(result) -> bool`
returns True iff `validate()` produced zero `ERROR`-level issues (warnings
and `NEEDS_HUMAN_REVIEW` do not block the mechanical gate, though they may
still block a human reviewer). Wired into
`research/orchestrator.py::queue_experiment_from_spec(spec)` — the function
that actually inserts a new `Experiment` row as `QUEUED` (`db.create_experiment`)
from a canonical spec — which raises `QueueGateError` naming every failing
check and refuses to insert anything if validation fails.
`research/db.py`'s `execution_status`/`research_verdict` axes are completely
unchanged; this is a gate placed BEFORE insertion, not a new status value.

### Memory linkage & rejected-hypothesis acknowledgment (item #8)

`evidence_references` on a proposal holds Phase-E `MEM-XXXX` ids, checked to
resolve by `validate()`. Additionally, `find_rejected_hypothesis_conflicts()`
does pure deterministic metadata matching (no LLM, no semantic similarity):
for every ACTIVE `REJECTED_HYPOTHESIS` memory record, resolve its owning
experiment's `family` via `research/db.py`, compare to the proposal's
`family` (exact match required), and check keyword overlap (lowercased,
tokenized, stopword-filtered set intersection) between the proposal's
`independent_variables` and the record's stored `independent_variable` text.
Any match without `acknowledges_rejected_hypothesis_ids` naming the
conflicting experiment/record AND a non-empty `materially_new_rationale`
fails validation with `UNACKNOWLEDGED_REJECTED_HYPOTHESIS`, naming the
specific conflicting id. See
`tests/test_experiment_spec.py::test_naive_reproposal_of_lower_confidence_is_caught`
— a proposal for `family="threshold_postprocessing"`,
`independent_variables=("lower confidence threshold to 0.1",)` is caught
against EXP-0001/`MEM-0010` without any acknowledgment.

### Human authority flags (item #10)

Seven boolean approval fields on `ExperimentProposal`, default `False`:
`production_swift_modification_approved`, `coreml_model_replacement_approved`,
`new_training_approved`, `private_user_data_use_approved`,
`external_upload_approved`, `mac_iphone_deployment_approved`,
`signing_distribution_change_approved`. `validate()` hard-fails any proposal
whose declared risk profile requires one but whose flag is `False`
(`production_impact=True` without `production_swift_modification_approved`,
etc.). **`external_api_required` and `external_upload_approved` are
completely decoupled** from `OPENROUTER_API_KEY`'s presence in the
environment — nothing in `experiment_validator.py` reads `os.environ` at
all; the key's presence/absence has zero bearing on this flag, proven by
`tests/test_experiment_spec.py::test_external_api_required_does_not_imply_authorization`,
which checks the same failure occurs identically whether the (mocked, never
real) key is present or absent, and never reads/prints/logs the real key's
value anywhere.

### Backfill (item #7) — `research/backfill_experiment_specs.py`

Constructs `ExperimentProposal`+`ExperimentResult` pairs for EXP-0001..0005
from the real historical artifacts (`hypothesis.md`, `methodology.md`,
`config.yaml`, `results.json`, `conclusion.md`) and writes them to
`research/experiment_specs/EXP-000N.json` (`uv run python -m
research.backfill_experiment_specs`). **Migration policy** (full rationale
in that module's docstring): `LEGACY_UNKNOWN` marks a field that existed in
spirit in the historical prose but was never written as its own discrete
field (e.g. `supports_hypothesis_if`/`rejects_hypothesis_if`/`inconclusive_if`);
`NOT_RECORDED` marks a field whose underlying CONCEPT did not exist at all
at the time (`evidence_references` — Phase E's memory DB postdates
EXP-0001..0005); `NOT_APPLICABLE` marks a field that is meaningful in
general but doesn't apply to a given experiment. `schema_version` on every
backfilled record is set to the CURRENT version (a statement about the
backfilled record's FORMAT today, not a claim about what schema existed when
EXP-0001 actually ran). Human-authority approval flags are left `False` for
all five — none of them ever touched production Swift, replaced a shipped
model, trained anything, used private data, uploaded externally, deployed to
Mac/iPhone, or changed signing, so none was ever sought or is fabricated
retroactively. **Verified execution_status/research_verdict, unchanged**:
EXP-0001 COMPLETED/PASS, EXP-0002 COMPLETED/FAIL, EXP-0003 COMPLETED/FAIL,
EXP-0004 COMPLETED/INCONCLUSIVE, EXP-0005 COMPLETED/INCONCLUSIVE — checked
both against the backfilled JSON files AND against the live `research/db.py`
rows (`tests/test_experiment_spec.py::test_legacy_backfill_matches_live_db_row`).

### CLI — `research/cli.py`

`omnilab experiment run EXP-XXXX` (renamed from the old bare `omnilab
experiment EXP-XXXX` — same Phase-C behavior). New:
`omnilab experiment validate EXP-XXXX` (runs `experiment_validator.validate()`
against `research/experiment_specs/EXP-XXXX.json`, prints every issue by
level, prints queue eligibility) and `omnilab experiment show EXP-XXXX
[--json]` (normalized schema fields: hypothesis/motivation/research question,
evidence references, pre-registered success criteria and interpretation
conditions, risk/safety flags, amendment count, result if any, and a
validation summary). No LLM call anywhere in either command path.

### Schema versioning (item #12)

Current version: `"1.0"` (`research.experiment_spec.SCHEMA_VERSION`).
Compatibility policy (`research/experiment_spec_migrations.py`): a
same-MAJOR-version proposal dict loads directly, even across minor versions
(additive minor fields are expected to have safe defaults); a
different-MAJOR-version dict requires an explicit, registered
`(from_version, to_version)` migration function, raising
`UnsupportedSchemaVersionError` if none exists — never silently guessed. A
missing `schema_version` raises `SchemaVersionError` immediately. The
registry currently holds exactly one migration, a documented no-op
`("1.0", "1.0")` entry — a real extension point, deliberately not
over-built for versions that don't exist yet.

### Example — NON-EXECUTABLE

```json
{
  "proposal": {
    "schema_version": "1.0",
    "experiment_id": "EXP-9999",
    "title": "Per-hazard-class TTS cooldown instead of one global cooldown",
    "family": "application_decision_logic",
    "hypothesis": "A per-class TTS announcement cooldown (e.g. 4s for Person, 8s for Stairs) reduces redundant/annoying announcements without increasing missed-hazard-announcement rate, compared to today's single global cooldown.",
    "motivation": "User feedback (hypothetical, not yet collected) suggests the current single global cooldown either over-announces frequent nearby hazards (Person) or under-announces rare-but-critical ones (Stairs) because both share one timer.",
    "research_question": "Does per-class cooldown tuning change announcement redundancy/missed-hazard rate on real device sessions?",
    "evidence_references": [],
    "prior_experiment_ids": [],
    "baseline_run_id": "RUN-20260904-002",
    "independent_variables": ["per-class TTS cooldown duration"],
    "dependent_variables": ["announcement latency (device-measured)", "false-alarm/redundant-announcement rate (device-measured)"],
    "control_condition": "current single global cooldown, unchanged",
    "baseline_comparison": "on-device A/B session log comparison (REQUIRES_IPHONE — cannot be Windows-simulated)",
    "success_criteria": {"primary_metric": "hazard.recall", "min_meaningful_delta": 0.03},
    "production_impact": true,
    "production_impact_description": "would modify ios/ SpeechEngine cooldown logic if adopted",
    "mac_iphone_required": true,
    "production_swift_modification_approved": false,
    "mac_iphone_deployment_approved": false
  }
}
```

**NON-EXECUTABLE EXAMPLE — not queued, not run, illustrative only.** It is
not present in `research/experiment_specs/`, has no `EXP-9999` row in
`research/db.py`, and would in fact FAIL `validate()` today
(`production_impact=True`/`mac_iphone_required=True` with both approval
flags `False`) — which is the point: this is what an under-approved,
not-yet-queue-eligible family-H proposal looks like.

## Phase G — real, tested, budget-aware, safe LLM abstraction

Phase G makes the Phase C `research/llm/` skeleton real: an actual OpenRouter
HTTP call was implemented and exercised (once, live, deliberately) on top of
the graceful-no-key plumbing that already worked. Phase G adds **no new
experiment**, queues nothing, trains nothing, and does not touch `ios/` or
`benchmark/config.py`.

### What Phase C already had working (audited, not rewritten)

- `research/llm/base.py::LLMUnavailableError` — the designed, catchable
  graceful-failure type for "no LLM available right now."
- `research/llm/base.py::UsageTracker` — a persisted, JSON-file daily call
  counter re-read on every check (already correct; Phase G only changed
  *when* `record_call()` fires — see below).
- `research/llm/router.py::LLMRouter` — primary/fallback model routing over
  `roles.yaml`, tested against a fake provider (`tests/test_llm_router.py`).
- Graceful no-key failure (`OpenRouterProvider._api_key()`).

### What was incomplete before Phase G

No real HTTP call had ever been implemented or tested (the pre-Phase-G
`complete()` made an actual `requests.post()` with no test ever mocking it —
`tests/test_llm_router.py::test_explicit_key_bypasses_env_check` was, in
practice, an unmocked live network attempt that happened to look like a
graceful-failure test because it failed either way). There was no
authorization gate separate from "is a key present," no error-category
vocabulary, no bounded retry/backoff, no per-run budget distinct from the
daily cap, no structured-output validation, no privacy/injection guards, and
no context builder wired to Phase E's context packet.

### Provider abstraction

`research/llm/base.py::LLMProvider.complete()` is the one interface every
provider implements. `LLMResponse` (text, tokens_used, cost_usd, model_used,
provider, request_id, latency_ms, error_category) is the only shape that
crosses out of `research/llm/` — nothing outside this package ever sees a
raw OpenRouter JSON response. `ErrorCategory` is a closed enum: `TIMEOUT`,
`HTTP_ERROR`, `RATE_LIMIT`, `AUTH_ERROR`, `MODEL_UNAVAILABLE`,
`MALFORMED_RESPONSE`, `EMPTY_RESPONSE`, `NETWORK_ERROR`, `UNKNOWN`.

### OpenRouter configuration / env vars

`OPENROUTER_API_KEY` is read from `os.environ` inside
`OpenRouterProvider._api_key()` at call time (never at import time, so tests
freely monkeypatch it). It is never interpolated into a log line or
exception message — only a redacted `set(len=N)`/`unset` marker is ever
shown. `.env` is gitignored (verified by
`tests/test_llm_no_network.py::TestEnvIsGitignored`); `.env.example`
contains only the placeholder `OPENROUTER_API_KEY=`.

**Having `OPENROUTER_API_KEY` configured does not authorize external
calls.**

### Model routing

`research/llm/roles.yaml` now uses `preferred_model` + `fallback_models`
(a list, tried in order) + `max_tokens` + `timeout` + `call_budget_category`
per role (`researcher`, `experiment_designer`, `reviewer`, `analyst`). The
original master plan's named free-tier models were not assumed current —
see `roles.yaml`'s header comment for the explicit "unverified, re-check
before relying on this" caveat. `LLMRouter._role_config()` also still
accepts the original Phase C `primary`/`fallback` (singular) keys for
backward compatibility with existing fixtures.

### Budgets

Two independent, distinct caps:
  - **Daily** (`UsageTracker`, `research/llm_usage.json`, default 40/day via
    `research.config.MAX_LLM_CALLS_PER_DAY`) — persisted, survives process
    restarts, re-read on every check.
  - **Per-run** (`RunBudget`, in-memory only, default 10/run via
    `research.config.MAX_LLM_CALLS_PER_RUN`) — deliberately not persisted;
    a "run" is one process invocation, and cross-process accumulation is
    already the daily tracker's job.

**Policy (deliberate, documented):** both budgets are checked BEFORE any
network attempt and incremented AFTER every attempt — success or failure.
A failed call still costs a real round-trip; letting a retry/fallback storm
look "free" because every attempt failed would defeat the guardrail's
purpose.

### Authorization gate

`research/llm/authorization.py::require_authorization()` is the single
choke point both `OpenRouterProvider.complete()` and `LLMRouter.complete()`
call through. `authorized` has no default that silently authorizes a call —
omitting it or passing `False` (or an `LLMCallAuthorization` with
`authorized=False`) raises `LLMCallNotAuthorizedError` before the API key is
even checked, before budget is checked, before any network code runs. This
is structurally separate from "is a key present": a key alone never
dispatches a call. Tested exhaustively in `tests/test_llm_authorization.py`,
including the specific decoupling case (key present + `authorized=False` →
refused, HTTP layer mocked and asserted never invoked; key present +
`authorized=True` → proceeds against a mocked HTTP layer).

### Privacy / data boundary

`research/llm/privacy_guard.py::check_payload_safe(payload)` runs against
every outgoing request payload before it is sent (wired into
`OpenRouterProvider.complete()`, and into `research/llm/context_builder.py`'s
output). It flags: a literal `OPENROUTER_API_KEY=`/`*_SECRET=`/`*_TOKEN=`
assignment, a multi-line `.env`-style dump, a `Bearer <token>` header, an
`sk-...`-style key literal, and an absolute Windows user-profile path. **This
is a best-effort heuristic, not a security boundary** — it does not catch
obfuscated/encoded secrets, non-text media, or novel PII formats; see the
module docstring for the full, honest limits list. Nothing in
`research/llm/context_builder.py` auto-pulls files, photos, faces, voices,
environment variables, or repository dumps — only Phase E's compact context
packet plus whatever the caller explicitly passes in
(`objective`/`code_excerpt`).

### Context construction

`research/llm/context_builder.py::build_context()` wraps
`research/memory_context.py::generate_context_packet()` (the PREFERRED, and
now only, source of context) into a `BuiltContext` with observable
`char_count`/`approx_token_estimate` and a `categories_included` dict
(`baseline`, `rejected_hypotheses`, `open_questions`, `objective`,
`code_excerpt`) so a caller can see exactly what went in without
re-deriving it. Deterministic: the same memory-DB state produces the same
context text every time.

### Structured-output validation

`research/llm/structured_output.py` defines three response shapes —
`HypothesisResponse`, `ReviewerResponse`, `AnalysisResponse` — validated via
`parse_and_validate(raw_text, shape)`. Any response containing a Phase F
result-only field (`metrics`, `research_verdict`, `verdict`,
`observed_results`, `pass_fail`, ...) is rejected, reusing the exact
proposal/result separation principle `research/experiment_spec.py` already
enforces for `ExperimentProposal.from_dict()`. `tests/test_llm_structured_output.py::TestChainOfCustody`
proves an adversarial response containing smuggled result fields cannot (a)
reach `ExperimentProposal.from_dict()`/the queue-eligibility gate, (b)
mutate `research/db.py` (patched and asserted uncalled), or (c) produce any
object an evidence-recording path could consume.

### Prompt injection / authority boundaries

`research/llm/prompts/system_policy.md` is the system-prompt template any
real role call should prepend — it states plainly that production code is
off-limits, the deterministic benchmark decides outcomes (not the model),
no fabricated results are acceptable, the model has no secret access, and
it cannot change frozen success criteria or bypass approval flags.
`research/llm/injection_guard.py::flag_suspicious_response()` is a
lightweight, best-effort pattern scan over model OUTPUT (phrases like
"ignore previous instructions," "disable the guardrail," "bypass approval,"
"reveal the api key"). **This is explicitly NOT a solved problem** — it is
trivially evadable by rephrasing/translation/splitting, and is never treated
as a security control; the actual safety property (model output cannot set
a verdict, mutate the DB, or become evidence) is enforced structurally by
`research/llm/structured_output.py`, independent of whether this heuristic
fires.

### Retry / failure policy

`OpenRouterProvider.complete()` retries only `TIMEOUT`/`NETWORK_ERROR`
(`RETRYABLE_CATEGORIES` in `research/llm/base.py`), bounded by `max_retries`
(default 2 → up to 3 total attempts), with a small exponential backoff.
`AUTH_ERROR`/`MALFORMED_RESPONSE`/`MODEL_UNAVAILABLE`/`EMPTY_RESPONSE` fail
immediately — they cannot succeed differently on retry. `max_retries=0`
disables retries entirely (used by the one live smoke-test call below).
Fallback to `fallback_models` happens at the router level
(`LLMRouter.complete()`) and is itself budget-aware: every attempted model,
success or failure, counts against both the daily and per-run budget.

### Tests / zero-network guarantee

`tests/test_llm_*.py` cover every item above. **Approach for "no network
call occurs in normal unit tests":** every Phase G test mocks
`requests.post` directly, AND `tests/conftest.py` adds an autouse,
session-scoped fixture that monkeypatches `socket.socket.connect`/
`connect_ex` to raise `UnexpectedNetworkCallError` for any non-loopback
host — a backstop in case any test is missing a mock. Full suite: 308 → 388
tests, all green, confirmed zero real network calls during the run.

### The one live smoke test (dated record)

Run manually (not collected by pytest) via `research/llm/smoke_test.py` on
**2026-09-05**. Result: the chosen model id,
`meta-llama/llama-3.1-8b-instruct:free` (picked from prior knowledge of
OpenRouter's free tier rather than spending the one call on model
discovery — see that file's docstring for the full reasoning), returned
`HTTP 404` / `ErrorCategory.MODEL_UNAVAILABLE` — the slug no longer exists
on OpenRouter as of this date. Per the task's explicit instruction, this
was NOT treated as a reason to try a second model live; the single
authorized call (`max_retries=0`, so exactly one HTTP request) was made,
recorded against budget (0/40 → 1/40 used), and reported as a clean,
informative failure. The key was never logged (only a `set(len=73)`
redacted marker was printed). A future phase should pick a re-verified
model id (or spend a dedicated, separately-authorized call on the
`/models` discovery endpoint) before relying on a live OpenRouter call
again.
