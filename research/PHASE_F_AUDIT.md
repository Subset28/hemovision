# Phase F — audit of the pre-Phase-F experiment representation

Read before/alongside `research/README.md`'s Phase F section. This is the
field-by-field accounting item #1 of the Phase F task required, produced by
reading `research/db.py`, `research/evaluation_policy.py`,
`research/experiment_registry.py`, `research/experiment_lifecycle.py`,
`research/experiment_schema.py`, `research/runners.py`, `research/orchestrator.py`,
`research/cli.py`, `research/memory_db.py`, and every artifact under
`experiments/completed/EXP-0001/` through `EXP-0005/`.

## Already exists as a typed `research/db.py::Experiment` dataclass field

`experiment_id`, `hypothesis`, `motivation`, `rationale`, `independent_variable`
(singular — one string, not a list), `controls` (dict), `evaluation_method`,
`success_criteria` (dict, free-form — NOT machine-validated, see below),
`risks`, `expected_outcome`, `parent_experiment_id`, `experiment_family`,
`git_branch`, `start_commit`, `end_commit`, `model_version`, `dataset_version`,
`configuration`, `baseline_run_id` (free string, NOT resolved against a real
artifact at construction time — `OmniLabDB.resolve_baseline_run_dir` checks
it, but only as a separate, optional call, not enforced at insert time),
`result_run_id`, `execution_status`, `research_verdict`, `metrics`,
`conclusion`, `validation_requirement`, `estimated_cost`, `created_at`,
`updated_at`, `completed_at`, `llm_model_used`, `llm_tokens_used`,
`llm_cost_usd`.

## Already exists only as free-form markdown/YAML per experiment

