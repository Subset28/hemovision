# OmniSight v1.2: YOLO26 Migration + Step Hazard Detection

**Date:** 2026-06-24  
**Status:** Approved

---

## Overview

Two independent sub-systems shipped together:

1. **YOLO26 model swap** — replace YOLOv8 `ScanningData` model with YOLO26n for ~2× Neural Engine inference speed and improved small-object accuracy (traffic lights, curbs, fire hydrants).
2. **`StepHazardDetector`** — new on-device depth analyzer that announces stairs, curbs, and drops to blind users before they reach them. Uses LiDAR on Pro models, `VNGenerateDepthImageRequest` on all others. 100% offline.

Target users: blind and visually impaired people navigating indoors and outdoors daily.

---

## Licensing Note

YOLO26 (Ultralytics) is AGPL-3.0. Distributing in a closed App Store app requires either an Ultralytics Enterprise license or treating the exported CoreML weights as a separate artifact. The current app already ships YOLOv8 under the same terms — this migration does not change the existing licensing posture.

---

## Sub-system 1: YOLO26 Migration

### What changes

| File | Change |
|------|--------|
| `ScanningData.mlpackage` (bundle) | Replace with YOLO26n export |
| `CoreMLDetector.swift` | Add `"traffic light": 0.90` to `knownHeights` |
| `AppStateManager.swift` | No change (same resource name `ScanningData`) |
| `OpticalCore.swift` | Validate class name strings match YOLO26 COCO labels |

### Model export (one-time, outside Xcode)

```bash
pip install ultralytics
yolo export model=yolo26n.pt format=coreml nms=True imgsz=640
# Rename output → ScanningData.mlpackage
# Replace in Xcode bundle
```

`nms=True` preserves the `VNRecognizedObjectObservation` output format that `CoreMLDetector.buildObservations` expects. Without it, YOLO26's NMS-free head produces raw tensor output incompatible with Vision's observation parsing.

### Risk: class name mismatch

YOLO26 COCO class names may differ subtly from the current model (e.g. `"traffic_light"` vs `"traffic light"`). After swap, verify:
- All strings in `hazardClasses` (OpticalCore.swift)
- All strings in `allWhitelistedClasses` (SpeechEngine.swift)
- All strings in `knownHeights` (CoreMLDetector.swift)

If any mismatch: fix the string table, not the detector logic.

### Expected outcome

- ~2× faster inference on Apple Neural Engine (A15+)
- Better detection of small objects (traffic lights, curbs, signage)
- Zero behavior change to downstream tracker, speech, or UI

---

## Sub-system 2: StepHazardDetector

### Detection algorithm

Sample a 10×5 grid across the **bottom 40% of the depth frame** (where floor, curbs, and stairs appear in portrait orientation). Compute column-wise depth gradient between adjacent rows.

**LiDAR path (Pro models):** Absolute depth in meters from `ARFrame.sceneDepth.depthMap`.
- Single discontinuity >0.25m over <0.5m horizontal → step/curb
- 3+ parallel discontinuities spaced 0.15–0.35m apart → stairs
- Depth increases away from camera → step **down**; decreases → step **up**

**Non-Pro path:** `VNGenerateDepthImageRequest` (Vision, iOS 17+, on-device Neural Engine, ~30ms).
- Produces relative depth 0–1 normalized
- Same grid analysis; thresholds use normalized ratios (0.12 relative change)
- Capped at 4 fps to control battery draw

### Output

```swift
enum StepHazard {
    case clear
    case stepDown(distanceM: Float?)
    case stepUp(distanceM: Float?)
    case stairsDescending(distanceM: Float?)
    case stairsAscending(distanceM: Float?)
}
```

### Speech + haptics

| State | Announcement | Haptic |
|-------|-------------|--------|
| `.stepDown` | "Step down ahead" | warning |
| `.stepUp` | "Curb or step up" | medium |
| `.stairsDescending` | "Stairs descending ahead" | warning |
| `.stairsAscending` | "Stairs ascending ahead" | medium |

- 3s cooldown between announcements (same pattern as `CrosswalkDetector`)
- HIGH priority speech — bypasses normal queue via `speakImmediate`
- Respects `hapticsEnabled` setting (self-guards like existing haptic methods)
- Respects new `stepDetectionEnabled` settings toggle

### New file

`StepHazardDetector.swift` — standalone class on a serial `DispatchQueue` (thread-safe, same pattern as `CrosswalkDetector`).

```swift
final class StepHazardDetector {
    var onHazardChange: ((StepHazard) -> Void)?
    func process(depthMap: CVPixelBuffer?, pixelBuffer: CVPixelBuffer, timestamp: TimeInterval)
}
```

- `depthMap` non-nil → LiDAR path
- `depthMap` nil → Vision depth estimation path
- Throttles Vision requests internally; LiDAR analysis runs in microseconds

---

## Integration

### `OmniPipeline.swift`

Add alongside `crosswalkDetector`:
```swift
let stepHazardDetector = StepHazardDetector()
```

In `session(_:didUpdate:)`, after crosswalk dispatch:
```swift
stepHazardDetector.process(
    depthMap: OmniPipeline.isSupported ? frame.sceneDepth?.depthMap : nil,
    pixelBuffer: frame.capturedImage,
    timestamp: frame.timestamp
)
```

### `AppStateManager.swift`

Add `setupStepHazardSubscription()` called from `init`, mirroring `setupCrosswalkSubscription()`:
```swift
private func setupStepHazardSubscription() {
    cameraManager?.stepHazardDetector.onHazardChange = { [weak self] hazard in
        guard let self else { return }
        self.speechEngine.announceStepHazard(hazard)
    }
}
```

### `SpeechEngine.swift`

Add `announceStepHazard(_ hazard: StepHazard)`:
- Formats announcement string from enum case
- Calls `speakImmediate` with appropriate haptic level
- No-ops on `.clear`
- Checks `Settings.shared.stepDetectionEnabled`

### `SettingsView.swift`

One new toggle under the existing hazard settings section:
- Label: "Detect stairs & curbs"
- Key: `Settings.stepDetectionEnabled` (Bool, default `true`)

---

## Files Changed Summary

| File | Type | Description |
|------|------|-------------|
| `ScanningData.mlpackage` | Replace | YOLO26n CoreML export |
| `CoreMLDetector.swift` | Edit | Add traffic light to knownHeights |
| `StepHazardDetector.swift` | **New** | Depth gradient hazard detector |
| `OmniPipeline.swift` | Edit | Add stepHazardDetector, feed depth |
| `AppStateManager.swift` | Edit | Add setupStepHazardSubscription |
| `SpeechEngine.swift` | Edit | Add announceStepHazard |
| `SettingsView.swift` | Edit | Add stepDetectionEnabled toggle |
| `Settings` (struct) | Edit | Add stepDetectionEnabled field |

---

## Out of Scope (next specs)

- Traffic light detection (sub-system 3)
- Text/sign reading (sub-system 4)
- YOLO26 fine-tuning on stairs/curbs dataset
- Apple Watch haptic relay
