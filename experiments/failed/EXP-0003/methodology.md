# EXP-0003 — Methodology

## Independent variable

scoring-time class grouping map (measurement only, not a production change)

## Controls (held constant)

- `model`: yolov8m-oiv7.pt (same weights, same predictions)
- `conf_threshold`: 0.4
- `iou_threshold`: 0.7
- `manifest`: data/manifests/eval_manifest.jsonl (unchanged)

## Evaluation method

Recompute directly from raw predictions + ground truth (benchmark/results/baseline/predictions.jsonl for the official conf=0.4 detections, benchmark/results/diagnostics/low_conf_predictions.jsonl -- already captured in Phase B.5 -- for the full conf=0.01 per-box candidate pool, data/manifests/eval_manifest.jsonl for ground truth) via benchmark/diagnostics/person_confusion_analysis.py's classify_false_negatives(), which reuses benchmark.metrics.greedy_match (not a reimplementation) for the actual FN determination and per-image candidate scoping. Four diagnostic counterfactual rescorings (benchmark/diagnostics/person_counterfactuals.py) then ask 'what if a whole-person-alias/subpart prediction were scored as a Person hit' at various confidence floors, reporting Person AND hazard-level precision/recall plus the number of new false positives introduced for every counterfactual -- never recall alone. NO new inference is run; benchmark/config.py and benchmark/results/baseline/ are never touched.

## Success criteria (checked by research/evaluation_policy.py)

- `primary_metric`: person.recall
- `candidate_fed_to_policy`: counterfactual B (whole-person alias set {Man,Woman,Boy,Girl,Human body} accepted as Person at IoU>=0.5 and confidence>=0.4 -- the SAME production threshold). Counterfactuals A/C/D are computed and reported for completeness but are not themselves fed into the pass/fail guardrail check, since B is the most direct scoring-time realization of this experiment's hypothesis.
- `guardrails`: research.evaluation_policy.default_hazard_policy, UNMODIFIED (hazard.precision >= baseline-0.05, hazard.recall >= baseline-0.02, latency.p95_ms <= baseline*1.5)
- `min_meaningful_delta`: 0.03
- `note_on_policy_adaptation`: This is a diagnostic/measurement-only experiment -- no production model or config candidate is actually deployed. The standard hazard guardrails are applied unmodified anyway (not loosened) because they still answer the meaningful underlying question here: 'if this scoring remap were ever turned into a real postprocessing rule, would it hold hazard-level precision/recall?' A hard guardrail violation is treated as a genuine FAILED verdict for that counterfactual, not silently downgraded to PASSED or hand-waved away.

## Baseline compared against

`RUN-20260904-002` (see `benchmark/results/baseline/run_metadata.json`
if this is the canonical baseline, or `benchmark/results/diagnostics/` for a
diagnostic-derived baseline).
