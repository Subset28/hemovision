# EXP-0004 — Methodology

## Independent variable

one preprocessing transform (e.g. CLAHE) applied before inference

## Controls (held constant)

- `model`: yolov8m-oiv7.pt (same weights)
- `conf_threshold`: 0.4
- `iou_threshold`: 0.7
- `imgsz`: 640
- `manifest`: data/manifests/eval_manifest.jsonl (unchanged)

## Evaluation method

Run real inference over the eval manifest with the transform applied to each image before the model call; compare against the canonical baseline via research.evaluation_policy's default hazard policy.

## Success criteria (checked by research/evaluation_policy.py)

- `primary_metric`: person.recall
- `min_meaningful_delta`: 0.03
- `guardrails`: ['hazard.precision >= baseline-0.05', 'latency.p95_ms <= baseline*1.5']

## Baseline compared against

`RUN-20260904-002` (see `benchmark/results/baseline/run_metadata.json`
if this is the canonical baseline, or `benchmark/results/diagnostics/` for a
diagnostic-derived baseline).
