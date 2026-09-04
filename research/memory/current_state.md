# Current State

> Read `research/memory/README.md` first — this file and its four siblings
> are mandatory reading before proposing any new experiment.

Last updated: 2026-09-04 (Phase C seed, from Phase B/B.5 findings).

## Canonical baseline

- Run: `RUN-20260904-002` (`benchmark/results/baseline/`). Model
  `yolov8m-oiv7.pt`, imgsz=640, conf=0.4, iou=0.7 — this is the shipped
  production operating point and must never be changed by experiment code.
- Hazard classes (person, car, truck, bus, bicycle, motorcycle, stairs, dog):
  Precision=0.807, Recall=0.480, F1=0.602, mAP50=0.582.
- Person (GT=303, the largest and most trustworthy sample): Recall=0.211,
  Precision=0.667. Worst hazard-class recall in the dataset.
- Latency (Windows/CUDA proxy only): p50=18.0ms, p95=57.1ms, p99=65.8ms.

## Active / queued work

- EXP-0001 (threshold_postprocessing, confirmatory) — QUEUED, about to run.
- EXP-0002 (small_object, resolution sweep) — QUEUED.
- EXP-0003 (class_confusion, semantic remap analysis) — QUEUED, awaiting
  approval to run.
- EXP-0004 (preprocessing, single transform) — QUEUED, awaiting approval to
  run.
- EXP-0005 (model_variant, YOLO26n) — BLOCKED, per spec: only unblock if
  0002/0003/0004 indicate model capacity/architecture is the limiting factor.

## What this phase deliberately has NOT built yet

- `omnilab run` (continuous autonomous queue processing) — Phase C is
  one-at-a-time, manually triggered only.
- Any live LLM call (no OPENROUTER_API_KEY in this environment).
- Literature-grounded hypothesis generation (see `open_questions.md`).
- Device-validated (Mac/iPhone) execution of anything.
