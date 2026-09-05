# EXP-0004 — Hypothesis

**Family**: preprocessing
**Validation requirement**: OFFLINE_SIMULATABLE
**Parent experiment**: (none)

## Hypothesis

A single, simple image preprocessing transform (contrast/sharpening/CLAHE) applied before inference improves difficult Person detection without unacceptable latency cost.

## Motivation

Occlusion/small-object/clutter dominate Person misses; a contrast/sharpening transform is a plausible, cheap lever worth testing in isolation before considering any model-level change.

## Rationale

Exactly ONE transform is applied (not a stack), per the master spec's explicit instruction not to change multiple uncontrolled variables at once.

## Expected outcome

Directional, evidence-based answer to whether any of the 5 pre-registered candidates clears the existing hazard-precision guardrail while producing a real (non-noise) Person recall improvement, with a full failure-bucket-transition breakdown per candidate. A result of 'no candidate works' (overall FAILED) is an explicitly anticipated, acceptable outcome, not a defect in the experiment design.

## Risks

Runtime cost of TWO additional full inference passes per candidate (conf=0.4 and conf=0.01) x 5 candidates = 10 inference passes over 380 images, on top of the already-captured baseline; preprocessing itself (CLAHE/unsharp/gamma/autocontrast) adds a small, separately-measured per-image overhead. No production code touched. Risk that a transform improves recall but degrades hazard precision or introduces IoU regressions on already-correct baseline Person TPs -- explicitly checked (see evaluation_method's regression-check description) rather than assumed away.
