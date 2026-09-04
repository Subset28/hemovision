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

Directional evidence on whether preprocessing is a viable lever.

## Risks

Runtime cost of a second full inference pass; no production code touched.
