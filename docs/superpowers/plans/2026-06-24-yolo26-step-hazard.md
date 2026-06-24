# OmniSight v1.2: YOLO26 + StepHazardDetector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace YOLOv8 with YOLO26n for 2× faster inference, and add `StepHazardDetector` that announces stairs/curbs/drops to blind users via LiDAR depth analysis.

**Architecture:** YOLO26n is a drop-in CoreML model swap — same `VNCoreMLRequest` / `VNRecognizedObjectObservation` interface. `StepHazardDetector` follows the `CrosswalkDetector` pattern: serial queue, throttled callback, `onHazardChange` delegate. LiDAR only in v1.2 (non-Pro returns immediately).

**Tech Stack:** Swift 5.9, ARKit, CoreML, Vision, AVSpeechSynthesizer, Ultralytics YOLO26 (export step only, Python)

## Global Constraints

- iOS deployment target: 17.6 (see Info.plist)
- Bundle ID: com.orbconcepts.omnisight
- No unit test targets exist — verification is build success + manual device test
- Settings are stored in UserDefaults via `@AppStorage` in SettingsView and read via `UserDefaults.standard` in SpeechEngine
- `OmniPipeline.isSupported` = `ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth)` — true on iPhone Pro only
- StepHazardDetector: LiDAR path only. Non-Pro devices pass `nil` depthMap → detector returns `.clear` immediately
- All new announcements bypass the TTS queue via `speakToUser` directly (same as `announceCrosswalk`)
- Haptics must check `hapticsEnabled` from UserDefaults before firing
- SpeechEngine is `@MainActor` — `announceStepHazard` must also be called on main thread

---

## Task 1: YOLO26n Model Export & Bundle Swap

**Files:**
- Replace: `ios/OmniSight/ScanningData.mlpackage` (or `.mlmodelc`) in Xcode bundle
- Modify: `ios/OmniSightKit/Sources/OmniSightKit/CoreMLDetector.swift`

**Interfaces:**
- Produces: `ScanningData` bundle resource name unchanged — `AppStateManager.swift:37` loads it as `CoreMLDetector(modelResourceName: "ScanningData", bundle: .main)` and requires no change

---

- [ ] **Step 1: Export YOLO26n to CoreML (run in terminal, not Xcode)**

```bash
pip install ultralytics
python3 -c "
from ultralytics import YOLO
model = YOLO('yolo26n.pt')
model.export(format='coreml', nms=True, imgsz=640)
"
```

Expected output: `yolo26n.mlpackage` in current directory.
`nms=True` is required — without it YOLO26's NMS-free head produces raw tensor output
incompatible with Vision's `VNRecognizedObjectObservation`.

- [ ] **Step 2: Rename and add to Xcode project**

```bash
mv yolo26n.mlpackage ScanningData.mlpackage
```

In Xcode: drag `ScanningData.mlpackage` into the `OmniSight` target, replacing the existing model. Check "Copy items if needed". Verify it appears under Build Phases → Copy Bundle Resources.

- [ ] **Step 3: Add `traffic light` to `knownHeights` in CoreMLDetector.swift**

File: `ios/OmniSightKit/Sources/OmniSightKit/CoreMLDetector.swift`

Find the `knownHeights` dictionary (around line 23) and add one entry:

```swift
private static let knownHeights: [String: Double] = [
    "person":        1.70,
    "bicycle":       1.10,
    "car":           1.50,
    "motorcycle":    1.20,
    "bus":           3.00,
    "truck":         2.80,
    "dog":           0.55,
    "cat":           0.35,
    "chair":         0.90,
    "dining table":  0.75,
    "table":         0.75,
    "door":          2.10,
    "stairs":        0.20,
    "fire hydrant":  0.60,
    "stop sign":     1.80,
    "backpack":      0.50,
    "suitcase":      0.65,
    "bottle":        0.28,
    "traffic light": 0.90,   // ← add this line
]
```

- [ ] **Step 4: Verify YOLO26 class names match existing string tables**

YOLO26 uses COCO 80-class names. Confirm these exact strings are present in both
`hazardClasses` (`OpticalCore.swift:108`) and `allWhitelistedClasses` (`SpeechEngine.swift:75`):

```
"person", "car", "truck", "bus", "bicycle", "motorcycle", "stairs", "dog",
"cat", "chair", "table", "door"
```

If YOLO26 uses underscores (e.g., `"traffic_light"`) instead of spaces (`"traffic light"`),
update the `knownHeights` key to match — not the detector logic.

- [ ] **Step 5: Build and run on device**

Build target: OmniSight → Any iOS Device. Expected: build succeeds, app launches, detections appear in camera view with bounding boxes. Speech should announce detected objects as before.

- [ ] **Step 6: Commit**

