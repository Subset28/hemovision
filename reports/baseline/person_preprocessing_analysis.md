# Person Preprocessing Analysis (EXP-0004)

Diagnostic/measurement-only experiment. 380 static Open Images V7 photographs, Windows/CUDA proxy hardware — no video/tracking/LiDAR/TTS/real-camera processing/real accessibility scenarios. Every latency figure below is a Windows/CUDA inference-compute proxy only, not iPhone, not end-to-end. See `experiments/*/EXP-0004/{hypothesis.md,methodology.md,analysis.md,conclusion.md}` for the full pre-registration and reasoning.

Official baseline (`RUN-20260904-002`): hazard P=0.8070 R=0.4804; Person P=0.6667 R=0.2112 (num_gt=303); latency p95=57.13ms (inference only, no preprocessing).

**Identity/no-op control reproduces baseline exactly: True** (the correctness check every other candidate's delta depends on).

## Comparison table

| Candidate | Hazard P | Hazard R | Hazard F1 | Hazard mAP50 | Person P | Person R | Person F1 | Person AP50 | Preproc p95 (ms) | Inference p95 (ms) | Total p95 (ms) | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| identity | 0.8070 | 0.4804 | 0.6023 | 0.5823 | 0.6667 | 0.2112 | 0.3208 | 0.1743 | 0.175 | 57.40 | 57.56 | INCONCLUSIVE |
| clahe | 0.8048 | 0.4791 | 0.6007 | 0.5731 | 0.6778 | 0.2013 | 0.3104 | 0.1668 | 14.052 | 20.21 | 32.86 | INCONCLUSIVE |
| unsharp | 0.8066 | 0.4791 | 0.6011 | 0.5711 | 0.6915 | 0.2145 | 0.3275 | 0.1783 | 2.604 | 17.19 | 19.71 | INCONCLUSIVE |
| gamma (representative) | 0.7949 | 0.4856 | 0.6029 | 0.5780 | 0.6604 | 0.2310 | 0.3423 | 0.1866 | 1.754 | 17.81 | 19.19 | INCONCLUSIVE |
| autocontrast | 0.8018 | 0.4752 | 0.5967 | 0.5807 | 0.6522 | 0.1980 | 0.3038 | 0.1632 | 25.729 | 19.00 | 41.87 | INCONCLUSIVE |

**Overall representative candidate**: `gamma` (final status = INCONCLUSIVE).

## Per-candidate failure-bucket transitions (of the 239 baseline Person FNs)

### clahe

| Baseline bucket | n | -> TP | new-bucket breakdown |
|---|---|---|---|
| TRUE_DETECTOR_MISS | 92 | 0 | {'TRUE_DETECTOR_MISS': 89, 'LOW_CONFIDENCE_PERSON': 2, 'LOCALIZATION_FAILURE': 1} |
| LOW_CONFIDENCE_PERSON | 82 | 2 | {'LOW_CONFIDENCE_PERSON': 71, 'TRUE_DETECTOR_MISS': 2, 'TP': 2, 'LOCALIZATION_FAILURE': 6, 'SEMANTIC_CLASS_CONFUSION': 1} |
| SEMANTIC_CLASS_CONFUSION | 13 | 0 | {'SEMANTIC_CLASS_CONFUSION': 13} |
| LOCALIZATION_FAILURE | 52 | 0 | {'LOCALIZATION_FAILURE': 49, 'TRUE_DETECTOR_MISS': 1, 'LOW_CONFIDENCE_PERSON': 1, 'SEMANTIC_CLASS_CONFUSION': 1} |

Baseline Person TP regressions: 5/64 regressed (59 remained TP).

TRUE_DETECTOR_MISS (92 baseline) recovery: gained_any_person_candidate=55, gained_tp=0, gained_other_human_class=20, remains_complete_miss=17.

### unsharp

| Baseline bucket | n | -> TP | new-bucket breakdown |
|---|---|---|---|
| TRUE_DETECTOR_MISS | 92 | 0 | {'TRUE_DETECTOR_MISS': 89, 'LOW_CONFIDENCE_PERSON': 3} |
| LOW_CONFIDENCE_PERSON | 82 | 2 | {'LOW_CONFIDENCE_PERSON': 76, 'TP': 2, 'LOCALIZATION_FAILURE': 3, 'SEMANTIC_CLASS_CONFUSION': 1} |
| SEMANTIC_CLASS_CONFUSION | 13 | 0 | {'SEMANTIC_CLASS_CONFUSION': 12, 'LOCALIZATION_FAILURE': 1} |
| LOCALIZATION_FAILURE | 52 | 0 | {'LOCALIZATION_FAILURE': 51, 'LOW_CONFIDENCE_PERSON': 1} |

Baseline Person TP regressions: 1/64 regressed (63 remained TP).

TRUE_DETECTOR_MISS (92 baseline) recovery: gained_any_person_candidate=62, gained_tp=0, gained_other_human_class=15, remains_complete_miss=15.

### gamma

| Baseline bucket | n | -> TP | new-bucket breakdown |
|---|---|---|---|
| TRUE_DETECTOR_MISS | 92 | 0 | {'TRUE_DETECTOR_MISS': 92} |
| LOW_CONFIDENCE_PERSON | 82 | 5 | {'LOW_CONFIDENCE_PERSON': 77, 'TP': 5} |
| SEMANTIC_CLASS_CONFUSION | 13 | 1 | {'SEMANTIC_CLASS_CONFUSION': 8, 'LOCALIZATION_FAILURE': 4, 'TP': 1} |
| LOCALIZATION_FAILURE | 52 | 0 | {'LOCALIZATION_FAILURE': 51, 'LOW_CONFIDENCE_PERSON': 1} |

Baseline Person TP regressions: 0/64 regressed (64 remained TP).

TRUE_DETECTOR_MISS (92 baseline) recovery: gained_any_person_candidate=62, gained_tp=0, gained_other_human_class=17, remains_complete_miss=13.

### autocontrast

| Baseline bucket | n | -> TP | new-bucket breakdown |
|---|---|---|---|
| TRUE_DETECTOR_MISS | 92 | 0 | {'TRUE_DETECTOR_MISS': 89, 'LOW_CONFIDENCE_PERSON': 2, 'LOCALIZATION_FAILURE': 1} |
| LOW_CONFIDENCE_PERSON | 82 | 1 | {'LOW_CONFIDENCE_PERSON': 76, 'TRUE_DETECTOR_MISS': 1, 'LOCALIZATION_FAILURE': 3, 'TP': 1, 'SEMANTIC_CLASS_CONFUSION': 1} |
| SEMANTIC_CLASS_CONFUSION | 13 | 0 | {'SEMANTIC_CLASS_CONFUSION': 13} |
| LOCALIZATION_FAILURE | 52 | 0 | {'LOCALIZATION_FAILURE': 48, 'LOW_CONFIDENCE_PERSON': 1, 'TRUE_DETECTOR_MISS': 3} |

Baseline Person TP regressions: 5/64 regressed (59 remained TP).

TRUE_DETECTOR_MISS (92 baseline) recovery: gained_any_person_candidate=57, gained_tp=0, gained_other_human_class=15, remains_complete_miss=20.

## Notes

See `benchmark/results/diagnostics/preprocessing_analysis.json` for the complete per-candidate, per-record data (confidence-distribution shifts, IoU shifts, size-based split, raw per-image latency) this report summarizes.