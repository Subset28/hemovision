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
- **Delete experiment history.** `experiments/failed/` and
  `experiments/rejected/` are never auto-emptied —
  `research/experiment_lifecycle.py::move_to_status` only ever MOVES a
  directory between status folders, never deletes one. Structurally, nothing
  in this package calls `shutil.rmtree` on an experiment directory.

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

- Benchmark/runner execution failure -> REJECTED.
- Test suite failure on the experiment branch -> REJECTED.
- Missing results -> REJECTED (handled by requiring a runner to actually
  populate baseline/candidate metrics before a verdict is computed).
- Unexpected dataset modification: SHA-256 hash of
  `data/manifests/eval_manifest.jsonl` is compared before/after — any change
  -> REJECTED.
- Diff touches files outside the experiment family's declared allowlist
  (`research/experiment_registry.py::FamilySpec.allowed_path_prefixes`) ->
  REJECTED. Heuristic limit: this checks path PREFIXES only, not semantic
  relevance.
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
