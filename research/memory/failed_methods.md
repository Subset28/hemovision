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