```bash
git add ios/OmniSight/ScanningData.mlpackage \
        ios/OmniSightKit/Sources/OmniSightKit/CoreMLDetector.swift
git commit -m "feat: migrate to YOLO26n CoreML model, add traffic light to knownHeights"
```

---

## Task 2: StepHazardDetector — Core Class + LiDAR Analysis

**Files:**
- Create: `ios/OmniSightApp/StepHazardDetector.swift`

**Interfaces:**
- Produces:
  - `StepHazardDetector` class (used by OmniPipeline in Task 3)
  - `StepHazardDetector.StepHazard` enum (used by SpeechEngine in Task 4)
  - `func process(depthMap: CVPixelBuffer?, timestamp: TimeInterval)` — call with LiDAR depth map; pass `nil` on non-Pro
  - `var onHazardChange: ((StepHazardDetector.StepHazard) -> Void)?` — fires on main thread, 3s cooldown

---

- [ ] **Step 1: Create `StepHazardDetector.swift` with enum and class skeleton**

File: `ios/OmniSightApp/StepHazardDetector.swift`

```swift
import CoreVideo
import Foundation

final class StepHazardDetector {

    enum StepHazard {
        case clear
        case stepDown(distanceM: Float?)
        case stepUp(distanceM: Float?)
        case stairsDescending(distanceM: Float?)
        case stairsAscending(distanceM: Float?)
    }

    var onHazardChange: ((StepHazard) -> Void)?

    private let queue = DispatchQueue(label: "com.orbconcepts.omnisight.stephazard", qos: .utility)
    private var lastHazardAt: Date = .distantPast

    func process(depthMap: CVPixelBuffer?, timestamp: TimeInterval) {
        guard let dm = depthMap else { return }
        queue.async { [weak self] in
            guard let self else { return }
            let enabled = (UserDefaults.standard.object(forKey: "stepDetectionEnabled") as? Bool) ?? true
            guard enabled else { return }
            guard Date().timeIntervalSince(self.lastHazardAt) >= 3.0 else { return }
            let hazard = self.analyzeDepth(dm)
            if case .clear = hazard { return }
            self.lastHazardAt = Date()
            DispatchQueue.main.async { [weak self] in self?.onHazardChange?(hazard) }
        }
    }

    // MARK: - Depth analysis (implemented in Step 2)
    private func analyzeDepth(_ depthMap: CVPixelBuffer) -> StepHazard { .clear }
}
```

- [ ] **Step 2: Build to verify skeleton compiles**

Build target: OmniSight. Expected: build succeeds (analyzeDepth is a stub returning `.clear`).

- [ ] **Step 3: Implement `analyzeDepth` — 10×5 grid gradient**

Replace the stub `analyzeDepth` with the full implementation:

```swift
// Samples a 10-column × 5-row grid across the bottom 40% of the LiDAR depth frame.
// Detects abrupt column-wise depth changes that indicate steps, curbs, or stairs.
// LiDAR depthMap format: kCVPixelFormatType_DepthFloat32, depth in meters per pixel.
// "Bottom 40%" = rows 60%–100% of frame height = ground closest to user's feet.
private func analyzeDepth(_ depthMap: CVPixelBuffer) -> StepHazard {
    CVPixelBufferLockBaseAddress(depthMap, .readOnly)
    defer { CVPixelBufferUnlockBaseAddress(depthMap, .readOnly) }

    let width  = CVPixelBufferGetWidth(depthMap)
    let height = CVPixelBufferGetHeight(depthMap)
    let bpr    = CVPixelBufferGetBytesPerRow(depthMap)
    guard let base = CVPixelBufferGetBaseAddress(depthMap), width > 0, height > 0 else { return .clear }

    let floats = base.assumingMemoryBound(to: Float32.self)
    let stride = bpr / MemoryLayout<Float32>.size

    let cols    = 10
    let rows    = 5
    let startY  = Int(Double(height) * 0.60)
    let rowStep = max(1, (height - startY) / rows)
    let colStep = max(1, width / cols)

    var grid = [[Float32]](repeating: [Float32](repeating: 0, count: cols), count: rows)
    for r in 0..<rows {
        for c in 0..<cols {
            let py = min(height - 1, startY + r * rowStep)
            let px = min(width  - 1, c * colStep)
            let v  = floats[py * stride + px]
            grid[r][c] = (v > 0 && v.isFinite && v < 20.0) ? v : 0
        }
    }

    struct Disc { let row: Int; let delta: Float32 }
    let threshold: Float32 = 0.25  // 25cm — minimum depth jump to register as step/curb
    var discs: [Disc] = []

    for c in 0..<cols {
        for r in 0..<(rows - 1) {
            let d0 = grid[r][c]
            let d1 = grid[r + 1][c]
            guard d0 > 0, d1 > 0 else { continue }
            let delta = d1 - d0
            if abs(delta) >= threshold { discs.append(Disc(row: r, delta: delta)) }
        }
    }

    guard !discs.isEmpty else { return .clear }

    let avgDelta  = discs.map(\.delta).reduce(0, +) / Float32(discs.count)
    let goingDown = avgDelta > 0  // depth increases going further = ground drops = step DOWN

    // Stairs: 3+ discontinuities with tread spacing 0.15–0.35m
    let stairLike = discs.filter { abs($0.delta) >= 0.15 && abs($0.delta) <= 0.35 }
    let isStairs  = stairLike.count >= 3

    let nearestRow = discs.map(\.row).min() ?? 0
    let distM: Float? = grid[nearestRow][cols / 2] > 0 ? grid[nearestRow][cols / 2] : nil

    switch (isStairs, goingDown) {
    case (true,  true):  return .stairsDescending(distanceM: distM)
    case (true,  false): return .stairsAscending(distanceM: distM)
    case (false, true):  return .stepDown(distanceM: distM)
    case (false, false): return .stepUp(distanceM: distM)
    }
}
```

