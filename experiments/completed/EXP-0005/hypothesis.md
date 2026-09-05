# EXP-0005 — Hypothesis

**Family**: model_variant
**Validation requirement**: REQUIRES_MAC
**Parent experiment**: (none)

## Hypothesis

A different model checkpoint/architecture (e.g. YOLO26n, referenced but never actually shipped per OMNISIGHT_ARCHITECTURE.md section 3) would improve Person and/or Stairs recall over the current yolov8m-oiv7 baseline.

## Motivation

Recent commit history references a YOLO26n swap plan that was never executed. This is the most expensive, highest-risk experiment family (model_variant) and must only be pursued once cheaper levers are exhausted.

## Rationale

Per the master spec's explicit ordering: only unblock this if EXP-0002 (resolution), EXP-0003 (class confusion), and EXP-0004 (preprocessing) indicate model capacity/architecture — not thresholding/measurement/preprocessing — is the limiting factor.

## Expected outcome

Directional, evidence-based answer to whether swapping the pretrained detector checkpoint/ architecture materially improves Person detection at a fair, precision-matched comparison, with a full failure-bucket-transition and small-Person breakdown per candidate, and an explicit accounting of whether any of the 4 candidates recovers TRUE_DETECTOR_MISS cases that EXP-0004's preprocessing intervention could not touch at all. A result of 'no candidate wins at matched precision' (overall FAILED) is an explicitly anticipated, acceptable outcome given EXP-0001-0004's accumulated evidence, not a defect in the experiment design. This experiment NEVER replaces the production model or touches ios/ regardless of outcome -- a winning candidate here is a candidate for FUTURE Mac/iPhone validation only.

## Risks

Runtime cost of 2 full inference passes (conf=0.4, conf=0.01) x 4 candidates = 8 passes over 380 images, on top of the already-captured official baseline. Each candidate requires downloading a checkpoint (benchmark/models/*.pt, gitignored, never committed) from an Ultralytics official release asset. CoreML export is attempted for 2 candidates but is known, per ultralytics' own explicit platform check, to be UNSUPPORTED on Windows regardless of coremltools being importable for spec-parsing -- this is expected to fail with an explicit, documented AssertionError, not a silent/ambiguous failure; real on-device CoreML/ANE behavior requires a Mac and is out of scope. Risk that the COCO candidate's fixed-threshold recall gain is a confidence-calibration artifact rather than a genuine improvement -- explicitly why the precision-matched/guardrail-matched sweeps are pre-registered as required, not left to post-hoc rationalization. Risk of baseline Person TP regressions under any candidate -- explicitly checked (baseline_tp_regressions) with the same rigor as gains, per EXP-0004's established convention.
