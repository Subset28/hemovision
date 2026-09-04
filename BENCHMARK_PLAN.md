# OmniSight Benchmark Plan (Phase A Deliverable)

Derived from `OMNISIGHT_ARCHITECTURE.md`. This is a **plan**, not an implementation — Phase B builds it, pending approval. No code touched.

Guiding rule from the master spec: only implement metrics meaningful to OmniSight's actual architecture (Vision+CoreML on-device YOLOv8m detector, hand-rolled tracker, LiDAR-augmented distance, TTS prioritization). Do not invent metrics for polish.

## 1. Windows Benchmark (model/computational behavior)

Runs YOLOv8m (the exact model baked into `ScanningData.mlpackage`, Open Images V7, 640x640, conf 0.4/iou 0.7) outside the app, via PyTorch/ONNX or `coremltools` on the RTX 3070 Ti.

**Note**: since no evaluation dataset exists in-repo, this requires sourcing or constructing a labeled test set consistent with Absolute Rule #6 (privacy) — public/synthetic images matching OmniSight's real conditions (indoor/outdoor navigation scenes), not real user photos.

### Detection metrics
- Precision, Recall, F1 (at the app's actual operating point: conf=0.4, iou=0.7)
- mAP@50, mAP@50:95 — standard, comparable across model swaps (relevant given the pending YOLOv8m→YOLO26n decision)

### Error metrics
- False positives / false negatives (per class, per category — see robustness breakdown)
- Duplicate detections (pre-NMS-baked-in sanity check; NMS itself is not tunable from the app, so this measures whether the graph's baked NMS is behaving as expected)
- Missed objects (recall failures on hazard classes specifically — `{person, car, truck, bus, bicycle, motorcycle, stairs, dog}` per `OpticalCore.swift:108-110`, since these drive HIGH-priority TTS)

### Performance metrics
- Median / P95 inference latency
- Throughput (FPS at 640x640, batch=1 — matches app's actual usage, not batched)
- GPU utilization, VRAM, CPU, RAM — measured on Windows as a proxy for compute cost, **not** a substitute for on-device figures (ANE behavior differs from GPU/CPU and must come from Phase 2)

### Robustness breakdown
Categories chosen from `docs/system_overview.md`'s existing known-failure-mode table (not invented) plus the architecture audit:
- Indoor vs. outdoor
- Lighting (well-lit / low-light / glare — LiDAR+camera failure mode noted in `system_overview.md`)
- Object size (small/medium/large, since focal-length distance heuristic is only calibrated for 18 known classes)
- Distance bands (matches HIGH-priority thresholds: ≤1.2m, ≤3m, ≤4m closing-fast, >4m)
- Clutter/density (dense-crowd tracker ID churn is a documented known failure mode)
- Hazard vs. non-hazard class (since these get different TTS treatment downstream)
- Glass/mirror surfaces (documented LiDAR failure mode)
- Seated-person cases (documented distance-overestimation failure mode)

Do not add motion-blur/occlusion categories unless the sourced test data actually has natural examples of these — avoid synthetic categories the model was never meaningfully exposed to in practice.

### Output
```
python -m benchmark.run
```
- Machine-readable: `benchmark/results/BASELINE.json`
- Human-readable: console summary table + `benchmark/results/BASELINE.md`

## 2. Device Benchmark (user-facing behavior — requires Mac mini + iPhone)

The Windows benchmark measures the model in isolation. This measures the **actual pipeline**: ARKit capture → Vision/CoreML inference → tracker → LiDAR fusion → SpeechEngine — end to end, on-device.

### Metrics
- End-to-end latency: frame capture → TTS-ready announcement (the number that matters to a blind user, not raw model inference)
- Inference latency specifically (ANE via `computeUnits = .all` — cannot be replicated on Windows; the RTX benchmark is a directional proxy only)
- Sustained FPS during the 15fps-throttled ingest loop (`OmniPipeline.swift:95`) — confirm throttle is actually achieved, not aspirational
- Memory (peak, sustained) — repo has no LiDAR-memory profiling; relevant given `OmniPipeline.swift:50-58`'s existing SIGKILL-avoidance workaround for Pro Max + sceneDepth
- Thermal state (`ProcessInfo.thermalState`) over a sustained session — LiDAR+ARKit+CoreML concurrently is thermally heavy; no existing data on this
- Battery drain per unit time
- TTS latency (queue-to-speech, already partially logged via `DecisionLog`/`PerformanceMonitor` — this benchmark should read and aggregate what's already emitted, not reinvent it)
- Camera-processing latency (ARKit frame → CVPixelBuffer ready)

### Tooling
- Use existing `BenchmarkSession.swift`/`PerformanceMonitor.swift` in-app session as the **data source** — it already reports frame latency p50/p95, tracker event counts, TTS emitted/suppressed ratios. Currently console/debug-UI only and not persisted; extend it to write JSON to a file `xcodebuild`/`devicectl` can pull off-device, rather than building a parallel measurement system.
- Attempt `xcodebuild test`/`xcodebuild build` for CI-style verification once a test target exists (none currently does — Phase 25 territory, not Phase 1/2).
- Attempt `simctl` for simulator-only checks (note: LiDAR/ARKit sceneDepth cannot be simulated — simulator benchmark is necessarily partial, camera/LiDAR-dependent metrics require the physical iPhone).
- `devicectl` for physical-device automation — feasibility unconfirmed (Open Question #2 in the architecture doc); first Phase-2 task is to establish whether this actually works for this hardware/signing setup before building automation around it.

### What must stay manual (until proven otherwise)
- Physical device placement/movement for varied test scenes (a person can't be scripted to walk into frame)
- Thermal/battery long-run sessions likely need to be manually initiated and left running

## 3. What This Plan Deliberately Excludes (for now)

- No training/fine-tuning benchmarks — no training data exists yet, and Phase 0/1 explicitly forbid assuming this is needed.
- No mAP comparison against YOLO26n yet — that model doesn't exist in the repo (see architecture doc §3 discrepancy). Once/if the swap actually happens, this benchmark becomes the direct before/after comparison tool.
- No synthetic-category robustness metrics not grounded in `system_overview.md`'s documented failure modes or this audit's findings.

## 4. Approval Gate

Per master spec, Phase B (implementing this benchmark) does not start until explicitly approved.
