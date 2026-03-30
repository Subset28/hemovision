# OmniSight Engine — Code Map

> **For TSA Judges & Code Defense Review**
> This document provides a complete navigation guide to every significant code element in the project, organized by module and rubric criterion.

---

## Quick Navigation

| You want to see... | Go to |
|---|---|
| Main app entry point | [`lib/main.dart`](lib/main.dart) |
| C++ AI engine | [`src/core_engine.cpp`](src/core_engine.cpp) |
| Distance estimation formula | [`src/core_engine.cpp` → `calculate_distance()`](src/core_engine.cpp) |
| Priority queue (threat sorting) | [`src/core_engine.cpp` → `QueueElement`](src/core_engine.cpp) |
| SLAM spatial memory | [`src/core_engine.cpp` → `_update_spatial_memory()`](src/core_engine.cpp) |
| FFT audio analysis | [`src/core_engine.cpp` → `process_audio()`](src/core_engine.cpp) |
| Dart FFI bridge definitions | [`lib/core_engine.dart`](lib/core_engine.dart) |
| Business logic controller | [`lib/controllers/main_controller.dart`](lib/controllers/main_controller.dart) |
| Isolate-based processing | [`lib/controllers/main_controller.dart` → `_tick()`](lib/controllers/main_controller.dart) |
| AR bounding box overlays | [`lib/views/home_view.dart` → `_buildObjectOverlays()`](lib/views/home_view.dart) |
| SLAM radar widget | [`lib/views/home_view.dart` → `RadarPainter`](lib/views/home_view.dart) |
| Audio alert HUD | [`lib/views/home_view.dart` → `_buildAlertHUD()`](lib/views/home_view.dart) |
| Caregiver TCP sync | [`lib/services/caregiver_service.dart`](lib/services/caregiver_service.dart) |
| Telemetry graph | [`lib/views/caregiver_view.dart` → `TelemetryGraphPainter`](lib/views/caregiver_view.dart) |
| Settings / calibration | [`lib/views/settings_view.dart`](lib/views/settings_view.dart) |

---

## Layer 1: C++ Core Engine (`src/`)

The performance-critical engine runs entirely in C++ and communicates with Flutter via Dart FFI.

### `core_engine.h`
- Defines `DetectedObject` struct (class ID, bounding box, distance, threat level)
- Defines `SpatialPoint` struct (x, y, z, persistence frames)
- Declares all exported C functions with `FFI_PLUGIN_EXPORT` macro
- Cross-platform: `__declspec(dllexport)` on Windows, `visibility("default")` on Unix

### `core_engine.cpp`

#### Class: `OmniSightEngine`
The main engine class. One instance lives for the entire app session.

**Private members:**
| Member | Type | Purpose |
|---|---|---|
| `object_queue` | `std::priority_queue<QueueElement>` | Max-heap sorted by `threat_level` |
| `spatial_memory_map` | `std::vector<SpatialPoint>` | SLAM point cloud |
| `engine_mutex` | `std::mutex` | Thread safety across Isolate calls |
| `is_running` | `std::atomic<bool>` | Safe multi-thread shutdown signal |
| `frame_counter` | `int` | Animation seed for simulation mode |

**Key Methods:**

##### `calculate_distance(bbox_width, bbox_height, class_id)`
```
Formula: D = (W_real × f) / W_pixel
Where:
  W_real  = known real-world object width (class-dependent lookup table)
  f       = focal length = 800px (calibrated for standard phone camera ~28mm equiv.)
  W_pixel = apparent width of the bounding box in pixels

This is a pinhole camera model. It is O(1), mathematically provable,
and does not require a neural network.
```

##### `calculate_threat_level(distance_m, class_id)`
```
Formula: threat = min(100/( d + 0.1 ) × multiplier, 100)
Where:
  d           = estimated distance in meters
  multiplier  = 3.0 (car) | 1.5 (person) | 1.0 (chair/default)

The +0.1 prevents division by zero at d=0.
The exponential decay means a 1m car scores ~272 (capped at 100).
A 10m chair scores ~9.
```

##### `process_frame(image_data, width, height, out_objects, max_objects)`
1. Acquires `engine_mutex` lock
2. If `USE_OPENCV` defined: runs YOLOv8 ONNX inference via `cv::dnn`
3. Simulation fallback: generates animated bounding boxes using `sin/cos(frame_counter)`
4. Calls `_update_spatial_memory()` for each detected object
5. Pushes objects to `object_queue`
6. Returns detected count

##### `_update_spatial_memory(obj)`
1. Decrements `persistence_frames` on all existing points
2. Erases points with `persistence_frames <= 0` via `std::remove_if` (erase-remove idiom)
3. Caps vector at 50 points to prevent unbounded memory growth
4. Appends new `SpatialPoint` with `persistence_frames = 30`

##### `process_audio(audio_buffer, buffer_size, out_frequencies)`
- In simulation: returns 1200 Hz / 0.87 confidence (siren profile)
- In real mode: scans FFT magnitude bins for peak, checks against 750–1800 Hz siren band

---

## Layer 2: Dart FFI Bridge (`lib/core_engine.dart`)

Establishes the Dart ↔ C++ memory boundary.

### Struct Definitions
`DetectedObject` and `SpatialPoint` are mirrored exactly from C++ using `dart:ffi`:
- `@Int32()`, `@Float()` annotations ensure C ABI alignment
- Dart reads fields directly from raw memory — zero serialization overhead

