# EXP-0001 — Hypothesis

**Family**: threshold_postprocessing
**Validation requirement**: OFFLINE_SIMULATABLE
**Parent experiment**: (none)

## Hypothesis

The existing threshold sweep (benchmark/results/diagnostics/threshold_sweep.json) accurately characterizes the precision/recall tradeoff, and threshold alone cannot resolve Person recall without unacceptable precision loss.

## Motivation

Phase B.5's diagnostic threshold sweep already showed Person recall roughly doubling (0.211->0.479) at conf=0.05 while precision collapses (0.667->0.312). This experiment formalizes that finding through the real omnilab pipeline as a confirmatory/control run — the safest possible first real experiment, since it requires no new inference code and no code changes at all.

## Rationale

Confirms a large-sample (Person, GT=303), already-verified finding rather than discovering something new — deliberately low-risk per the master spec's instruction to prove the pipeline works before running anything more speculative.

## Expected outcome

Hypothesis confirmed (final status PASSED); no production recommendation changes.

## Risks

None — read-only analysis of already-approved diagnostic data, no code change.
