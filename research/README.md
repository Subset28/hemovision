# OmniSight Research Lab — Phase C (experiment infrastructure)

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
