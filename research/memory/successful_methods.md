# Successful Methods

> Read `research/memory/README.md` first.

Empty at Phase C seed time — no experiment has PASSED yet. This file is
updated by `research/orchestrator.py`'s `experiment()` command whenever an
experiment's evaluation-policy verdict is PASSED, with: experiment_id, what
changed, the measured effect (with sample-size context), and why it was
judged a genuine win (not noise) per `research/evaluation_policy.py`.

## EXP-0001 (2026-09-04T23:18:36.396427+00:00)

- Family: threshold_postprocessing
- Status: PASSED
- Hypothesis: The existing threshold sweep (benchmark/results/diagnostics/threshold_sweep.json) accurately characterizes the precision/recall tradeoff, and threshold alone cannot resolve Person recall without unacceptable precision loss.
- Reasons: guardrail 'hazard.precision' violated: 0.3814 does not satisfy gte 0.7570 (hazard precision must not drop more than 0.05 below baseline)
