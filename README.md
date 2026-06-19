# OmniSight — Real-Time Assistive Intelligence for the Visually Impaired

OmniSight is an on-device assistive vision system for iPhone that goes beyond simple object detection. It tracks objects across frames, reasons about the spatial scene, generates natural-language summaries, and intelligently prioritizes voice feedback so users get the information they need without a wall of speech.

Built for iOS 16+ using ARKit, CoreML (YOLOv8), LiDAR depth fusion, and AVSpeechSynthesizer. No cloud — all inference runs on-device in real time.

**2nd Place — TSA Software Development 2025**

---

## Architecture

```
ARKit camera (30fps)
    ↓
CoreMLDetector          ← YOLOv8 via Vision framework
    ↓ RawDetection[]
ObjectTracker           ← SORT-inspired IoU matching + state machine
    ↓ TrackedObject[]   (TENTATIVE → CONFIRMED → COASTING)
OpticalProcessor        ← LiDAR depth fusion, DTO assembly
    ↓ FramePayload
SpeechEngine            ← Priority queue + per-class cooldowns + mode gating
    ↓
SceneContextEngine      ← Scene-level NL summaries (fires every 6s)
    ↓
AVSpeechSynthesizer     → User hears: "Two people ahead, one approaching from the right"
```

---

## Features

### Object Tracking (SORT-inspired)
- **IoU-based matching** — correctly handles multiple same-class objects in the same frame; falls back to center-distance when boxes don't overlap (common at 15fps with fast-moving objects)
- **Track state machine** — TENTATIVE (< 3 matches) → CONFIRMED → COASTING (position extrapolated via screen velocity) → pruned after 3 missed frames
- **Position prediction** — coasting tracks extrapolate position from historical screen velocity so re-association stays accurate after brief occlusion
- Coasting tracks are excluded from all TTS announcements (extrapolated position only)

### Spatial Reasoning
- 7-zone directional language: "far left", "left", "slightly left", "straight ahead", "slightly right", "right", "far right"
- Distance via **focal-length geometry** for 18 known object classes (`distance = realHeight × focalLength / detectedHeightPx`); area heuristic fallback for unknown classes
- LiDAR depth fusion overrides optical distance when available (Pro/Pro Max models)
- Velocity estimation via exponential moving average — negative = approaching

### Scene Summarization
- `SceneContextEngine` runs every 6 seconds (independent of per-object TTS)
- **Change detection**: lightweight scene signature (class + distance bucket) suppresses identical summaries
- Generates contextual phrases: "Person approaching to your right", "Busy area — 5 objects nearby", "Path ahead is clear"
- Priority scales with urgency: closing hazard (75) → nearby hazard (50) → density summary (10)

### Intelligent TTS System
- **Priority queue** drains at 10Hz; each item has an expiry (emergency: 1.5s, summary: 3s, static: 2s)
- **Per-object cooldown** (5s) + **per-class cooldown** (furniture: 15s, vehicles: 5s) — same object never spams
- **Verbosity modes**: Normal / Low Noise (2× cooldowns, suppress low-priority) / Critical Only
- Emergency interrupts (collision <1.2m direct-ahead) bypass queue and cancel any in-progress speech
- **Travel mode**: auto-detected from object approach velocity; adjusts thresholds for vehicle context

### Object-Finding Mode
- Switch from Navigation → **Finding mode** via the mode pill in the UI (or "Find Object" sheet)
- All TTS suppressed except when the target class is confirmed (≥ 3 matched frames)
- On detection: "Found [object], [direction], [distance]" at priority 95, 4s cooldown
- Returns to Navigation mode with one tap

### LiDAR Obstacle Detection
- Samples center-point depth at 10fps (throttled from camera rate)
- Skips if optical system already identified the object at that distance
- Obstacles < 1.2m ahead → emergency speak at rate 0.56 (faster than normal 0.52)
- 2.5s cooldown prevents repeat warnings for stationary walls

---

## Modes

| Mode | Behavior |
|------|----------|
| Navigation | Full scanning: obstacles, approaching objects, scene summaries |
| Finding | Suppresses all speech until target class is confirmed, then announces direction + distance |

---

## Settings

| Setting | Options |
|---------|---------|
| Verbosity | Normal / Low Noise / Critical Only |
| Units | Metric / Imperial |
| Hazard Alarms | On/Off |
| Haptic Feedback | On/Off |
| Directional Audio Pan | On/Off |

Two-finger double-tap mutes speech for 10 seconds.

---

## Technical Notes

- **15fps ingest cap** (ARKit runs at 30fps, every other frame is dropped to halve tracker load)
- **Video format capped at 1920px width** at 30fps — prevents SIGKILL on Pro Max from memory pressure with `sceneDepth` enabled
- **1.5s camera debounce** on start/stop prevents ARSession resource conflicts
- `OmniSightKit` is a local Swift Package — all detection/tracking/scene logic lives there; the app target handles only UI and speech

---

## Requirements

- iPhone 12 Pro or newer (LiDAR required for depth; app degrades gracefully to optical-only on non-Pro)
- iOS 16.0+
- Camera permission

---

## How to Run

1. Clone repo
2. Open `ios/OmniSight/OmniSight.xcodeproj` in Xcode 15+
3. Select your device (simulator lacks camera/LiDAR)
4. Build & run (`⌘R`)
