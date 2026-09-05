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

(not applicable while BLOCKED)

## Risks

Highest risk/cost family: requires acquiring/exporting a new model, and real CoreML/ANE deployment behavior cannot be validated without a Mac (see research/experiment_registry.py's production_validation_requirement=REQUIRES_MAC).
