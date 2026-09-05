# Phase I Readiness Audit

**Scope**: deterministic A–H system audit + Phase I threat model +
recommended autonomy boundary. Zero live LLM completion calls were made to
produce this report (public catalog/docs fetches only, and only where
already-cached from earlier Phase H work — none newly fetched here).

**UPDATE (hardening pass, same day)**: both CRITICAL findings and all HIGH/
MEDIUM findings below (§6) have been fixed and tested — see
`reports/phase_i/PHASE_I_SAFETY_INVARIANTS.md` for the full invariant table,
enforcement locations, and residual risks. §6 below is left as originally
written (the audit's own record) with a RESOLVED marker added to each item;
nothing in this document was rewritten to look retroactively correct.

**Bottom line, as originally written: READY_WITH_RESTRICTIONS.** Two
CRITICAL gaps had to close before any Phase I autonomous loop starts (kill
switch not covering LLM calls; free-model enforcement being opt-in). Both
are now RESOLVED — see the safety invariants report for the updated overall
recommendation.

---

## 1. Field-by-field proposal schema mapping matrix

Every field of `research/experiment_spec.py::ExperimentProposal`, classified
by where its value actually comes from. Fixed in commit `3bcebb5` are
marked **FIXED**; pre-existing correct mappings are unmarked.

| Field | Source | Notes |
|---|---|---|
| `schema_version` | DETERMINISTICALLY_DERIVED | hardcoded `"1.0"` in `_build_proposal` |
| `experiment_id` | DETERMINISTICALLY_DERIVED | dry-run: `EXP-9xxx` placeholder, never persisted; real queue: sequential id from `research/db.py`, never LLM-authored |
| `title` | LLM_SUPPLIED | |
| `family` | LLM_SUPPLIED | validated against `experiment_registry.REGISTRY` |
| `hypothesis` | LLM_SUPPLIED | validator requires non-empty |
| `motivation` | LLM_SUPPLIED | validator requires non-empty |
| `research_question` | LLM_SUPPLIED | |
| `evidence_references` | LLM_SUPPLIED | validated against real `MemoryDB` records (`BAD_EVIDENCE_REF`) |
| `prior_experiment_ids` | LLM_SUPPLIED | validated against real DB experiments (`BAD_PRIOR_EXPERIMENT_REF`) |
| `baseline_run_id` | DETERMINISTICALLY_DERIVED | pipeline parameter (`CANONICAL_BASELINE_RUN_ID`), never LLM-authored |
| `baseline_metrics` | **FIXED** → DETERMINISTICALLY_DERIVED | `research/baseline_lookup.py::load_baseline_metrics()`; was silently `{}` before this fix |
| `independent_variables` | LLM_SUPPLIED | validator requires non-empty |
| `dependent_variables` | LLM_SUPPLIED | validator requires non-empty |
| `controlled_variables` | LLM_SUPPLIED | |
| `procedure` | LLM_SUPPLIED | empty → `NEEDS_HUMAN_REVIEW` (`PROCEDURE_QUALITY`) |
| `dataset_version` | **FIXED** → LLM_SUPPLIED | required in native schema; placeholder-checked |
| `model_config_ref` | **FIXED** → LLM_SUPPLIED | required in native schema; placeholder-checked |
| `implementation_scope` | **FIXED** → LLM_SUPPLIED | required in native schema; placeholder-checked |
| `expected_artifacts` | **FIXED** → LLM_SUPPLIED | required in native schema |
| `reproducibility_requirements` | **FIXED** → LLM_SUPPLIED | already had a `NEEDS_HUMAN_REVIEW` check pre-fix; now also wired end-to-end and placeholder-checked |
| `control_condition` | LLM_SUPPLIED | validator requires non-empty |
| `baseline_comparison` | LLM_SUPPLIED | validator requires non-empty |
| `isolation_requirements` | **FIXED** → LLM_SUPPLIED | required in native schema; placeholder-checked |
| `success_criteria` | LLM_SUPPLIED | validator checks metric names + contradiction rules |
| `production_impact` | LLM_SUPPLIED | gates `UNAPPROVED_PRODUCTION_IMPACT` |
| `production_impact_description` | LLM_SUPPLIED | |
| `data_privacy_classification` | LLM_SUPPLIED | gates `UNAPPROVED_PRIVATE_DATA_USE` |
| `external_api_required` | LLM_SUPPLIED | gates `UNAPPROVED_EXTERNAL_API` |
| `mac_iphone_required` | LLM_SUPPLIED | cross-checked against family registry (`MAC_IPHONE_REQUIRED_MISMATCH`) |
| `compute_resource_estimate` | **FIXED** → LLM_SUPPLIED | required in native schema; empty → `NEEDS_HUMAN_REVIEW` |
| `allowed_path_scope` | **FIXED** → DETERMINISTICALLY_DERIVED | `_family_allowed_path_scope()` from `experiment_registry.py`; was silently `()` before this fix |
| `supports_hypothesis_if` | LLM_SUPPLIED | |
| `rejects_hypothesis_if` | LLM_SUPPLIED | |
| `inconclusive_if` | LLM_SUPPLIED | |
| `production_swift_modification_approved` | HUMAN_SUPPLIED | hardcoded `False` in `_build_proposal`; only changeable via `ExperimentSpec.amend()` |
| `coreml_model_replacement_approved` | HUMAN_SUPPLIED | same |
| `new_training_approved` | HUMAN_SUPPLIED | same |
| `private_user_data_use_approved` | HUMAN_SUPPLIED | same |
| `external_upload_approved` | HUMAN_SUPPLIED | same |
| `mac_iphone_deployment_approved` | HUMAN_SUPPLIED | same |
| `signing_distribution_change_approved` | HUMAN_SUPPLIED | same |
| `acknowledges_rejected_hypothesis_ids` | LLM_SUPPLIED | cross-checked against `find_rejected_hypothesis_conflicts()` |
| `materially_new_rationale` | LLM_SUPPLIED | required non-empty when acknowledging a conflict |

**No field is unaccounted for.** Every canonical field now has an explicit,
traceable source; none can be silently empty AND pass validation without an
explicit `NEEDS_HUMAN_REVIEW` or `PLACEHOLDER_VALUE` signal (see
`research/experiment_validator.py`).

---

## 2. A–H deterministic readiness audit

### Phase A — architecture docs
`OMNISIGHT_ARCHITECTURE.md`/`BENCHMARK_PLAN.md`/`IMPLEMENTATION_PLAN.md`
still describe the shipped app accurately (ARKit+Vision/CoreML+SORT+LiDAR,
YOLOv8m/OIV7, 601 classes) — no production code has changed since Phase A.
Production boundary (`ios/` = protected, `research/`+`benchmark/`+`experiments/`
= lab) remains structurally enforced (§3). **PASS.**

### Phase B/B.5 — benchmark
- Baseline tag `RUN-20260904-002` exists, unchanged (`benchmark/results/baseline/`).
- Benchmark is deterministic: fixed `conf=0.4/iou=0.7/imgsz=640`, fixed
  `random_seed=42` (recorded in `run_metadata.json`), fixed 380-image manifest.
- Corrected 5.4% class-confusion figure (EXP-0003, superseding the earlier
  35.1% estimate) remains the authoritative memory record — confirmed
  `SUPERSEDED` tag present in `research/memory.db`.
- Benchmark/data-isolation assumption: the eval manifest is drawn from OIV7's
  *validation* split — this fact is what DRYRUN-0007's reviewer correctly
  flagged as an isolation risk for any future training experiment. Documented,
  not yet resolved (that resolution is exactly what a real training_data
  experiment would need to do). **PASS**, with the isolation caveat carried
  forward as a known limitation, not a defect.

### Phase C — experiment infrastructure
- `research/omnilab.db` integrity: exactly EXP-0001..EXP-0005, all
  `COMPLETED`, verdicts PASS/FAIL/FAIL/INCONCLUSIVE/INCONCLUSIVE — unchanged.
- Audit log: `experiment_events` table records every status/verdict
  transition — **but nothing prevents a second write** to an experiment
  already `COMPLETED` (see §6, HIGH finding).
- Branch isolation: `create_experiment_branch()` is called only from
  `orchestrator.run_experiment()`; confirmed zero calls from `research/dry_run/`
  or `research/cli.py`'s dry-run commands.
- Pause/resume/stop: `_check_not_paused_or_stopped()` is code-enforced,
  called at the top of `orchestrator.run_experiment()` — confirmed it raises
  `OrchestratorPausedError`/`OrchestratorStoppedError` before any real
  execution proceeds. **This gate does NOT cover any Phase H dry-run/live-LLM
  call path** (see §6, CRITICAL finding). **PARTIAL PASS.**

### Phase D — EXP-0001..0005
- All 5 remain `COMPLETED`, verdicts unchanged since Phase D closed.
- Negative/inconclusive results (EXP-0002 FAIL, EXP-0003 FAIL, EXP-0004/0005
  INCONCLUSIVE) are preserved, not deleted, and are exactly what Phase H's
  redundancy checker uses to reject superficially-reworded repeats.
- Verdict/status semantics (execution_status vs. research_verdict, two
  independent axes) intact — confirmed via direct DB query this round.
  **PASS.**

### Phase E — research memory
- `research/memory.db` still returns the corrected 5.4% class-confusion
  finding as authoritative (superseding the informal 35.1% estimate) —
  confirmed via `research/memory_context.py::generate_context_packet()`
  output used in every Phase H prompt.
- Rejected directions remain retrievable — `find_rejected_hypothesis_conflicts()`
  queried them successfully in every DRYRUN round (0 conflicts for DRYRUN-0007,
  as expected for a genuinely novel proposal).
- Evidence-pointer/supersession mechanics unchanged since Phase E closed.
  **PASS.**

### Phase F — canonical schema
- Proposal/result separation intact: `ExperimentProposal` structurally
  cannot hold a metric/verdict/conclusion (`check_no_result_fields_in_proposal`).
- Preregistration freeze/hash (`ExperimentSpec.freeze()`/`verify_integrity()`)
  and amendment traceability (`ExperimentSpec.amend()`, append-only
  `Amendment` records) unchanged, still the only sanctioned path to alter a
  frozen proposal.
- 7 human-authority approval flags: confirmed hard-coded `False` in
  `_build_proposal` regardless of LLM output, for both `run_dry_run_cycle`
  and the new `run_revision_only` path.
- Schema mapping: fixed this round (§1). **PASS** (previously PARTIAL, now
  closed).

### Phase G — LLM abstraction
- Free-model-only enforcement: **CODE-ENFORCED ONLY WHEN `--structured-output`
  is passed** (`evaluate_model_for_role()` runs inside `_call_llm` only `if
  model_catalog is not None`, and `model_catalog` is only populated by
  `_setup_dry_run_execution()` when `args.structured_output` is set). Every
  real Phase H live call so far DID pass this flag, so free-model-only held
  in practice — but the guarantee is conditional on an operator flag, not
  unconditional code. **See §6, CRITICAL finding.**
- No paid fallback: `LLMRouter.complete()`'s multi-model fallback loop
  exists in `research/llm/router.py` but is never called from any live code
  path (`_call_llm` always calls `router.provider.complete()` directly, one
  attempt). Confirmed via grep — zero call sites for `router.complete()`
  outside a docstring reference. **Structurally true today, fragile to
  future changes** (see §6, MEDIUM finding).
- Authorization gate: `require_authorization()` in `openrouter.py` is
  unconditional on every `complete()` call — a configured API key alone
  never authorizes a request. **CODE-ENFORCED.**
- Budget enforcement: `dry_run_budget.check()` / `usage_tracker.check_budget()`
  / `run_budget.check()` (when supplied) all run unconditionally before every
  `_call_llm` network attempt. **CODE-ENFORCED.**
- Capability-aware catalog preflight: deterministic `requests.get` +
  `evaluate_model_for_role()`, confirmed used (not WebFetch) in every
  successful round.
- Native structured output: wired for both proposal and reviewer schemas,
  `provider.require_parameters: true` set whenever `response_format` is used.
- Diagnostics: `network_attempted`, `http_status`, `request_id`,
  `token_usage`, `finish_reason` all populated and confirmed correct in
  DRYRUN-0007's three artifacts.
- Secret safety: confirmed no `sk-or-v1-` pattern in any diagnostics field,
  call record, or committed artifact.
- One logical step / one HTTP request: confirmed via `_call_llm`'s direct
  `provider.complete()` call, never `router.complete()`.
- Catalog snapshot provenance: `research/catalog_snapshots/` (gitignored)
  has a sanitized, timestamped snapshot for every live call this round.
  **PARTIAL PASS** — 2 CRITICAL/MEDIUM gaps noted above must close before
  Phase I (§6).

### Phase H — dry-run agent
- Researcher/reviewer/revision artifacts: all 3 present, immutable,
  hash-verified this round.
- Immutable evidence chain: confirmed byte-identical before/after the
  revision call.
- Canonical resume commands: `dry-run-review`/`dry-run-revise` both reuse
  `_setup_dry_run_execution()` — no divergent/standalone code path remains.
- Local-attempt vs. actual-network accounting: `network_attempted` field
  distinguishes the two in every `CallRecord`; confirmed 8→9 local counter
  delta matched exactly 1 real HTTP request for the revision round.
- No queue leakage: `actually_queued: false` in every artifact; zero calls
  to `queue_experiment_from_spec` from any dry-run code path (confirmed via
  grep — only `orchestrator.py` itself and print statements reference it).
- No production mutation: confirmed via `git diff --stat -- ios/
  benchmark/config.py` at every checkpoint this round. **PASS.**

---

## 3. Absolute rules — code-enforced vs. convention-enforced

| Rule | Status | Mechanism |
|---|---|---|
| Never auto-modify/deploy production | **CODE-ENFORCED** | no code path in `research/` or `benchmark/` writes under `ios/`; no deployment/signing code exists anywhere in the repo |
| Every executed experiment isolated in its own branch | **CODE-ENFORCED** | `create_experiment_branch()` called only from `orchestrator.run_experiment()` |
| Never fabricate results | **CODE-ENFORCED (structural) + CONVENTION (LLM honesty)** | `ExperimentProposal` cannot hold a metric/verdict (Phase F separation); but nothing stops an LLM from writing a fabricated-sounding *prose* claim in `procedure`/`motivation` — human review remains the check on that |
| Deterministic benchmark decides empirical success | **CODE-ENFORCED** | `research/experiment_validator.py::validate()`/`is_queue_eligible()` never call an LLM; reviewer's `worth_running` is explicitly documented as non-authoritative |
| Failed experiments preserved | **CODE-ENFORCED** | every DRYRUN round's artifact is a new, uniquely-named file, never overwritten (confirmed by the `dryrun_id`-in-filename fix after DRYRUN-0003/0004's collision) |
| PII/private imagery protected | **CODE-ENFORCED** | `check_payload_safe()` (privacy_guard.py) runs unconditionally in `_call_llm` before every outgoing prompt |
| Resource limits configurable | **CODE-ENFORCED** | `RunBudget`/`DryRunCallBudget` both take `max_calls`, wired to `--max-calls` |
| Kill switch/pause works | **PARTIAL — CODE-ENFORCED FOR REAL EXECUTION ONLY** | `_check_not_paused_or_stopped()` gates `orchestrator.run_experiment()` but is never checked by any Phase H LLM-call path. **CRITICAL gap for Phase I** (§6). |
| No unrestricted deployment/signing changes | **CODE-ENFORCED (by absence)** | no deployment/signing code exists in the repo at all |
| Human retains authority for high-value decisions | **CODE-ENFORCED** | 7 approval flags hard-coded `False` at every LLM-output construction site; only `ExperimentSpec.amend()` (a human-invoked, human-labeled — `approved_by` — API) can change one |
| Free-model-only (Phase G addition) | **CONDITIONAL — opt-in via `--structured-output`** | see §6, CRITICAL |
| Completed-experiment immutability | **DETECTABLE, NOT PREVENTED** | `experiment_events` logs every change; `update_fields()`/`set_research_verdict()` have no guard against a second write to an already-`COMPLETED` experiment. See §6, HIGH. |

