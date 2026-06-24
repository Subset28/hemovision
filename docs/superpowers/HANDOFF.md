# OmniSight Session Handoff — 2026-06-24

## Where We Are

v1.1 is live on the App Store (submitted 2026-06-22). v1.2 spec and implementation plan are written and committed. **Nothing has been implemented yet.** Next session picks up at plan execution.

## What Was Designed This Session

**v1.2 = two features:**

1. **YOLO26n model swap** — replaces YOLOv8 (`ScanningData.mlpackage`) for ~2× Neural Engine speed. NMS-free head, CoreML export with `nms=True` keeps `VNRecognizedObjectObservation` compatible.

2. **`StepHazardDetector`** — new class (pattern: CrosswalkDetector). Analyzes LiDAR depth map from ARKit, samples 10×5 grid in bottom 40% of frame, detects depth discontinuities >0.25m. Announces: "Step down ahead", "Curb or step up", "Stairs descending/ascending". LiDAR-only in v1.2 — non-Pro devices skip silently. Serial queue + 3s cooldown.

## Key Files

| File | Status |
|------|--------|
| `docs/superpowers/specs/2026-06-24-yolo26-step-hazard-design.md` | Written, committed (17694aa) |
| `docs/superpowers/plans/2026-06-24-yolo26-step-hazard.md` | Written, committed (17694aa) |

## Next Action: Execute the Plan

The plan has 5 tasks. **Task 1 requires a Python step the user runs first:**

```bash
pip install ultralytics
python3 -c "
from ultralytics import YOLO
model = YOLO('yolo26n.pt')
model.export(format='coreml', nms=True, imgsz=640)
"
mv yolo26n.mlpackage ios/OmniSight/ScanningData.mlpackage
```

Then Tasks 2–5 are pure Swift code changes.

**Execution choice not yet made.** Options:
- **Subagent-Driven** (recommended) — invoke `superpowers:subagent-driven-development`
- **Inline** — invoke `superpowers:executing-plans`

## Plan Tasks Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | YOLO26n export + bundle swap + knownHeights update | `ScanningData.mlpackage`, `CoreMLDetector.swift` |
| 2 | `StepHazardDetector` class with LiDAR depth gradient | `StepHazardDetector.swift` (new) |
| 3 | Wire `StepHazardDetector` into `OmniPipeline` ARKit loop | `OmniPipeline.swift` |
| 4 | `announceStepHazard` in SpeechEngine + AppStateManager subscription | `SpeechEngine.swift`, `AppStateManager.swift` |
| 5 | SettingsView toggle (shows "Requires iPhone Pro" on non-LiDAR) | `SettingsView.swift` |

## Architecture Reminder

```
OmniSightKit (Swift Package)
  CoreMLDetector.swift    — YOLO model, knownHeights, VNCoreMLRequest
  OpticalProcessor.swift  — frame orchestration, HIGH priority

OmniSightApp
  OmniPipeline.swift      — ARKit, crosswalkDetector, stepHazardDetector (Task 3)
  StepHazardDetector.swift — NEW (Task 2)
  AppStateManager.swift   — subscriptions wired here
  SpeechEngine.swift      — all TTS, haptics, announceStepHazard (Task 4)
  SettingsView.swift      — @AppStorage, stepDetectionEnabled toggle (Task 5)
```

## Critical Constraints

- `VNGenerateDepthImageRequest` does NOT exist — was a design error, corrected in spec. Non-Pro path deferred to v1.3 (needs a bundled CoreML depth model ~50MB, e.g. MiDaS).
- YOLO26 is AGPL-3.0. Same licensing posture as existing YOLOv8. User is aware.
- `announceStepHazard` must call `speakToUser` directly (not queue) — same pattern as `announceCrosswalk`.
- `SpeechEngine` is `@MainActor`. `StepHazardDetector.onHazardChange` dispatches to main thread before firing.
- Settings: no `Settings.shared` struct — all via `UserDefaults.standard` with string keys.

## After v1.2

Next planned features (separate specs needed):
1. Traffic light detection — v1.3
2. Text/sign reading — v1.4
3. Non-LiDAR step detection (MiDaS CoreML model) — v1.3
