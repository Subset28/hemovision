# OmniSight Engine

> **TSA Nationals 2025–2026 · Software Development**
> *Removing barriers. Restoring independence.*

<div align="center">

![Platform](https://img.shields.io/badge/Platform-iOS%20%7C%20Android%20%7C%20Windows-blue?style=for-the-badge)
![Flutter](https://img.shields.io/badge/Flutter-3.41.6-54C5F8?style=for-the-badge&logo=flutter)
![C++](https://img.shields.io/badge/C++-17-00599C?style=for-the-badge&logo=cplusplus)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)
![Offline](https://img.shields.io/badge/Offline-100%25-success?style=for-the-badge)

</div>

---

## What is OmniSight Engine?

OmniSight Engine is a **100% offline, cross-platform accessibility application** that gives people with visual and hearing impairments a comprehensive environmental awareness system.

It operates in two directions simultaneously:

| Direction | For | Description |
|-----------|-----|-------------|
| **Vision → Audio** | Blind / Low Vision | On-device AI detects obstacles and maps them into a 3D spatial audio soundscape. Objects closer to the user are louder. Objects to the left play in the left ear. |
| **Audio → Vision** | Deaf / Hard of Hearing | FFT audio analysis detects emergency sirens and alarms, immediately triggering a full-screen AR visual HUD with directional information. |

A **Caregiver Dashboard** runs on a second device (no internet — local TCP hotspot only) and receives live threat alerts from the primary user's device.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     OmniSight Engine                          │
│                                                              │
│   ┌─────────────┐    Dart FFI     ┌──────────────────────┐  │
│   │  Flutter UI │◄───────────────►│   C++ Core Engine    │  │
│   │  (MVC View) │                 │  (core_engine.cpp)   │  │
│   └──────┬──────┘                 └──────────┬───────────┘  │
│          │                                   │               │
│          │ Streams                    ┌──────▼──────────┐    │
│   ┌──────▼──────┐             ┌──────┤  Priority Queue  │    │
│   │    Main     │             │      │  (Threat Sorted) │    │
│   │ Controller  │             │      └─────────────────-┘    │
│   │  (Isolate)  │             │                              │
│   └──────┬──────┘      ┌──────▼──────────┐                  │
│          │             │  SLAM-lite Map   │                  │
│   ┌──────▼──────┐      │  (Spatial Mem)  │                  │
│   │  Caregiver  │      └─────────────────┘                  │
│   │  Service    │                                            │
│   │ (TCP Socket)│                                            │
│   └─────────────┘                                            │
└──────────────────────────────────────────────────────────────┘
```

### Design Pattern: MVC

| Layer | File | Responsibility |
|---|---|---|
| **Model** | `core_engine.dart` | FFI type definitions, `OmniSightEngine` wrapper |
| **Controller** | `main_controller.dart` | Dart Isolate dispatch, stream management, caregiver sync |
| **View** | `home_view.dart`, `caregiver_view.dart`, `settings_view.dart` | UI rendering, animation, user input |
| **Service** | `caregiver_service.dart` | TCP socket server + client |
| **Core (C++)** | `src/core_engine.cpp` | ML inference, distance math, FFT, SLAM |

---

## The Four Modules

### Module A — Vision to Audio (CV + Spatial Audio)
- **Local AI:** YOLOv8 ONNX model loaded via OpenCV DNN. Zero cloud. Zero latency.
- **Distance Estimation:** `D = (W_real × f) / W_pixel` — focal-length inverse formula calibrated to standard phone cameras.
- **Priority Queue:** `std::priority_queue<QueueElement>` sorts objects by composite threat score. The most dangerous hazard is always announced first.
- **Spatial Audio:** Panned 3D audio based on object X-position and distance.

### Module B — Audio to Vision (FFT + AR HUD)
- **FFT Analysis:** Cooley-Tukey algorithm on raw PCM audio samples.
- **Siren Band Filter:** Detects 750–1800 Hz rising-frequency signatures.
- **AR Alert HUD:** Full-screen glassmorphic overlay with directional indicator and haptic feedback.

### Module C — Caregiver Integration (Local TCP)
- **TCP Server:** Primary user device binds on port `8085`.
- **TCP Client:** Caregiver device connects via local hotspot IP.
- **Zero Internet:** Works in competition halls, hospitals, anywhere — no router needed.
- **Live Telemetry Graph:** `CustomPaint` Bezier-curve visualization of threat density over time.

### Module D — SLAM-lite Spatial Memory
- **Topography Array:** `std::vector<SpatialPoint>` in C++. Each detected object adds a timestamped 3D coordinate with a 30-frame lifespan.
- **Decay Algorithm:** Points decrement each frame; expired points are erased via `std::remove_if`.
- **Radar Widget:** `CustomPaint` draws a real-time bird's-eye radar with glow halos for close threats.

---

## Technical Highlights (TSA Rubric: Complexity)

| Feature | Implementation | Why It Matters |
|---|---|---|
| Multi-threading | `Flutter compute()` + `std::mutex` | UI never drops below 60fps during C++ inference |
| Memory Management | `calloc` / `calloc.free` + RAII C++ | Zero memory leaks across FFI boundary |
| Priority Sorting | `std::priority_queue` (max-heap) | O(log n) threat prioritization |
| Distance Math | Pinhole camera focal-length formula | Mathematically provable, not ML-dependent |
| FFT Analysis | Cooley-Tukey radix-2 | O(n log n) audio frequency extraction |
| Offline Networking | Raw `dart:io` TCP ServerSocket | No third-party networking libraries |
| Cross-Platform FFI | `DynamicLibrary.open` + `Struct` | Single codebase for iOS, Android, Windows |

---

## Project Structure

```
hemovision/
├── lib/
│   ├── main.dart                    # App entry, splash screen, theme
│   ├── core_engine.dart             # FFI type bindings (Model)
│   ├── controllers/
│   │   └── main_controller.dart     # Business logic, streams (Controller)
│   ├── services/
│   │   └── caregiver_service.dart   # TCP socket server/client
│   └── views/
│       ├── home_view.dart           # Primary AR interface (View)
│       ├── caregiver_view.dart      # Telemetry dashboard
│       └── settings_view.dart       # Engine calibration
├── src/
│   ├── core_engine.h                # C++ header, FFI export macros
│   └── core_engine.cpp              # C++ engine implementation
├── android/
│   └── app/src/main/
│       ├── AndroidManifest.xml      # Permissions, app config
│       └── kotlin/.../MainActivity  # Flutter embedding
├── ios/
│   └── Runner/
│       └── Info.plist               # iOS permissions, bundle config
├── assets/
│   └── models/                      # YOLOv8 ONNX model (deployment)
├── BUG_LOG.md                       # 20 documented bugs (Phase 10)
├── CODE_MAP.md                      # Architecture guide for judges
├── INTERVIEW_DEFENSE_GUIDE.md       # TSA code defense prep
├── CMakeLists.txt                   # C++ build config
└── pubspec.yaml                     # Flutter dependencies
```

---

## Running the App

### Prerequisites
- Flutter SDK ≥ 3.2.0 (install via [Puro](https://puro.dev))
- For Windows: Visual Studio 2022 with "Desktop development with C++"
- For iOS: macOS + Xcode 15+ + CocoaPods
- For Android: Android Studio + SDK 33+

### Quick Start (Mock Mode — works everywhere)

```bash
# Install dependencies
flutter pub get

# Run on Windows (no C++ compilation needed — mock mode auto-activates)
flutter run -d windows

# Run on connected iOS device
flutter run -d <device-id>

# Run on Android
flutter run -d android
```

### Compile the C++ Core (Full AI Mode)

```bash
# Windows (MSVC)
cd src
cl /LD core_engine.cpp /Fe:core_engine.dll

# Linux / Android NDK
g++ -shared -fPIC -o libcore_engine.so core_engine.cpp

# With OpenCV (Full YOLOv8 inference)
g++ -shared -fPIC -DUSE_OPENCV \
    -I/usr/local/include/opencv4 \
    -lopencv_dnn -lopencv_core -lopencv_imgproc \
    -o libcore_engine.so core_engine.cpp
```

---

## Offline & Security Compliance

| Requirement | Status |
|---|---|
| No hardcoded API keys | ✅ Zero keys in codebase |
| No internet required | ✅ `usesCleartextTraffic="false"` in Android |
| Local AI only | ✅ ONNX model loaded from device assets |
| Caregiver sync offline | ✅ LAN TCP socket, no cloud relay |
| Data stored | ✅ None — no persistent storage of camera/audio |

---

## TSA Rubric Mapping

| Phase | Rubric Requirement | Evidence |
|---|---|---|
| 1 | Problem Definition | Accessibility gap for 253M visually impaired globally |
| 2 | Planning & Design | MVC architecture, module breakdown in `CODE_MAP.md` |
| 3 | Development | 4 working modules, Flutter + C++ |
| 4 | Testing | `BUG_LOG.md` — 20 documented bugs with resolutions |
| 5 | Code Complexity | FFI bridge, Priority Queue, SLAM, FFT, Isolates |
| 6 | Mastery | Custom distance formula, SLAM spatial memory |
| 7 | Interface | Glassmorphism, AR overlays, accessibility focus |
| 8 | Offline | 100% offline — works in airplane mode |
| 9 | Innovation | Dual-direction accessibility (vision↔audio) |
| 10 | Documentation | This README, `CODE_MAP.md`, `INTERVIEW_DEFENSE_GUIDE.md` |

---

## License

MIT License — see [LICENSE](LICENSE) for details.

*Built for TSA Nationals 2025–2026 Software Development.*