- [ ] **Step 4: Build to verify full implementation compiles**

Expected: build succeeds with no warnings from `StepHazardDetector.swift`.

- [ ] **Step 5: Commit**

```bash
git add ios/OmniSightApp/StepHazardDetector.swift
git commit -m "feat: add StepHazardDetector with LiDAR depth gradient analysis"
```

---

## Task 3: OmniPipeline Integration

**Files:**
- Modify: `ios/OmniSightApp/OmniPipeline.swift`

**Interfaces:**
- Consumes: `StepHazardDetector` (Task 2) — `process(depthMap:timestamp:)`
- Produces: `OmniPipeline.stepHazardDetector` property (used by AppStateManager in Task 4)

---

- [ ] **Step 1: Add `stepHazardDetector` property alongside `crosswalkDetector`**

File: `ios/OmniSightApp/OmniPipeline.swift`

Find line 32:
```swift
let crosswalkDetector = CrosswalkDetector()
```
Add below it:
```swift
let stepHazardDetector = StepHazardDetector()
```

- [ ] **Step 2: Feed depth map to `stepHazardDetector` in `session(_:didUpdate:)`**

Find the crosswalk dispatch block (around line 84):
```swift
crosswalkDetector.process(pixelBuffer: frame.capturedImage, timestamp: frame.timestamp)
```
Add immediately after:
```swift
stepHazardDetector.process(
    depthMap: OmniPipeline.isSupported ? frame.sceneDepth?.depthMap : nil,
    timestamp: frame.timestamp
)
```

- [ ] **Step 3: Build**

Expected: build succeeds. `stepHazardDetector` created at same time as `crosswalkDetector`, fed every ARKit frame.

- [ ] **Step 4: Commit**

```bash
git add ios/OmniSightApp/OmniPipeline.swift
git commit -m "feat: wire StepHazardDetector into OmniPipeline ARKit frame loop"
```

---

## Task 4: SpeechEngine + AppStateManager Integration

**Files:**
- Modify: `ios/OmniSightApp/SpeechEngine.swift`
- Modify: `ios/OmniSightApp/AppStateManager.swift`

**Interfaces:**
- Consumes: `StepHazardDetector.StepHazard` enum (Task 2)
- Consumes: `OmniPipeline.stepHazardDetector` (Task 3)
- Produces: `SpeechEngine.announceStepHazard(_ hazard: StepHazardDetector.StepHazard)` — called on main thread by AppStateManager

---

- [ ] **Step 1: Add `announceStepHazard` to `SpeechEngine`**

File: `ios/OmniSightApp/SpeechEngine.swift`

Add after `announceCrosswalk` (around line 593), inside the `// MARK: - Public API` section:

```swift
// Step hazard alerts bypass the queue — same safety rationale as announceCrosswalk.
func announceStepHazard(_ hazard: StepHazardDetector.StepHazard) {
    let enabled = (UserDefaults.standard.object(forKey: "stepDetectionEnabled") as? Bool) ?? true
    guard enabled else { return }

    let text: String
    let useWarning: Bool

    switch hazard {
    case .clear:
        return
    case .stepDown(let dist):
        text = dist.map { "Step down, \(distText(Double($0)))" } ?? "Step down ahead"
        useWarning = true
    case .stepUp(let dist):
        text = dist.map { "Curb or step up, \(distText(Double($0)))" } ?? "Curb or step up"
        useWarning = false
    case .stairsDescending(let dist):
        text = dist.map { "Stairs descending, \(distText(Double($0)))" } ?? "Stairs descending ahead"
        useWarning = true
    case .stairsAscending(let dist):
        text = dist.map { "Stairs ascending, \(distText(Double($0)))" } ?? "Stairs ascending ahead"
        useWarning = false
    }

    synth.stopSpeaking(at: .immediate)
    queue.removeAll()
    isSpeaking = false
    speakToUser(text, rate: 0.50)

    let hapticsOn = (UserDefaults.standard.object(forKey: "hapticsEnabled") as? Bool) ?? true
    if hapticsOn {
        useWarning ? HapticManager.shared.warningVibration() : HapticManager.shared.mediumVibration()
    }
}
```