### `OmniSightEngine` class
- Constructor tries to open the native library for the current platform
- On failure → sets `_isMockMode = true` (graceful degradation)
- Mock mode allows full UI preview on any machine without compiled C++

---

## Layer 3: Controller (`lib/controllers/main_controller.dart`)

MVC Controller layer. Coordinates all business logic.

### Streams (Observable Outputs)
| Stream | Type | Consumers |
|---|---|---|
| `detectedObjectsStream` | `List<Map<String,dynamic>>` | `HomeView` — bounding boxes |
| `spatialMapStream` | `List<Map<String,dynamic>>` | `HomeView` — radar widget |
| `audioAlertStream` | `Map<String,dynamic>` | `HomeView` — alert HUD |
| `statsStream` | `Map<String,dynamic>` | `HomeView` — stats grid |

### `_tick()` — The Engine Cycle
Called every 100ms by a `Timer.periodic`.

1. Increments frame counter
2. Dispatches `_processFrame()` on a background Isolate via `compute()`
   - `compute()` serializes the function + args, runs on a new Dart Isolate, returns result
   - **This is why the UI never stutters** — the main thread is never blocked
3. Pushes results to all stream controllers
4. If caregiver sync active: forwards high-threat objects to `CaregiverService`

### `_processFrame(args)` — Top-Level Isolate Function
Must be top-level (not a method) for `compute()` to serialize it.
- Reads `isMock` flag from args
- In mock mode: calls `_mockFrame()` for realistic animated simulation
- In real mode: opens DynamicLibrary, calls FFI functions, returns results

---

## Layer 4: Views (`lib/views/`)

### `home_view.dart` — Primary AR Interface

**Key Widgets:**

| Widget | Implementation | Purpose |
|---|---|---|
| `_buildCameraFeed()` | `Container` + `CustomPaint(ScanGridPainter)` | Simulated camera background with grid |
| `_buildObjectOverlays()` | `Positioned` + `AnimatedContainer` | AR bounding boxes with threat bars |
| `_buildAlertHUD()` | `BackdropFilter` + `SlideTransition` | Siren alert overlay |
| `_buildRadarWidget()` | `CustomPaint(RadarPainter)` | SLAM bird's-eye radar |
| `_buildStatsGrid()` | `GridView` | Frames/alerts/uptime/fps counters |

**CustomPainters:**

| Painter | What It Draws |
|---|---|
| `ScanGridPainter` | 40px technical grid + corner markers |
| `RadarPainter` | Concentric rings, sweep pulse, SLAM points with glow halos |

### `caregiver_view.dart` — Telemetry Dashboard

**Key Widgets:**
- Live alert feed (JSON decoded from TCP stream)
- `TelemetryGraphPainter` — Bezier curve visualization of threat density over time using `Path.cubicTo()`
- Connection management (IP input, connect/disconnect)

### `settings_view.dart` — Engine Calibration

- Per-module toggles (Spatial Audio, Haptics, Siren Detection, SLAM)
- Sliders for volume, vibration intensity, detection range, threat threshold
- Accessibility options (High Contrast, Large Text)
- Audio output profile dropdown (Standard, Hearing Aid, Bone Conduction, Silent)

---

## Layer 5: Caregiver Service (`lib/services/caregiver_service.dart`)

### Server Mode (Primary User Device)
```dart
ServerSocket.bind(InternetAddress.anyIPv4, 8085)
```
- Binds to all IPv4 interfaces on the local network
- Accepts one caregiver connection
- Writes JSON-encoded alerts followed by `\n` delimiter

### Client Mode (Caregiver Device)
```dart
Socket.connect(ipAddress, 8085, timeout: Duration(seconds: 5))
```
- Connects to the primary user's LAN IP
- Splits incoming data by `\n` delimiter
- Decodes JSON into alert maps, pushes to stream

### Why Local TCP?
- Works without internet (airport, hospital, competition hall)
- No latency from cloud relay
- No data privacy concerns
- Survives network instability

---

## Code Defense FAQ

**Q: Why did you choose a `std::priority_queue` over a `std::vector`?**
> A priority queue gives us O(log n) insertion and O(1) access to the highest-threat object. A `std::vector` would require O(n) scanning every frame to find the most dangerous hazard. With 10+ objects in view, this optimization matters.

**Q: What is Dart FFI and why not use it differently?**
> Dart FFI (Foreign Function Interface) allows Dart to call C functions directly in memory. We use it instead of a method channel because it has microsecond-level latency vs. method channels (which serialize data through platform layers). For real-time CV at 30fps, this matters enormously.

**Q: How does the distance formula work?**
> We use the pinhole camera model: `D = (W × f) / w`. We know the real-world width of each object class (a car is ~1.8m wide). We measure its apparent pixel width. We divide. The focal length was empirically calibrated by photographing a known object at a known distance with a standard phone.

**Q: Why `compute()` instead of raw `Isolate.spawn()`?**
> `compute()` is a Flutter helper that serializes a top-level function and one argument, runs it on a new Dart Isolate, and returns the result — handling all the port plumbing for us. Raw `Isolate.spawn()` is more flexible but requires manual `ReceivePort`/`SendPort` management and can't easily pass Dart FFI pointers across isolate boundaries.

**Q: How is this app usable offline at TSA Nationals?**
> Every computation happens on the device: ML inference via ONNX on CPU, FFT in C++, spatial memory in RAM. Caregiver sync uses local TCP on a phone hotspot. No packet ever touches the internet.

---

*OmniSight Engine — TSA Nationals 2025–2026 Software Development*
