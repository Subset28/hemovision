# OmniSight Architecture (Phase A Audit)

Read-only audit. No production code modified. Findings from static inspection of `C:\Users\Armaa\Downloads\OmniSight` on 2026-09-04.

## 1. Project Structure

- Swift/SwiftUI iOS app, two modules:
  - `ios/OmniSightApp` — Xcode app target, bundle id `com.orbconcepts.omnisight`.
  - `ios/OmniSightKit` — local SPM package, no external deps.
- **Deployment target mismatch**: README says "iOS 16+", `Package.swift` says `.iOS(.v16)`, but Xcode project (`project.pbxproj:300,343`) is pinned to `IPHONEOS_DEPLOYMENT_TARGET = 17.6`. Flag for resolution — affects device-support scope.
- `SWIFT_VERSION = 5.0`. Xcode project references OmniSightKit via `XCLocalSwiftPackageReference`.
- **No test target exists.** Zero XCTest anywhere in the repo.
- Award-winning, shipped product — 2nd Place TSA Software Development 2025, live on App Store (v1.1 submitted 2026-06-22 per `docs/superpowers/HANDOFF.md`). Treat as production, preserve clean baseline.

## 2. Computer Vision Pipeline

**Fully on-device. No server-side inference, no network calls in the CV path** (confirmed: no `URLSession` usage anywhere in the detection/tracking/speech code).

