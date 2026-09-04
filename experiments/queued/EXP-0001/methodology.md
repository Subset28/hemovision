# EXP-0001 — Methodology

## Independent variable

confidence_threshold (evaluated post-hoc from an existing conf=0.01 capture; benchmark/config.py's real conf=0.4 is unchanged)

## Controls (held constant)

- `model`: yolov8m-oiv7.pt (same weights as the canonical baseline)
- `manifest`: data/manifests/eval_manifest.jsonl (unchanged)
- `iou_threshold`: 0.7
- `imgsz`: 640

## Evaluation method

Read benchmark/results/diagnostics/threshold_sweep.json's conf=0.4 (baseline) and conf=0.05 (candidate) buckets; apply research.evaluation_policy's default hazard policy. A hard evaluation-policy FAILED verdict (precision guardrail badly violated) CONFIRMS this experiment's hypothesis and maps to a final PASSED status.

## Success criteria (checked by research/evaluation_policy.py)

- `hypothesis_confirmed_if`: candidate hazard.precision violates the (baseline-0.05) guardrail by more than the noise margin, while person.recall improves by more than the minimum-meaningful-delta

## Baseline compared against

`RUN-20260904-002` (see `benchmark/results/baseline/run_metadata.json`
if this is the canonical baseline, or `benchmark/results/diagnostics/` for a
diagnostic-derived baseline).
