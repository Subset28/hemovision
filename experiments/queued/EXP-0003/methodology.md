# EXP-0003 — Methodology

## Independent variable

scoring-time class grouping map (measurement only, not a production change)

## Controls (held constant)

- `model`: yolov8m-oiv7.pt (same weights, same predictions)
- `conf_threshold`: 0.4
- `iou_threshold`: 0.7
- `manifest`: data/manifests/eval_manifest.jsonl (unchanged)

## Evaluation method

Re-score the EXISTING baseline predictions.jsonl with a {Person,Man,Woman} super-class remap applied only at scoring time; compare recomputed recall against the strict-label baseline recall.

## Success criteria (checked by research/evaluation_policy.py)

- `primary_metric`: person_superclass.recall
- `min_meaningful_delta`: 0.05

## Baseline compared against

`RUN-20260904-002` (see `benchmark/results/baseline/run_metadata.json`
if this is the canonical baseline, or `benchmark/results/diagnostics/` for a
diagnostic-derived baseline).
