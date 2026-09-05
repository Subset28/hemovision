# Phase H — Completion Report

**Status: CLOSED / PASSED** (human sign-off received 2026-09-05)

## 1. What Phase H set out to prove

That OmniLab can make a controlled, authorized, budget-bounded, auditable
cloud-LLM call chain — researcher → deterministic redundancy/schema check →
independent reviewer → bounded revision — and that the result is genuinely
evidence-grounded, non-redundant, and never capable of executing, queueing,
or approving anything on its own.

## 2. Evidence chain (immutable, chronologically ordered)

| Artifact | Commit | Content |
|---|---|---|
| `research/dry_run_proposals/DRYRUN-0007.json` | pre-existing | Researcher proposal: `training_data` family, COCO-pretraining-vs-baseline hypothesis targeting Person recall |
| `research/dry_run_proposals/DRYRUN-0007-review.json` | pre-existing | Independent reviewer critique, `recommends_revision: true`, flagged baseline-provenance + leakage-risk confounds unprimed |
| `research/dry_run_proposals/DRYRUN-0007-revision.json` | `e43d458` | Revision: redesigned control condition (two newly-trained conditions, COCO-init vs ImageNet-init) instead of the shipped baseline; added deterministic train/eval isolation procedure; 3-seed design |

All three files are byte-identical to what each live call produced. No file
was ever edited after being written. Each round used the canonical
`_setup_dry_run_execution()` init path (`omnilab dry-run` /
`dry-run-review` / `dry-run-revise`) — no standalone script at any point
after the one standalone-script mistake in the reviewer round (caught,
reported, replaced with the canonical `dry-run-review` command before any
further live call).

## 3. Demonstrated capabilities (accepted per human sign-off)

- researcher used accumulated Phase E evidence rather than repeating
  EXP-0001–0005
- researcher proposed a materially new training-data/pretraining experiment
- deterministic schema/redundancy validation worked (0 conflicts, `is_valid:
  true` at every stage)
- reviewer independently found genuine causal-design flaws, unprimed
- reviewer recommendation was `REVISE`, not generic approval
- reviser incorporated the critique
- reviser did not fabricate unknown baseline provenance
- reviser redesigned the causal comparison rather than hiding the confound
- dataset isolation became an explicit design requirement
- stochastic training was upgraded to a 3-seed design
- established precision/recall guardrails (hazard.precision ≥0.757,
  min_meaningful_delta 0.03) were preserved unchanged
- original proposal and review remained immutable throughout
- no proposal was ever queued (`actually_queued: false` in every artifact)
- no EXP-0006 was created
- no experiment branch was created
- production/`ios/`/`benchmark/config.py` remained untouched
- real API failures throughout Phase H (DRYRUN-0001 through -0006) failed
  safely — never silently retried, never fabricated a result
- bounded call accounting held at every round (local-attempt counter
  exactly matched real `network_attempted` HTTP requests once the
  remediation build's diagnostics were in place)
- free-model-only enforcement held for every live call actually made

## 4. Live-call accounting (full Phase H history)

| Round | Local attempts before→after | Real HTTP requests | Outcome |
|---|---|---|---|
| DRYRUN-0001 | — | 3 (router-fallback bug) | Failed — bug found, fixed |
| DRYRUN-0002–0004 | — | 3 | Failed — led to remediation build |
| DRYRUN-0005–0006 | — | 2 | Failed — reasoning-negotiation bug found, fixed |
| DRYRUN-0007 researcher | 6→7 | 1 | **Succeeded** |
| DRYRUN-0007 reviewer attempt 1 | 7→8 | **0** (`.env` not loaded in a standalone script) | Failed pre-network — script replaced with canonical `dry-run-review` |
| DRYRUN-0007 reviewer (canonical) | — | 1 | **Succeeded** |
| DRYRUN-0007 revision (canonical `dry-run-revise`) | 8→9 | 1 | **Succeeded** |

Every failed round is preserved (`reports/dry_run/`,
`reports/openrouter/OPENROUTER_INTEGRATION_AUDIT.md`) — nothing was deleted.

## 5. Schema-mapping gap found and fixed (this round)

While reconciling DRYRUN-0007's revision against the canonical
`ExperimentProposal` schema, an audit found that `ProposalResponse` (the
LLM-facing schema) had no field for 7 canonical fields:
`reproducibility_requirements`, `dataset_version`, `isolation_requirements`,
`compute_resource_estimate`, `model_config_ref` (user-flagged) plus two more
found during the full field-by-field audit — `baseline_metrics` and
`allowed_path_scope` — both silently `{}`/`()` in every proposal Phase H
ever produced, including DRYRUN-0007's.

Fixed in commit `3bcebb5` — see
`reports/phase_i/PHASE_I_READINESS_AUDIT.md`'s field-mapping matrix for the
full field-by-field classification. Summary: the 5 judgment fields are now
LLM-authorable (required in the native structured-output schema) with a
deterministic placeholder-garbage rejection (`PLACEHOLDER_VALUE` ERROR) so a
bare "TBD" can never satisfy validation, while a real explicit-prerequisite
sentence is always accepted; `baseline_metrics`/`allowed_path_scope` are now
derived deterministically (never LLM-authored) from the real baseline
artifact and the family registry respectively.

`DRYRUN-0007-revision.json` was **not** rewritten — see
`reports/phase_h/DRYRUN-0007_SCHEMA_COMPATIBILITY.md` for a read-only
compatibility report showing how it would map under the fixed schema
without mutating history.

## 6. Test coverage added this round

- `tests/test_schema_mapping_fix.py` — 39 tests (baseline lookup, `_build_proposal`
  deterministic-field wiring, placeholder rejection, NEEDS_HUMAN_REVIEW additions)
- Updated 3 existing fixture files for the new required schema fields
- Full suite: **562 passed**, 0 live external calls in any test (repo-wide
  socket guard in `tests/conftest.py`)

## 7. Production-safety verification (re-run at closeout)

- `git diff --stat -- ios/ benchmark/config.py` → empty
- `benchmark/results/baseline/` (`RUN-20260904-002`) unchanged
- `research/omnilab.db` experiments table: exactly EXP-0001..EXP-0005,
  all `COMPLETED`
- `git branch --list "experiment/*"` → exactly EXP-0001..EXP-0005
- No secret pattern (`sk-or-v1-`) in any diff or committed artifact

## 8. Recommendation

Phase H is CLOSED/PASSED. See `reports/phase_i/PHASE_I_READINESS_AUDIT.md`
for the full A–H readiness audit, threat model, and Phase I authority
recommendation — **Phase I itself remains unauthorized** pending that
report's review.
