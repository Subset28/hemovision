# Failed Methods

> Read `research/memory/README.md` first.

## Already established (Phase B.5, treated as prior art here, not a new experiment)

- **Lowering the confidence threshold to fix Person recall.** conf=0.05
  roughly doubles Person recall (0.211->0.479) but collapses precision
  (0.667->0.312) — see `research/memory/known_failures.md`. This is not a
  fresh negative result from this lab's own orchestrator; it's Phase B.5
  diagnostic evidence being carried forward so nobody re-proposes "just lower
  the threshold" as if it were a novel idea. EXP-0001 formally confirms this
  via the orchestrator pipeline.

This file is otherwise empty at Phase C seed time — updated by
`research/orchestrator.py`'s `experiment()` command whenever a verdict is
FAILED or REJECTED, with enough detail (independent variable, what broke,
which guardrail) that the same mistake isn't repeated.

## EXP-0002 (2026-09-04T23:21:45.894618+00:00)

- Family: small_object
- Status: FAILED
- Hypothesis: Increased inference-time input resolution (640->960 or 640->1280) meaningfully improves Person recall, at some measurable latency cost.
- Reasons: guardrail 'hazard.recall' violated: 0.4491 does not satisfy gte 0.4604 (hazard recall must not drop more than 0.02 below baseline)

## EXP-0003 (2026-09-04T23:53:42.838654+00:00)

- Family: class_confusion
- Status: FAILED
- Hypothesis: A meaningful fraction of Person recall loss at the baseline conf=0.4 operating point is attributable to the detector correctly localizing a human-shaped region but labeling it with a semantically related non-Person class (Man/Woman/Boy/Girl/Human body/person-subparts), NOT to the detector failing to notice a person at all. Every Person ground-truth false negative is classified into exactly one of 5 mutually-exclusive primary categories (so percentages sum to 100%): (A) TRUE_DETECTOR_MISS -- no spatially relevant human-like prediction of any class exists near the GT box at any non-noise confidence; (B) LOW_CONFIDENCE_PERSON -- a Person prediction exists at sufficient IoU (>=0.5) but below the 0.4 production confidence threshold; (C) SEMANTIC_CLASS_CONFUSION -- a different human-related class (Man/Woman/Boy/Girl/Human body/a person subpart) is predicted at sufficient IoU (>=0.5) and at/above a diagnostic confidence floor (0.4, matching the production threshold); (D) LOCALIZATION_FAILURE -- a human-related prediction exists nearby but its IoU with the GT box is below the 0.5 match threshold (though still >=0.3, the 'spatially associated' floor); (E) DUPLICATE_MULTI_LABEL is reported as a secondary/overlapping flag (not a primary bucket) when >=2 distinct human-related classes are predicted over the same GT box.
- Reasons: guardrail 'hazard.precision' violated: 0.6785 does not satisfy gte 0.7570 (hazard precision must not drop more than 0.05 below baseline)
