# Model Variant Comparison Analysis (EXP-0005)

Diagnostic/measurement-only experiment. 380 static Open Images V7 photographs, Windows/CUDA proxy hardware (RTX 3070 Ti) -- no CoreML/ANE execution, no video/tracking/LiDAR/TTS/real-camera processing/real accessibility scenarios. Every latency figure below is a Windows/CUDA inference-compute proxy only, NOT iPhone. No production model is replaced by this experiment regardless of outcome; ios/ is never touched. See `experiments/*/EXP-0005/{hypothesis.md,methodology.md,analysis.md,conclusion.md}` for the full pre-registration and reasoning.

Official baseline (`RUN-20260904-002`): hazard-8 P=0.8070 R=0.4804; Person P=0.6667 R=0.2112 (num_gt=303); latency p95=57.13ms.

## Common-class definition

Primary cross-model comparison classes: ['Bicycle', 'Bus', 'Car', 'Dog', 'Motorcycle', 'Person', 'Truck']. Excluded (no COCO equivalent, structural gap): ['Stairs'].

## Comparison table (common-class hazard + Person, fixed conf=0.4)

| Candidate | Vocab | Params(M) | Size(MB) | Hazard-common P | Hazard-common R | Person P | Person R | Person F1 | Person AP50 | Inference p50 (ms) | Inference p95 (ms) | Peak GPU (MB) | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A_yolov8m_oiv7_baseline | oiv7 | 26.2 | 50.29 | 0.8134 | 0.4896 | 0.6667 | 0.2112 | 0.3208 | 0.1743 | 27.99 | 69.73 | 204.5 | INCONCLUSIVE |
| B_yolov8n_oiv7_smaller | oiv7 | 3.5 | 6.89 | 0.7846 | 0.3384 | 0.6923 | 0.1188 | 0.2028 | 0.0966 | 21.40 | 54.47 | 187.1 | FAILED |
| C_yolo11m_coco_newer_arch | coco | 20.11 | 38.8 | 0.4540 | 0.6921 | 0.2930 | 0.5677 | 0.3865 | 0.2574 | 28.97 | 61.15 | 203.4 | FAILED |
| D_yolov8l_oiv7_diagnostic_upper_bound (representative) | oiv7 | 44.09 | 84.48 | 0.8047 | 0.5201 | 0.6542 | 0.2310 | 0.3415 | 0.1988 | 35.15 | 48.69 | 372.6 | INCONCLUSIVE |

**Overall representative candidate**: `D_yolov8l_oiv7_diagnostic_upper_bound` (final status = INCONCLUSIVE).

## Precision-matched / guardrail-matched Person recall (fair-comparison sweep)

| Candidate | Precision-matched threshold | Precision-matched recall | Guardrail-matched threshold | Guardrail-matched recall |
|---|---|---|---|---|
| A_yolov8m_oiv7_baseline | 0.4 | 0.21122112211221122 | 0.35 | 0.24422442244224424 |
| B_yolov8n_oiv7_smaller | 0.35 | 0.1551155115511551 | 0.35 | 0.1551155115511551 |
| C_yolo11m_coco_newer_arch | 0.95 | 0.006600660066006601 | 0.9 | 0.12211221122112212 |
| D_yolov8l_oiv7_diagnostic_upper_bound | 0.45 | 0.21122112211221122 | 0.35 | 0.264026402640264 |

Fixed-threshold (conf=0.4) recall gains must be read alongside this table -- a candidate with different confidence calibration can look artificially better at conf=0.4 alone while offering no real advantage once precision is matched to the baseline's own operating point.

## TRUE_DETECTOR_MISS recovery (headline comparison; 92 baseline cases, 0/92 recovered by EXP-0004's preprocessing)

| Candidate | gained_any_person_candidate | gained_tp | gained_other_human_class | remains_complete_miss |
|---|---|---|---|---|
| B_yolov8n_oiv7_smaller | 50 | 0 | 0 | 42 |
| C_yolo11m_coco_newer_arch | 83 | 17 | 0 | 9 |
| D_yolov8l_oiv7_diagnostic_upper_bound | 71 | 1 | 0 | 21 |

## Per-candidate failure-bucket transitions (of the 239 baseline Person FNs) and baseline-TP regressions

### B_yolov8n_oiv7_smaller

