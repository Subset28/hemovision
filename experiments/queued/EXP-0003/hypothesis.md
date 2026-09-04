# EXP-0003 — Hypothesis

**Family**: class_confusion
**Validation requirement**: OFFLINE_SIMULATABLE
**Parent experiment**: (none)

## Hypothesis

A meaningful fraction of Person recall loss is attributable to predictions falling into semantically related classes (Man/Human body/Clothing/Woman) rather than true missed detections.

## Motivation

35.1% of missed Person boxes had a DIFFERENT class predicted at the same location (IoU>=0.3) per reports/baseline/person_failure_analysis.md — this is a labeling choice, not a confidence problem, and is NOT fixable by lowering the threshold.

## Rationale

Recomputing recall with a measurement-time class-grouping remap ({Person, Man, Woman} scored as one super-class) quantifies how much 'true' person-detection capability is understated by strict single-label scoring, without changing any production label output.

## Expected outcome

Quantifies the 'understated capability' gap; does not itself justify a production change.

## Risks

None — measurement-only, does not change any production label or threshold.
