# OmniSight — System Overview

Readable in under 2 minutes. Technical audience.

---

## Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│  PERCEPTION LAYER (OmniSightKit)                                     │
│                                                                       │
│  ARKit (30 fps)                                                       │
│    │  CVPixelBuffer + optional LiDAR sceneDepth                      │
│    ▼                                                                  │
│  OmniPipeline ──throttle to 15 fps──► OpticalProcessor               │
│                                              │                        │
│                                    VNImageRequestHandler             │
│                                              │                        │
│                                    CoreMLDetector (YOLOv8 / Vision)  │
│                                    focal-length distance estimate     │
│                                    LiDAR depth override (Pro models) │
│                                              │ [RawDetection[]]      │
│                                              ▼                        │
│                                    ObjectTracker (SORT-lite)         │
│                                    IoU matching + center fallback    │
│                                    TENTATIVE → CONFIRMED → COASTING  │
│                                    velocity prediction (vX, vY)      │
│                                              │ [TrackedObject[]]     │
│                                              ▼                        │
│                                    FramePayload (DetectedObjectDTO[])│
└─────────────────────────────────────────────────────────────────────┘
         │
         │  @Published lastPayload
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│  REASONING LAYER (OmniSightApp)                                      │
│                                                                       │
│  SpeechEngine.onFrame()                                               │
│    │                                                                  │
│    ├─ filterObjects()    whitelist + range + confidence + isCoasting │
│    │                                                                  │
│    ├─ [mode dispatch]                                                 │
│    │     .finding(cls)   → handleFindingMode()                       │
│    │     .hazardPriority → handleHazardPriority()                    │
│    │     .navigation     → (fall through)                            │
│    │                                                                  │
│    ├─ detectEmergency()  closing velocity < -0.8 m/s + < 2m         │
│    ├─ queueApproaching() velocity < -0.4 m/s, per-object cooldown   │
│    ├─ queueSceneSummary() SceneContextEngine (6s cooldown + sig)    │
│    └─ queueStaticObject() closest confirmed, per-class cooldown      │
│                                                                       │
│  SceneContextEngine                                                   │
│    signature hash → change detection → natural-language summary      │
│    density: clear / sparse / moderate / crowded                      │
│    urgency score → TTS priority                                       │
└─────────────────────────────────────────────────────────────────────┘
         │
         │  priority queue (sorted, expiry-filtered)
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│  OUTPUT LAYER                                                         │
│                                                                       │
│  drainQueue() — 10 Hz timer                                           │
│    priority-sorted QueueItem[] → AVSpeechSynthesizer                 │
│    emergencySpeak() bypasses queue (priority 99+)                    │
│                                                                       │
│  LiDAR obstacle channel (parallel, from OmniPipeline.$middleSensor) │
│    depth < 1.2m → immediate warn / emergency speak                   │
│                                                                       │
│  HapticManager — warning vibration on hazard / LiDAR alert          │
└─────────────────────────────────────────────────────────────────────┘
         │
┌─────────────────────────────────────────────────────────────────────┐
│  INSTRUMENTATION (toggle-able, zero-cost when off)                   │
│                                                                       │
│  PerformanceMonitor — p50/p95 latency ring buffer, track counters,  │
│                        TTS emit/suppress ratios, scene update counts │
│  DecisionLog        — 60-entry ring buffer, layer-tagged decisions,  │
│                        shown in debug overlay (0.5 Hz refresh)       │
│  BenchmarkSession   — 30s timed session → MetricsReport JSON        │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow — Per Frame

```
ARKit frame arrives
  └─► OmniPipeline checks throttle (minEmitInterval ≈ 67ms → ~15 fps)
        └─► OpticalProcessor.processOnWorkQueue()  [Vision workQueue, serial]
              ├─ VNImageRequestHandler.perform()   [blocks workQueue ~30-80ms]
              │     └─► CoreMLDetector callback
              │           ├─ VNRecognizedObjectObservation → RawDetection
              │           ├─ distance: focal-length formula (18 classes)
              │           │            or fallback √-area heuristic
              │           └─ LiDAR: depthMap.sampleDepth(at: centerNorm)
              ├─ ObjectTracker.update()            [SORT IoU matching]
              ├─ PerformanceMonitor.recordFrame()
              ├─ DecisionLog.recordTrackEvents()
              └─ FramePayload → DispatchQueue.main → OmniSightSession
                    └─► SpeechEngine.onFrame()     [@MainActor]
```

---

## Latency Budget (iPhone Pro, indoor, 2-4 objects)

| Stage                       | Typical    | Worst case  |
|-----------------------------|-----------|-------------|
| ARKit frame → workQueue     | ~2 ms     | ~5 ms       |
| Vision/CoreML inference     | 30–55 ms  | 90 ms       |
| Tracker (IoU matching)      | <1 ms     | 3 ms (20+)  |
| FramePayload → main thread  | <1 ms     | 2 ms        |
| SpeechEngine.onFrame()      | <1 ms     | 2 ms        |
| **End-to-end (p50)**        | **40 ms** | **100 ms**  |