| Baseline bucket | n | -> TP | new-bucket breakdown |
|---|---|---|---|
| TRUE_DETECTOR_MISS | 92 | 0 | {'TRUE_DETECTOR_MISS': 85, 'LOW_CONFIDENCE_PERSON': 7} |
| LOW_CONFIDENCE_PERSON | 82 | 1 | {'LOW_CONFIDENCE_PERSON': 57, 'TRUE_DETECTOR_MISS': 21, 'LOCALIZATION_FAILURE': 3, 'TP': 1} |
| SEMANTIC_CLASS_CONFUSION | 13 | 0 | {'TRUE_DETECTOR_MISS': 8, 'LOW_CONFIDENCE_PERSON': 4, 'LOCALIZATION_FAILURE': 1} |
| LOCALIZATION_FAILURE | 52 | 0 | {'TRUE_DETECTOR_MISS': 32, 'LOW_CONFIDENCE_PERSON': 12, 'LOCALIZATION_FAILURE': 8} |

Baseline Person TP regressions: 29/64 regressed (35 remained TP).

Small-Person (<2% GT area) recovery: TRUE_DETECTOR_MISS: 0/68 recovered, LOW_CONFIDENCE_PERSON: 0/49 recovered, SEMANTIC_CLASS_CONFUSION: 0/3 recovered, LOCALIZATION_FAILURE: 0/33 recovered

### C_yolo11m_coco_newer_arch

| Baseline bucket | n | -> TP | new-bucket breakdown |
|---|---|---|---|
| TRUE_DETECTOR_MISS | 92 | 17 | {'TRUE_DETECTOR_MISS': 45, 'TP': 17, 'LOW_CONFIDENCE_PERSON': 22, 'LOCALIZATION_FAILURE': 8} |
| LOW_CONFIDENCE_PERSON | 82 | 64 | {'TP': 64, 'TRUE_DETECTOR_MISS': 2, 'LOW_CONFIDENCE_PERSON': 12, 'LOCALIZATION_FAILURE': 4} |
| SEMANTIC_CLASS_CONFUSION | 13 | 12 | {'TP': 12, 'LOW_CONFIDENCE_PERSON': 1} |
| LOCALIZATION_FAILURE | 52 | 20 | {'TP': 20, 'LOCALIZATION_FAILURE': 13, 'TRUE_DETECTOR_MISS': 7, 'LOW_CONFIDENCE_PERSON': 12} |

Baseline Person TP regressions: 5/64 regressed (59 remained TP).

Small-Person (<2% GT area) recovery: TRUE_DETECTOR_MISS: 14/68 recovered, LOW_CONFIDENCE_PERSON: 39/49 recovered, SEMANTIC_CLASS_CONFUSION: 3/3 recovered, LOCALIZATION_FAILURE: 16/33 recovered

### D_yolov8l_oiv7_diagnostic_upper_bound

| Baseline bucket | n | -> TP | new-bucket breakdown |
|---|---|---|---|
| TRUE_DETECTOR_MISS | 92 | 1 | {'TRUE_DETECTOR_MISS': 79, 'TP': 1, 'LOW_CONFIDENCE_PERSON': 12} |
| LOW_CONFIDENCE_PERSON | 82 | 11 | {'LOW_CONFIDENCE_PERSON': 59, 'TP': 11, 'TRUE_DETECTOR_MISS': 11, 'LOCALIZATION_FAILURE': 1} |
| SEMANTIC_CLASS_CONFUSION | 13 | 0 | {'TRUE_DETECTOR_MISS': 9, 'LOW_CONFIDENCE_PERSON': 4} |
| LOCALIZATION_FAILURE | 52 | 1 | {'TRUE_DETECTOR_MISS': 28, 'LOCALIZATION_FAILURE': 7, 'LOW_CONFIDENCE_PERSON': 16, 'TP': 1} |

Baseline Person TP regressions: 7/64 regressed (57 remained TP).

Small-Person (<2% GT area) recovery: TRUE_DETECTOR_MISS: 0/68 recovered, LOW_CONFIDENCE_PERSON: 2/49 recovered, SEMANTIC_CLASS_CONFUSION: 0/3 recovered, LOCALIZATION_FAILURE: 0/33 recovered

## Notes

See `benchmark/results/diagnostics/model_variant_analysis.json` for the complete per-candidate, per-record data this report summarizes, and `experiments/completed/EXP-0005/{model_comparison.json,person_transitions.json}` for the structured artifacts.