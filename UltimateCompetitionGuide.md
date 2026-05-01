# OmniSight: Ultimate Competition Guide
**TSA 2026 | Technical Deep-Dive & Memorization Sheet**

---

## 1. System Architecture: The Data Flow
To achieve real-time performance, we built a **multi-threaded asynchronous pipeline**.
1.  **The Engine**: `ARSession` runs at 60fps, capturing 4K camera frames and a 256x192 LiDAR depth map.
2.  **The Pipeline**: Frames are passed to `OmniPipeline`, which isolates vision processing on a custom dispatch queue (`visionQueue`) to prevent the main UI thread from lagging.
3.  **The Intelligence**: 
    *   **YOLOv8m-oiv7**: A medium-scale convolutional neural network running on the Apple Neural Engine (ANE).
    *   **Scene Classification**: A secondary Vision model that identifies the room type every 10 seconds to maintain thermal stability.
4.  **The Output**: `SpeechEngine` manages a prioritized queue (`QueueItem`) where "Emergency" alerts (Priority 1) pre-empt "Awareness" messages (Priority 10).

---

## 2. Technical Feature Deep-Dive

### A. LiDAR Depth Semantics
*   **The Logic**: We don't just look; we measure. We sample the LiDAR depth map at two critical points:
    *   **Center Point (0.5, 0.5)**: Used for the "Spatial Radar" to detect immediate obstacles ahead.
    *   **Ground Point (0.5, 0.85)**: Used for **Surface Change Detection**.
*   **The Solve**: If `groundDepth` becomes significantly greater than `centerDepth` (+1.5m), the system detects a drop-off (stairs or a curb) and fires a unique haptic pulse before the user even steps forward.

### B. Intelligent Object Awareness (YOLO)
*   **Confidence Guarding**: We use a dual-threshold system. Objects require a minimum confidence of 0.50 (0.60 for furniture) and must be seen in at least **3 consecutive frames** to be announced. This prevents "ghost detections."
*   **Vector Analysis**: For every object, we calculate its **Pan** (left/right position) and **Velocity** (approach speed). If an object has a negative velocity > 0.4 m/s, it's flagged as "Approaching" and moved to high-priority speech.

### C. The Physical UI (Haptic Syntax)
We developed a distinct vocabulary for vibrations:
1.  **Collision Warning**: A continuous, high-intensity buzz (Impact Alert).
2.  **Nearby Pulse**: A subtle, single "pop" using the Taptic Engine to signal an object in the 2-5m range.
3.  **Emergency SOS**: A recurring triple-pulse used for the 5-second countdown.

---

## 3. Engineering Challenges & Solutions

### Challenge 1: The "Retaining ARFrames" Crash
*   **The Problem**: ARKit has a limited pool of camera frames. If Vision processing takes longer than 16ms, frames start to back up, eventually freezing the camera.
*   **The Solution**: We implemented explicit memory management using `autoreleasepool` blocks inside our Vision closures. We also added manual result-clearing (`request.results = nil`) to force the OS to release the camera buffer immediately after the AI is done.

### Challenge 2: Thermal Throttling
*   **The Problem**: Running LiDAR and YOLO simultaneously generates massive heat, causing the CPU to throttle and detection to slow down.
*   **The Solution**: We optimized the "Cognitive Load" of the app. We gated scene classification to a 10-second interval and implemented a **1.5-second debounce** on camera restarts to protect the hardware.

### Challenge 3: ANE vs. GPU Fallback
*   **The Problem**: Some models crash the Apple Neural Engine during ahead-of-time (AOT) compilation.
*   **The Solution**: We configured our CoreML `computeUnits` to `.cpuAndGPU` fallbacks. This ensures that even if the hardware-accelerated ANE fails, the app stays running with zero downtime.

---

## 4. Key Stats for Judges
*   **Inference Latency**: <100ms end-to-end.
*   **LiDAR Range**: 5 Meters (The "Safety Bubble").
*   **Whitelisted Classes**: 12 (Person, Car, Truck, Bus, Bike, Motorcycle, Dog, Cat, Chair, Table, Door, Stairs).
*   **Execution**: 100% On-Device (Privacy and Offline functionality).

---

## 5. Why We Chose This Idea
We wanted to move accessibility from **Reactive** to **Proactive**. Traditional canes are 1D sensors (length). OmniSight is a 3D sensor (volume). By using native Apple frameworks, we transformed a consumer device into a medical-grade accessibility tool without the $10,000 price tag of specialized hardware.

---
*OmniSight: Precision Perception.*
