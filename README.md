# OmniSight Engine (Hemovision)

**TSA Nationals Software Development Submission**
**Submission Deadline:** Mid-May
**Theme:** Removing barriers and increasing accessibility for people with vision/hearing disabilities.

OmniSight Engine is a 100% offline, cross-platform app utilizing computer vision to map environmental surroundings into an 8D Audio soundscape for the blind, and an AR Haptic interface translating critical audio (sirens/alarms) into visual HUDs for the deaf.

---

## 🗂 Code Map & Architecture structure

The project employs a pure **MVC Architecture**, heavily integrating **C++ Multi-threading** for Machine Learning computation.

*   `BUG_LOG.md`: Our documented list of 20 bugs and resolutions (Rubric Phase 10).
*   `lib/`
    *   `main.dart`: The main application entry point initializing the app theme.
    *   `core_engine.dart`: **Model Wrapper.** Custom Dart FFI wrapper translating raw memory pointers into Dart arrays.
    *   `controllers/`
        *   `main_controller.dart`: **Controller.** Handles the Dart **Isolates** (Multi-threading) execution for background processing so the UI frame rate never drops. Includes standard View Streams.
    *   `views/`
        *   `home_view.dart`: **View.** The Mastery Level GUI. Implements AR Haptic overlays, bounding box projection, and High-Contrast usability structures.
*   `src/`
    *   `core_engine.h` & `core_engine.cpp`: **The Brains.** Custom priority queue object sorting, distance estimation math relying on bounding box depth inversion, and cross-platform export hooks.

---

## 🚀 Execution & Constraints

*   **Offline Mode:** This app requires **zero Wi-Fi**. All simulated processing happens strictly on the local machine via FFI.
*   **Security:** There are NO hardcoded API keys. 
*   **Performance:** UI interactions will not lag behind the CV engine due to the strict implementation of `std::mutex` C++ constructs combined with `Isolate.run` in Dart.

## 🛠 Compilation (Code Defense Prep)

1. Make sure Flutter (`>= 3.2.0`) is installed.
2. Build the C++ DLL / SO (based on platform). For windows, Visual Studio C++ build tools compile `src/core_engine.cpp` to `core_engine.dll` and push to root or build folder.
3. Run `flutter run` on target physical device or local Windows host.

**Why Priority Queue? (Code Defense FAQ)**
> Q: "Show us the function that handles the spatial audio mapping. Why did you choose this data structure?"
>
> A: "We used a Priority Queue (`std::priority_queue<QueueElement>`) for object detection in `core_engine.cpp`. This ensures the most 'dangerous' objects—such as moving cars estimated via our custom distance heuristics—are processed and announced to the user before harmless items like distant chairs. This is mathematically defined in the `calculate_threat_level` function."