- [ ] **Step 2: Add `setupStepHazardSubscription()` to `AppStateManager`**

File: `ios/OmniSightApp/AppStateManager.swift`

Add after `setupCrosswalkSubscription()` (around line 56):

```swift
private func setupStepHazardSubscription() {
    cameraManager?.stepHazardDetector.onHazardChange = { [weak self] hazard in
        guard let self else { return }
        self.speechEngine.announceStepHazard(hazard)
    }
}
```

- [ ] **Step 3: Call `setupStepHazardSubscription()` from `init`**

File: `ios/OmniSightApp/AppStateManager.swift`

Find `setupCrosswalkSubscription()` call in `init` (around line 52):
```swift
speechEngine.start(scanning: session!)
setupDepthSubscription()
setupCrosswalkSubscription()
```
Add one line:
```swift
speechEngine.start(scanning: session!)
setupDepthSubscription()
setupCrosswalkSubscription()
setupStepHazardSubscription()
```

- [ ] **Step 4: Build**

Expected: build succeeds. On a Pro device, walking toward stairs should now trigger speech.

- [ ] **Step 5: Commit**

```bash
git add ios/OmniSightApp/SpeechEngine.swift \
        ios/OmniSightApp/AppStateManager.swift
git commit -m "feat: announce step/stair hazards via SpeechEngine, wire AppStateManager callback"
```

---

## Task 5: SettingsView Toggle

**Files:**
- Modify: `ios/OmniSightApp/SettingsView.swift`

**Interfaces:**
- Consumes: `OmniPipeline.isSupported` — determines whether to show toggle or "Requires iPhone Pro" row
- Produces: `stepDetectionEnabled` UserDefaults key (Bool, default `true`) — read by `announceStepHazard` (Task 4)

---

- [ ] **Step 1: Add `@AppStorage` property for `stepDetectionEnabled`**

File: `ios/OmniSightApp/SettingsView.swift`

Find the `// Awareness` block of `@AppStorage` properties (around line 17):
```swift
@AppStorage("hazardAlarmsEnabled") private var hazardAlarmsEnabled: Bool   = true
@AppStorage("hapticsEnabled")      private var hapticsEnabled:      Bool   = true
```
Add after `hapticsEnabled`:
```swift
@AppStorage("stepDetectionEnabled") private var stepDetectionEnabled: Bool = true
```

- [ ] **Step 2: Add toggle (or disabled row) to Awareness section**

Find the `// MARK: Awareness` section in the `Form`. Locate the existing `Toggle("Haptics", ...)` or `Toggle("Hazard Alarms", ...)` row and add after it:

```swift
if OmniPipeline.isSupported {
    Toggle("Detect stairs & curbs", isOn: $stepDetectionEnabled)
} else {
    HStack {
        Text("Detect stairs & curbs")
        Spacer()
        Text("Requires iPhone Pro (LiDAR)")
            .font(.caption)
            .foregroundStyle(.secondary)
    }
}
```

- [ ] **Step 3: Build**

Expected: build succeeds. On a Pro simulator/device, toggle appears and persists across app launches. On non-Pro, disabled label appears.

- [ ] **Step 4: Commit**

```bash
git add ios/OmniSightApp/SettingsView.swift
git commit -m "feat: add step detection toggle to settings (LiDAR-only, Pro devices)"
```

---

## Manual Test Checklist (run on iPhone Pro after all tasks)

- [ ] YOLO26: Objects detected and announced as before (person, car, bicycle, etc.)
- [ ] YOLO26: Check no class names silently dropped (open debug overlay, confirm objects appear)
- [ ] Step down: Point camera at stairs descending → "Stairs descending ahead" + warning haptic
- [ ] Step up: Point at curb or stairs ascending → "Curb or step up" / "Stairs ascending" + medium haptic  
- [ ] Cooldown: Announcement doesn't repeat more than once per ~3 seconds
- [ ] Toggle off: Disable "Detect stairs & curbs" → no step announcements
- [ ] Toggle on: Re-enable → announcements resume
- [ ] Non-Pro (if available): No crash, no step announcements, toggle shows "Requires iPhone Pro"

---

## Out of Scope (deferred)

- Non-LiDAR depth estimation (v1.3 — requires bundling a CoreML depth model ~50MB)
- Traffic light detection (v1.3 — separate spec)
- Text/sign reading (v1.4 — separate spec)
