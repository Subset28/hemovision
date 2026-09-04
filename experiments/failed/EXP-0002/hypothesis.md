# EXP-0002 — Hypothesis

**Family**: small_object
**Validation requirement**: OFFLINE_SIMULATABLE
**Parent experiment**: (none)

## Hypothesis

Increased inference-time input resolution (640->960 or 640->1280) meaningfully improves Person recall, at some measurable latency cost.

## Motivation

64.0% of missed Person boxes have area <2% of the image (small/distant) per reports/baseline/person_failure_analysis.md. Higher input resolution is a natural, architecture-preserving lever for small-object recall.

## Rationale

YOLO models natively support inference at a different imgsz via letterboxing, with no retraining and no change to the production model weights.

## Expected outcome

Directional evidence on whether resolution is a viable lever for Person recall.

## Risks

Runtime cost of a second full inference pass (~380 images); no production code touched.