`experiments/<status>/EXP-XXXX/hypothesis.md` — restates `hypothesis`,
`motivation`, `rationale`, `expected_outcome`, `risks` as prose (see
"duplicated" below); `methodology.md` — restates `independent_variable`,
`controls`, `evaluation_method`, `success_criteria`, plus a great deal of
PROSE that has no DB column at all: the detailed candidate lists,
inclusion/exclusion rationale, pre-registered secondary comparisons,
vocabulary-handling notes (EXP-0003/0004/0005's methodology.md files),
"overall verdict convention" narrative. `config.yaml` — a YAML re-serialization
of a subset of the same `Experiment` fields (`experiment_id`,
`experiment_family`, `independent_variable`, `controls`, `configuration`,
`baseline_run_id`, `validation_requirement`, `estimated_cost`); `results.json`
(free-form dict, shape varies per experiment — EXP-0001..0004 use
`final_experiment_status`, EXP-0005 uses `execution_status`/`research_verdict`
directly — see "duplicated"/"inconsistent" below); `analysis.md`,
`conclusion.md` (pure prose); `patch.diff`, `benchmark.log` (raw text/diff).

## Duplicated (same fact recorded in two places, no single source of truth)

- Hypothesis/motivation/rationale/expected_outcome/risks text: present
  BOTH as `Experiment` dataclass fields AND re-rendered verbatim into
  `hypothesis.md` by `research/experiment_schema.py::hypothesis_md()`. This
  duplication is intentional and low-risk (the .md is a derived
  rendering, always regenerated from the DB row, never hand-edited
  independently) — Phase F does not need to fix this, just note it.
- `execution_status`/`research_verdict`: recorded in the DB row (source of
  truth) AND informally re-stated inside `results.json` per experiment, but
  INCONSISTENTLY — EXP-0001..0004's `results.json` files use a legacy key
  `final_experiment_status` (a single conflated PASS/FAILED string, pre-dating
  the Phase C.5 status/verdict split) with no `execution_status` key at all,
  while EXP-0005's `results.json` uses the current
  `execution_status`/`research_verdict` pair directly. This is a real,
  historical inconsistency Phase F's backfill has to normalize explicitly
  (see `research/backfill_experiment_specs.py`), not paper over.
- `baseline_run_id`: present in both the DB row and each experiment's
  `config.yaml`, always identical (`RUN-20260904-002` for all 5) — low risk,
  same "derived rendering" pattern as above.

## Missing entirely (did not exist in any form before Phase F)

- `schema_version` on anything — no versioning concept existed on the
  per-experiment record at all.
- Explicit, structured `evidence_references` linking a proposal to Phase-E
  `research/memory_db.py` finding IDs — Phase E's memory DB postdates
  EXP-0001..0005 entirely (see backfill policy).
- Explicit human-authority approval flags — `research/README.md`'s
  Phase C "MAY NOT do" section is enforced by convention/code review, not by
  a machine-checkable field on the experiment record itself.
- Explicit amendment records — nothing in `research/db.py` distinguishes "the
  proposal was corrected before running" from "the proposal was written once
  and never touched"; `update_fields()` allows arbitrary field mutation with
  no reason/timestamp/approver trail for anything except `execution_status`/
  `research_verdict` transitions (which DO have `experiment_events`).
- A genuine proposal/result SEPARATION — `Experiment` is one flat dataclass
  where pre-registered fields (hypothesis, success_criteria) and
  post-execution fields (metrics, conclusion, research_verdict) live
  side-by-side with no structural barrier preventing a result field from
  being set before a proposal is even queued (nothing currently stops
  `create_experiment()` from being called with `metrics` already populated).
- Pre-registered interpretation conditions as three separate fields
  (`supports_hypothesis_if`/`rejects_hypothesis_if`/`inconclusive_if`) —
  EXP-0001's `success_criteria` dict has a single freeform
  `hypothesis_confirmed_if` key that gestures at this but was never split
  into a genuine 3-way PASS/FAIL/INCONCLUSIVE pre-registration.
- A machine-checkable success-criteria SCHEMA — every experiment's
  `success_criteria` dict has ad-hoc, experiment-specific keys
  (`hypothesis_confirmed_if`, `representative_candidate_selection`,
  `candidates_preregistered`, `overall_pass_requires`, ...), which is fine
  for human-readable methodology docs but cannot be mechanically validated
  (no fixed key vocabulary, no type constraints, no way to check "is this
  even a coherent criterion").
- An 8th experiment family for application-level decision/announcement logic
  (TTS/SpeechEngine-adjacent) — genuinely distinct from family G
  (temporal_pipeline, about tracking/temporal smoothing) but not covered by
  any of the existing 7.

## Should stay human-readable prose (not converted to validated structured fields)

`methodology.md`'s narrative procedure description (candidate rationale,
expected-benefit/failure-mode reasoning, compute-cost estimates in prose),
`analysis.md`/`conclusion.md`'s interpretive prose. Phase F's `procedure` and
`reproducibility_requirements` fields hold a SUMMARY string, not a
line-by-line structured re-encoding of this prose — converting candidate
rationale into a rigid schema would either lose information or force
premature structure onto genuinely narrative scientific reasoning. This is a
deliberate Phase F boundary, consistent with the task's explicit instruction
not to over-formalize prose that is working fine as prose.

## Converted to validated, structured fields in Phase F

`success_criteria` gains a fixed (though still extensible) key vocabulary
(`primary_metric`, `min_meaningful_delta`, `precision_floor`,
`max_latency_regression_pct`, `required_tests_pass`,
`sample_size_requirements`, `guardrail_metrics`) that
`research/experiment_validator.py` can mechanically check for contradictions
and unknown metric names; `independent_variables`/`dependent_variables`
become explicit tuples (not one freeform string) that the
rejected-hypothesis-acknowledgment check (item #8) can do keyword matching
against; `baseline_run_id` is validated at proposal-validation time (not just
optionally, later) to resolve to a real `benchmark/results/{baseline,
diagnostics}/run_metadata.json`; `evidence_references`/`prior_experiment_ids`
are validated to resolve against real Phase-E memory records/DB rows.
