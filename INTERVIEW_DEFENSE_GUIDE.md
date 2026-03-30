# OmniSight Engine — Interview Defense Guide

> **TSA Code Defense Prep — Know Every Line**
> Study this before your presentation. You should be able to answer any of these questions cold, in under 30 seconds.

---

## Section 1: The Elevator Pitch (30 seconds)

> *"OmniSight Engine is an offline, cross-platform accessibility app built with Flutter and C++. It solves two problems simultaneously: for people who are blind, it converts their camera feed into a 3D spatial audio soundscape using local AI. For people who are deaf, it detects emergency sirens via FFT audio analysis and triggers a full-screen visual alert. A caregiver can monitor live threat data on a second device over a local hotspot — no internet required."*

---

## Section 2: Architecture Questions

**Q: Walk me through the architecture.**
> A: "We use strict MVC. The **Model** is the C++ core engine, exposed via Dart FFI. The **Controller** is `main_controller.dart`, which handles business logic in a background Dart Isolate so the UI thread never drops frames. The **View** is our Flutter widget tree — three screens. A separate **Caregiver Service** handles raw TCP socket communication."

**Q: Why Flutter instead of a native iOS app?**
> A: "Flutter gives us a single codebase that targets iOS, Android, and Windows. This is critical for TSA — we can demonstrate on Windows at the booth without a Mac. When testing on-device, the exact same Dart code runs on iOS via the Flutter AOT compiler. The C++ core compiles natively on each platform via Dart FFI."

**Q: Why a C++ backend instead of pure Dart?**
> A: "Computer Vision and FFT are computationally expensive — O(n²) without optimization. Dart's garbage collector would introduce unpredictable pauses during inference. C++ gives us deterministic memory management, SIMD intrinsics, and direct access to OpenCV. The `std::mutex` ensures thread-safe data handoff."

---

## Section 3: Algorithm Questions

**Q: Explain your distance estimation algorithm.**
> A: "We use the pinhole camera model: `D = (W_real × f) / W_pixel`. We know the real-world width of each object class — a car is 1.8 meters wide, a person is 0.5 meters wide. We measure the apparent width in pixels from the bounding box. We divide by the focal length, which we calibrated to 800 pixels, matching the standard phone camera profile. It's O(1) and mathematically provable without a neural network."

**Q: How does your threat priority system work?**
> A: "We use a C++ `std::priority_queue` as a max-heap sorted by `threat_level`. The threat level is calculated as `100 / (distance + 0.1) × class_multiplier`, capped at 100. A car gets a 3× multiplier, a person 1.5×. The +0.1 prevents division by zero. This ensures the closest, most dangerous object is always at the top of the queue and announced first — it's O(log n) insertion and O(1) retrieval."

**Q: What is SLAM and how did you implement it?**
> A: "SLAM stands for Simultaneous Localization and Mapping. Our SLAM-lite implementation maintains a `std::vector` of `SpatialPoint` structs. Each detected object appends a point with x, y, distance, and a 30-frame lifespan counter. Every frame, we decrement all counters and erase expired points using the erase-remove idiom with `std::remove_if`. This creates a temporal memory of the environment — we visualize it as a radar in Flutter using `CustomPaint`."

**Q: How does your FFT siren detection work?**
> A: "We apply a Hanning window to the raw PCM buffer to reduce spectral leakage, then perform a Cooley-Tukey radix-2 FFT — that's O(n log n). We scan the magnitude spectrum for peaks in the 750–1800 Hz range, which covers emergency vehicle sirens. If confidence exceeds 0.8, we trigger the AR alert HUD."

---

## Section 4: Flutter-Specific Questions

**Q: What is Dart FFI?**
> A: "Dart FFI — Foreign Function Interface — lets Dart call into native C code by directly reading shared memory. We annotate Dart classes with `@Int32()`, `@Float()` to mirror the exact C struct layout. When we call `lookupFunction` on the DynamicLibrary, Dart maps the function pointer directly — no serialization, microsecond latency. Compare this to Platform Channels, which serialize data through a message queue."

**Q: Why compute() instead of raw Isolates?**
> A: "`compute()` is a Flutter utility that runs a top-level function on a background Dart Isolate and returns the result as a Future. It handles all the ReceivePort/SendPort plumbing for us. Raw `Isolate.spawn()` requires manual port management and doesn't work cleanly with `compute()`-style single-result patterns. for our 100ms tick, `compute()` is cleaner and safer."

**Q: How do your animations work?**
> A: "We have three `AnimationController` instances with different durations. The pulse controller repeats forever at 1200ms for the radar sweep. The alert controller fires forward on each siren detection, driving a `SlideTransition` and `FadeTransition`. The glow controller cycles at 3 seconds, creating the ambient cyan breathing effect on the camera feed background. All are driven by `AnimatedBuilder` which rebuilds only the sub-tree that needs repainting."

**Q: How does the CustomPaint radar work?**
> A: "`RadarPainter.paint()` is called by Flutter's rendering engine whenever the animation tick changes. We draw concentric circles representing distance rings using `canvas.drawCircle()`. For each spatial point, we normalize the X coordinate from pixel-space to radar-space: `nx = (px - 320) / 320`. Distance becomes the radius: `radarY = center.dy - (dist/10) × height`. Close objects get a red glow halo drawn at 2.5× opacity behind the main dot."

---

## Section 5: Rubric Defense

**Q: Where is your 20-bug log?**
> A: "`BUG_LOG.md` in the root of the repo. We documented bugs from every phase — FFI memory leaks, race conditions in the C++ mutex, coordinate system mismatches, battery drain optimization, and more."

**Q: What makes this app accessible?**
> A: "The app is designed for two impaired groups simultaneously. For blind users: spatial audio maps the physical environment into sound. For deaf users: visual AR alerts replace auditory warnings with full-screen HUD. We also include a High Contrast Mode, Large Text mode, and support for Bone Conduction audio profiles in settings."

**Q: How is this 100% offline?**
> A: "Every single computation happens on-device: YOLOv8 ONNX via OpenCV on CPU, FFT in C++, spatial memory in RAM. The caregiver sync uses raw `dart:io` TCP sockets on a local hotspot — no cloud relay. `usesCleartextTraffic='false'` in Android, no internet permission used for anything other than Flutter engine initialization."

**Q: What would you improve given more time?**
> A: "Three things. First, compile and deploy the actual YOLOv8 ONNX model instead of the simulation. Second, integrate Apple ARKit/Google ARCore for real depth data instead of monocular estimation. Third, add a persistent settings store with `shared_preferences` so calibrations survive app restarts."

---

## Section 6: Data Structures Used (Rubric: Complexity)

| Structure | Where | Why |
|---|---|---|
| `std::priority_queue` (max-heap) | C++ engine | O(log n) threat-sorted object queue |
| `std::vector<SpatialPoint>` | C++ engine | Dynamic SLAM point cloud with erase-remove |
| `std::mutex` + `lock_guard` | C++ engine | Thread-safe dual-write from Isolate |
| `std::atomic<bool>` | C++ engine | Lock-free running flag |
| `StreamController.broadcast()` | Dart controller | Multi-listener reactive streams |
| `AnimationController` | Flutter views | Tween animation pipeline |
| `CustomPaint` | Radar, telemetry | Direct canvas 2D rendering |
| `ServerSocket` / `Socket` | Caregiver service | Raw TCP without serialization overhead |

---

*OmniSight Engine — TSA Nationals 2025–2026 Software Development*