---

## 4. Phase I threat model

| # | Threat | Status |
|---|---|---|
| 1 | Infinite/repeated proposal loops | **PREVENTED** — `DryRunCallBudget`/`RunBudget` hard-cap calls per invocation; no code path loops without an explicit new CLI invocation |
| 2 | Repeatedly proposing rejected ideas with superficial wording changes | **PARTIALLY MITIGATED** — `find_rejected_hypothesis_conflicts()` is keyword/family-based, self-documented as non-exhaustive; a cleverly-reworded proposal with zero shared keywords could slip through |
| 3 | LLM granting itself approval | **PREVENTED** — structurally impossible; no field exists in `ProposalResponse`/`ReviewerCritique` for any of the 7 approval flags, and both are rejected outright (not silently dropped) if present in raw JSON |
| 4 | Queueing scientifically incomplete proposals | **MOSTLY PREVENTED, NEWLY IMPROVED** — `PLACEHOLDER_VALUE` + `NEEDS_HUMAN_REVIEW` (this round's fix) surface incompleteness that previously passed silently; `SCIENTIFIC_MERIT` always needs human review by design |
| 5 | Executing without human approval | **PREVENTED** — dry-run pipeline never calls `queue_experiment_from_spec`; 7 approval flags hard-coded False |
| 6 | Experiment branch leakage | **PREVENTED** — confirmed zero branch-creation calls outside `orchestrator.run_experiment()` |
| 7 | Dirty-tree contamination | **DETECTED, NOT AUTOMATICALLY PREVENTED** — `git status`/`git diff` checks are manual/CLI-report only; no pre-call hook currently refuses to run against a dirty tree |
| 8 | Benchmark manipulation | **PREVENTED** — `benchmark/config.py`/baseline results never written by any research/dry-run code path |
| 9 | Success-criterion modification after results | **PREVENTED** — Phase F freeze/hash + Phase F proposal/result separation; success_criteria lives on the frozen proposal, `ExperimentResult` cannot touch it |
| 10 | Cherry-picking runs/seeds | **UNMITIGATED** — nothing in the codebase currently checks "were all pre-registered seeds/runs reported," this is purely a human-review responsibility today |
| 11 | Deleting failed experiments | **PREVENTED** — no delete path exists in `research/db.py` for experiments; DRYRUN artifacts are append-only files |
| 12 | Exceeding LLM/API budget | **PREVENTED** — `UsageTracker`/`RunBudget`/`DryRunCallBudget`, confirmed exact accounting all of Phase H |
| 13 | Exceeding GPU/runtime budget | **UNMITIGATED** — no GPU-hour/wall-clock budget mechanism exists anywhere in the codebase yet; would matter the moment Phase I permits any real training |
| 14 | Accidental paid-model routing | **CONDITIONAL** — see §6 CRITICAL; only prevented when `--structured-output`/catalog preflight is used |
| 15 | External-data acquisition without approval | **PREVENTED (structurally) for Phase H** — dry-run never downloads anything; `external_upload_approved`/`external_api_required` gate is Phase F-level and default False |
| 16 | Secret leakage | **PREVENTED** — confirmed no API key/Authorization header ever reaches a diagnostics field, call record, or artifact, across all of Phase H |
| 17 | PII/private-image leakage | **PREVENTED** — `check_payload_safe()` unconditional; dry-run never touches real user imagery at all (text-only proposals) |
| 18 | Stale model capability metadata | **PARTIALLY MITIGATED** — every live call fetches a fresh catalog snapshot immediately before the call; but the catalog fetch and the actual completion request are two separate HTTP calls (a TOCTOU window exists, however small) |
| 19 | Malformed structured output | **PREVENTED** — `parse_and_validate_proposal`/`parse_and_validate_reviewer_critique` reject any malformed/fenced/ambiguous JSON, never silently coerce |
| 20 | Provider failure halfway through a loop | **DETECTED, GRACEFULLY HANDLED** — every `_call_llm` site catches `_CALL_UNAVAILABLE`, records diagnostics, returns a `stopped_reason` — never crashes uncaught (confirmed via DRYRUN-0001 through -0006's real failures) |
| 21 | Crash/restart causing duplicate execution | **UNMITIGATED for a future autonomous loop** — no idempotency/checkpoint mechanism exists; a crash mid-loop today only matters for the CLI's single invocation (nothing to duplicate), but this becomes a real risk the moment Phase I adds a persistent loop |
| 22 | Experiment DB/artifact disagreement | **DETECTABLE** — `ExperimentSpec.verify_integrity()`'s hash check catches proposal-payload drift; no equivalent check exists yet between a DRYRUN artifact and any future queued spec derived from it |

---

## 5. Recommended Phase I authority boundary

Given the two CRITICAL gaps in §6 must close first, the recommendation
below assumes those fixes land BEFORE Phase I begins.

| Capability | Recommended initial authority | Requires explicit human approval |
|---|---|---|
| Proposing | Autonomous, budget-capped | No (matches Phase H today) |
| Reviewing | Autonomous, budget-capped | No |
| Revising (bounded, ≤1 per proposal) | Autonomous, budget-capped | No |
| Queueing | **Human required** | **Yes, every time** |
| Creating experiment branches | **Human required** | **Yes, every time** (or gated to only fire after a human queues) |
| Modifying research code | **Never autonomous** | Always human (Claude/engineer), never the loop itself |
| Training | **Never autonomous initially** | Yes — `new_training_approved` stays a real per-experiment human gate |
| Benchmarking (running an already-queued, human-approved experiment) | Autonomous **only after** human queue approval | Yes, at the queue step, not the run step |
| Downloading external data | **Never autonomous** | Yes, every time |
| Modifying production Swift | **Never autonomous** | Yes, absolute |
| Replacing CoreML models | **Never autonomous** | Yes, absolute |
| Device validation (Mac/iPhone) | **Never autonomous** | Yes, absolute — requires physical human action anyway |
| Deployment | **Never autonomous** | Yes, absolute |

**Initial Phase I scope, concretely**: an autonomous loop that may run
propose → review → (bounded revise) on a schedule/trigger, write artifacts,
and STOP — exactly what Phase H's `dry-run` command does today, minus the
manual `--authorize` invocation. It must NOT gain queueing authority in its
first iteration; that remains a human calling `omnilab experiment run` (or
an equivalent explicit queue-approval command) against a proposal a human
has read.

---

## 6. Blockers

### CRITICAL (must fix before Phase I)

1. **Kill switch does not cover LLM calls.** `omnilab pause`/`stop` only
   gates `orchestrator.run_experiment()`. An autonomous loop calling
   `_setup_dry_run_execution()`/`_call_llm()` directly would be completely
   unaffected by a human hitting pause. **Fix**: `_call_llm` (or
   `_setup_dry_run_execution`) must call `orchestrator._check_not_paused_or_stopped()`
   (or an equivalent shared check) before any network attempt.
   **RESOLVED** (hardening pass, commit `a9d7210`): new
   `research/operational_state.py` centralizes RUNNING/PAUSED/STOPPED;
   `_call_llm` calls `check_gate()` as its first statement. See
   `PHASE_I_SAFETY_INVARIANTS.md` invariants #1-4.
2. **Free-model-only enforcement is opt-in, not unconditional.**
   `evaluate_model_for_role()`'s pre-flight only runs when a caller supplies
   `model_catalog` (today: only when `--structured-output` is passed). An
   autonomous loop that forgets/omits this flag — or a future code path that
   calls `_call_llm` without it — would send requests using whatever
   `roles.yaml` says with zero runtime check. **Fix**: make the catalog
   preflight unconditional inside `_call_llm` (fetch it once per process/run
   if not already supplied), not contingent on a CLI flag.
   **RESOLVED** (hardening pass, commit `a9d7210`): `_resolve_model_catalog()`
   always resolves a catalog (caller-supplied or freshly fetched) before
   `evaluate_model_for_role()` runs; a fetch failure fails closed
   (`ModelCatalogUnavailableError`). See invariants #5-7.

### HIGH

3. **Completed-experiment immutability is audit-logged, not lock-enforced.**
   `OmniLabDB.update_fields()`/`set_research_verdict()` have no guard
   refusing a second write to an experiment whose `execution_status` is
   already `COMPLETED`. **Fix**: add an explicit `ImmutableExperimentError`
   guard before Phase I gains any code path that could plausibly touch an
   experiment row programmatically.
   **RESOLVED** (hardening pass, commit `ac18707`): both methods now raise
   `ImmutableExperimentError` unless `allow_amendment=True` + a non-empty
   `reason`, which is itself logged to `experiment_events`. EXP-0001..0005
   verified unchanged. See invariants #12-15.
4. **No GPU/runtime budget mechanism.** Irrelevant while Phase H never
   trains anything; becomes a real gap the moment any future phase permits
   real training. **Fix before that phase, not necessarily before Phase I's
   propose/review/revise-only scope.**
   **RESOLVED (infrastructure only)** (hardening pass, commit `9103d8a`):
   new `research/execution_budget.py::require_execution_budget()`, fail
   closed on missing config/authorization. Not yet wired to any real
   training code path (none exists) — built ahead of need, per instruction.
   See invariants #16-17.

### MEDIUM

5. `LLMRouter.complete()`'s multi-model fallback loop still exists and is
   reachable if any future code calls it directly, reintroducing the
   DRYRUN-0001 bug class. Recommend deprecating/removing it or adding an
   assertion that it is never called from `research/dry_run/`.
   **RESOLVED (proven via test, not deleted)** (commit `a9d7210`): regression
   tests monkeypatch `LLMRouter.complete` to raise if invoked and run the
   full canonical path through it — proven unreachable. The method itself
   was kept (documented as legacy/unused-by-canonical-path). See invariant #8-9.
6. `find_rejected_hypothesis_conflicts()` is keyword-based, not semantic —
   self-documented residual risk (threat #2).
   **PARTIALLY RESOLVED** (commit `ad99964`): broadened keyword pool
   (dependent_variables, control/baseline text). Still explicitly documented
   as a guardrail, not proof of novelty — the residual gap is real and
   proven by a passing test, not just claimed. See invariant #20.
7. No dirty-tree pre-flight check before a live call (threat #7) — currently
   a manual verification step in this workflow, not automated.
   **RESOLVED for branch creation** (commit `9103d8a`): `git_isolation.py::
   require_clean_tree()`, reports exactly which paths are dirty, wired into
   `create_experiment_branch()`. Not yet wired into any other future
   operation (training/benchmark-writing) since none exists yet. See
   invariant #18-19.
8. Catalog-fetch-then-complete is two separate HTTP calls — a small
   TOCTOU window on model capability metadata (threat #18).
   **PARTIALLY RESOLVED** (commit `a9d7210`): the fetch is now bound as
   closely as practical to the actual request (per-call fresh fetch when no
   catalog was pre-supplied), and a returned-model mismatch is independently
   detected and rejected (`ModelProvenanceMismatchError`). The window itself
   cannot be fully closed — documented, not solved. See invariant #10-11.

---

## 7. Final recommendation

**As originally written: READY_WITH_RESTRICTIONS**, pending the two
CRITICAL blockers.

**UPDATED (hardening pass complete, same day): READY_FOR_PHASE_I_PROPOSAL_ONLY.**

Both CRITICAL blockers and all HIGH/MEDIUM findings above are now RESOLVED
or PARTIALLY RESOLVED-and-documented (see each item's update above and the
full invariant table in `reports/phase_i/PHASE_I_SAFETY_INVARIANTS.md`).
"PROPOSAL_ONLY" qualifies this: the recommendation is specifically for the
conservative initial scope in §5 — autonomous propose/review/bounded-revise
only, human-gated queueing/training/deployment. Phase I itself remains
UNAUTHORIZED pending explicit human sign-off; this document and the
hardening pass only establish that the infrastructure is ready for that
scope, not that Phase I is approved to begin.