Effective pipeline throughput: 12–15 fps (limited by Vision inference).
LiDAR depth sampling adds <1 ms (single pixel read from locked buffer).

---

## Decision Flow — TTS Priority System

```
onFrame() receives N confirmed objects
  │
  ├─ EMERGENCY (priority 99)
  │     condition: any object closing at > 0.8 m/s, distance < 2m
  │     behavior: interrupt queue, emergency speak
  │
  ├─ APPROACHING (priority 80)
  │     condition: velocity < -0.4 m/s, per-object cooldown 3s
  │     behavior: "Person approaching from the right"
  │
  ├─ SCENE SUMMARY (priority 0–85, from urgency score)
  │     condition: SceneContextEngine cooldown (6s) + scene changed
  │     behavior: natural-language summary of whole scene
  │
  └─ STATIC OBJECT (priority 10–75, class-dependent)
        condition: closest confirmed, per-class cooldown (5–15s)
        behavior: "Chair, slightly left, 2.3 meters"

Suppression logged to DecisionLog. Emissions counted by PerformanceMonitor.
Target: tts_suppressed_ratio > 0.70 in typical indoor environment.
```

---

## Tracker State Machine

```
Detection arrives
  │
  ▼
TENTATIVE (matchCount < 3)
  │  ← matched 3 consecutive frames
  ▼
CONFIRMED (matchCount ≥ 3)
  │  ← detection lost
  ▼
COASTING (up to 3 frames)
  │  position extrapolated via (vX, vY) screen velocity
  │  ← re-matched within 3 frames → CONFIRMED (coastingRecovery+1)
  └─ not re-matched → PRUNED (tracksPruned+1)

IoU threshold: 0.10 (loose — handles partial occlusion)
Center-distance fallback: 0.22 normalized (when boxes don't overlap)
```

---

## Failure Modes & Known Limitations

### Tracking

| Scenario | Behavior | Root Cause |
|---|---|---|
| Fast-moving objects (runners, cyclists) | Track may coast → prune | Velocity extrapolation is linear; 3-frame coast window too short |
| Dense crowds (5+ people) | ID churn, repeated introductions | IoU matching degrades when many boxes overlap |
| Temporary occlusion (doorway) | Usually recovers via coast | 3-frame window handles ≤200ms gaps at 15fps |
| Object leaves then re-enters | New track ID assigned | No re-identification across prune events |

### Distance Estimation

| Scenario | Error | Root Cause |
|---|---|---|
| Seated person | Overestimated (~2×) | `knownHeights["person"] = 1.7m`; seated height ≈ 0.9m |
| Child | Overestimated | Same reason |
| Camera tilted down | Underestimated | Focal-length formula assumes upright frame |
| Glass / mirror / window | LiDAR reads glass surface | No material classification; depth is geometry only |
| Very close objects (<0.5m) | Unreliable | Bounding box fills frame; height-fraction formula breaks |

### TTS

| Scenario | Behavior |
|---|---|
| Busy street (10+ objects/frame) | SceneContextEngine clamps to "Busy area" summary; individual objects suppressed |
| Identical class at same distance | Per-class cooldown prevents spam; may miss brief appearance |
| Mode switch during speech | `speakImmediate()` interrupts; previous sentence cut off |

### LiDAR (Pro models only)

- Glass surfaces return the glass depth, not the object behind it
- Highly specular surfaces (polished floors) return noise or `nil`
- Max reliable range: ~5m; degraded above that

### Hazard Priority Mode

- Suppresses furniture / low-risk objects, not just non-hazards
- A falling box would be suppressed (not in hazardClasses)
- `userInVehicle` flag disables some LiDAR thresholds but is never set automatically

---

## Module Boundaries

```
OmniSightKit (Swift Package, no UI dependencies)
  ├─ OpticalCore.swift     — shared DTOs, hazardClasses, formatDistance
  ├─ CoreMLDetector.swift  — Vision/CoreML inference, distance estimation
  ├─ ObjectTracker.swift   — SORT tracker, TrackEvent emission
  ├─ OpticalProcessor.swift — frame orchestration, workQueue management
  ├─ SceneContextEngine.swift — NL scene summaries
  ├─ OmniSightSession.swift — @Published FramePayload bridge
  ├─ PerformanceMonitor.swift — metrics singleton
  └─ DecisionLog.swift     — decision audit singleton

OmniSightApp (iOS target)
  ├─ AppStateManager.swift — @MainActor controller, camera lifecycle
  ├─ SpeechEngine.swift    — TTS pipeline, mode dispatch
  ├─ ContentView.swift     — SwiftUI, debug overlay
  ├─ SettingsView.swift    — user preferences, benchmark UI
  ├─ BenchmarkSession.swift — 30s timed benchmark
  ├─ AppMode.swift         — mode enum (navigation/finding/hazardPriority)
  └─ HapticManager.swift   — vibration feedback
```