| Stage | Implementation |
|---|---|
| Capture | **ARKit** (`ARWorldTrackingConfiguration`), not raw AVFoundation — chosen deliberately to avoid AVCaptureSession/ARSession conflicts (`OmniPipeline.swift:12`) |
| Frame rate | ARKit format capped 30fps, ≤1920px width (avoids SIGKILL w/ sceneDepth on Pro Max, `OmniPipeline.swift:50-58`). ML ingest throttled ~15fps (`now - lastIngestTime >= 0.067`, line 95). LiDAR depth on main thread at 10fps (line 77). Crosswalk OCR throttled 1fps. |
| Preprocessing | None explicit in Swift — raw `CVPixelBuffer` fed to `VNImageRequestHandler`; `VNCoreMLRequest.imageCropAndScaleOption = .scaleFill` (`CoreMLDetector.swift:66`). Resize/normalize baked into the Core ML graph itself. |
| Inference | Vision framework + Core ML, `computeUnits = .all` (ANE+GPU+CPU), `CoreMLDetector.swift:47-51`. |
| Postprocessing | Confidence filter at `config.confidenceThreshold` (app default **0.4**, `OpticalCore.swift:137` — overrides model's embedded default of 0.25). **NMS is baked into the Core ML model graph** (`nms: True` export flag) — no NMS code in Swift. Distance via focal-length geometry for 18 known classes (`CoreMLDetector.swift:23-43`), else area-heuristic fallback; LiDAR depth overrides when available (`OpticalProcessor.swift:104-109`). |
| Tracking | Hand-rolled SORT-inspired tracker (`ObjectTracker.swift`, ~260 lines) — IoU matching (threshold 0.10) + center-distance fallback (0.22), state machine TENTATIVE → CONFIRMED (3 matches) → COASTING (≤3 missed frames, velocity-extrapolated) → pruned. Not Vision's built-in tracker. |
| Prioritization | Hazard-class set `{person, car, truck, bus, bicycle, motorcycle, stairs, dog}` (`OpticalCore.swift:108-110`) → HIGH priority when distance ≤1.2m, or hazard+≤3m, or closing fast (<-0.5 m/s & <4m) (`OpticalProcessor.swift:112-117`). |

### LiDAR (Pro devices only, gated via `supportsFrameSemantics(.sceneDepth)`)
- Per-detection depth override.
- Center-point obstacle channel independent of CV detection.
- `StepHazardDetector.swift` — 10×5 grid depth-discontinuity analysis on bottom 40% of frame, 0.15m threshold, distinguishes step-up/down vs stairs.

### Crosswalk detection
- `CrosswalkDetector.swift` — on-device OCR (`VNRecognizeTextRequest`, `.fast`) for WALK/DON'T WALK signage, 2-frame confirmation + 5-frame unknown-reset hysteresis.

## 3. Model

- File: `ios/OmniSightApp/ScanningData.mlpackage` — `model.mlmodel` (170KB spec) + `weights/weight.bin` (**50MB**, fp16).
- **Actual shipped model: Ultralytics YOLOv8m**, trained on **Open Images V7** (601 classes). Confirmed directly from embedded model metadata: `"Ultralytics YOLOv8m model trained on .../open-images-v7.yaml"`, `torch==2.11.0`, converted 2026-04-25.
- Input: 640×640, fp16 cast in-graph. Export args embedded: `{'batch': 1, 'half': False, 'int8': False, 'dynamic': False, 'nms': True}`. Default `confidenceThreshold: 0.25`, `iouThreshold: 0.7` (app overrides confidence to 0.4).
- Output: `VNRecognizedObjectObservation` — labels resolved via the model's own embedded `classLabels` metadata. `OpenImagesV7Mapping.swift` is **dead code** (empty enum, explicit "not used" comment) — do not treat as the label source.
- No quantization beyond standard fp16 export. No int8/pruning.

### ⚠️ Model-swap discrepancy (important)
The latest commit (`76c5508 "feat: OmniSight v1.2 — StepHazardDetector + YOLO26n prep"`) and `docs/superpowers/HANDOFF.md` describe a plan to swap to **YOLO26n** for ~2x Neural Engine speedup. That swap requires a manual step (`pip install ultralytics; export yolo26n.pt → coreml → replace ScanningData.mlpackage`) that was **never executed** — direct binary inspection confirms the shipped model is still YOLOv8m/Open-Images-V7/601-class. Only the StepHazardDetector Swift code, wiring, and settings toggle landed. **Do not assume YOLO26n is present anywhere in this repo.**

## 4. TTS / Accessibility (SpeechEngine.swift, ~700 lines — richest subsystem)

- Priority-queued announcements, 10Hz drain timer.
- Per-object (5s) and per-class (5–15s, doubled in Low Noise mode) cooldowns.
- Emergency bypass (priority 99, <3s recollision cooldown) — hazard/step announcements bypass the normal queue entirely.
- 3 modes: navigation / finding / hazardPriority.
- Crowd-density suppression (≥3 people → suppress individual "person" announcements, 5s exit hysteresis).
- Travel-mode auto-detection (30-sample rolling window of high-speed objects).
- 7-zone directional language, metric/imperial formatting.
- `SceneContextEngine` — natural-language scene summaries, 6s cooldown, signature-hash change detection.
- All decisions logged via `DecisionLog` (audit trail), counted by `PerformanceMonitor`.

## 5. Existing Benchmarks/Tests

- **No XCTest targets, no unit tests, no UI tests anywhere.**
- `BenchmarkSession.swift` + `PerformanceMonitor.swift` = an in-app, on-device, 30-second timed UX/perf session — **not an accuracy benchmark**. Reports frame latency p50/p95, tracker create/promote/prune/reidentify counts, TTS emitted/suppressed ratios, scene update counts. **No ground truth, no mAP/precision/recall measurement anywhere.** Output is a console/debug-UI JSON blob, not persisted to the repo.
- No profiling scripts, no accuracy logs, no dataset directory in the repo.

## 6. Dataset/Training

**None found in-repo.** Model trained externally on Open Images V7 (public, CC-BY 4.0, 601-class taxonomy) — not bundled, not OmniSight's own data. No local dataset, no training scripts, no labeled validation/test imagery.

## 7. Build/Deploy Tooling

- `ios/fastlane/Fastfile` — full App Store Connect pipeline (build/beta/submit/release/bump_build) via `gym`/`pilot`/`deliver`, ASC API key via env vars. **No test lane** (consistent with no test target).
- `.github/workflows/generate_code_pdf.yml` — only CI workflow present; generates a code PDF, not a build/test pipeline.
- Xcode project has shared schemes (`xcshareddata/xcschemes`) — `xcodebuild` should work assuming valid signing, but **this cannot be verified from Windows**; requires the Mac mini.

## 8. What Requires Windows vs. macOS/iPhone

| Task | Machine |
|---|---|
| Core ML model inference benchmarking (accuracy, latency, mAP) on the `.mlpackage`/exported model | **Windows** (RTX 3070 Ti) — run YOLOv8m via PyTorch/ONNX/coremltools outside the app; requires re-deriving the eval pipeline since none exists |
| Static code analysis, preprocessing/postprocessing logic review | Windows |
| Actual on-device inference latency, FPS, thermal, battery, ARKit/LiDAR behavior, TTS latency | **Mac mini + physical iPhone** (LiDAR needs a Pro device) — cannot be simulated |
| `xcodebuild`/simulator build verification | **Mac mini** (Xcode required) |
| Device-level benchmark automation (`devicectl`) | **Mac mini + iPhone**, feasibility unconfirmed until tooling is tried |

## 9. Notable Findings

1. Git log commit message overstates repo state ("YOLO26n prep" reads as done; it isn't).
2. iOS deployment-target mismatch (README/Package.swift say 16+, Xcode project says 17.6).
3. `OpenImagesV7Mapping.swift` is dead code.
4. `notes.txt` flags open issues: haptics feel "too strong" on real phone (untested), LiDAR range question outstanding, "chair" over-announced (partially addressed by cooldowns/threshold, still flagged open).
5. `docs/system_overview.md` is an accurate, pre-existing architecture doc (latency budget table, known failure modes: seated-person distance overestimation, glass/mirror LiDAR issues, dense-crowd ID churn) — should heavily inform `BENCHMARK_PLAN.md`'s robustness categories.
6. Confidence threshold override (0.25 model default → 0.4 app) is a deliberate tuning decision, not an oversight.
7. `GoogleService-Info.plist` present — contains project keys, not opened (sensitive, flagged only).

## 10. Open Questions (cannot resolve via static inspection)

1. Does `xcodebuild`/simulator build currently succeed? (needs Mac/Xcode)
2. Is physical-device automation (`devicectl`) feasible for this setup? (needs Mac mini + iPhone)
3. Actual precision/recall/mAP of the shipped YOLOv8m-OpenImagesV7 model on OmniSight's real use cases — no eval harness exists; must be built from scratch (Phase 1/2).
4. Is `GoogleService-Info.plist` wired to an active Firebase integration, or vestigial?
5. Full contents of `AppMode.swift`, `ContentView.swift`, `SettingsView.swift`, `SceneContextEngine.swift`, `DecisionLog.swift`, `HapticManager.swift` — inferred from cross-references, not line-by-line verified.
6. Fastlane `metadata`/`screenshots`/`report.xml` — App Store Connect metadata, out of scope here.
