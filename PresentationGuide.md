# OmniSight: Redefining Autonomous Navigation
**TSA Competition 2026 | Project Presentation Guide**

---

## 1. The Problem: A World of Invisible Barriers
*   **The Statistic**: Over 250 million people worldwide live with vision impairment.
*   **The Gap**: Traditional tools (white canes, guide dogs) are physical and reactive. They don't provide *contextual* information (e.g., "That's a chair 2 meters ahead," or "You're in a crowded hallway").
*   **The Goal**: Create a "Digital Twin" of the environment that translates visual data into auditory and haptic intuition.

---

## 2. The Solution: OmniSight
OmniSight is an AI-powered spatial awareness system that uses the same technology found in self-driving cars (LiDAR + Computer Vision) to provide 360-degree navigation for the visually impaired.

### Core Philosophy: "Low Latency, High Trust"
*   **Sub-100ms Inference**: Decisions happen on-device, in real-time. No cloud lag.
*   **Physical UI**: Using the body’s natural haptic sensitivity to communicate distance and danger.

---

## 3. Key Features (The "Wow" Factors)

### A. Intelligent Object Tagging (CoreML + YOLOv8)
*   **What it does**: Real-time identification of 12 critical classes (People, Cars, Stairs, Doors, Furniture).
*   **Technical Edge**: Uses a customized YOLOv8 model optimized for the Apple Neural Engine.
*   **Logic**: It doesn't just name things; it calculates **Pan** (where it is) and **Velocity** (if it's moving toward you).

### B. The Spatial Radar (LiDAR + ARKit)
*   **What it does**: A constant 5-meter "protective bubble" around the user.
*   **Feature**: **Step & Drop-off Detection**. The system monitors the ground geometry. If the floor "disappears" (stairs/curbs), the user gets an instant haptic pulse.
*   **Obstacle Awareness**: Detects glass doors or thin objects that cameras might miss.

### C. The Physical UI (Haptic Design System)
*   **Collision Warning**: High-frequency buzz for immediate danger (<1m).
*   **Nearby Pulse**: Subtle taps for passing objects.
*   **Surface Pulse**: Unique vibration for stairs or drop-offs.

### D. Smart SOS & Safety
*   **The "Triple Tap"**: A simple gesture triggers a 5-second countdown.
*   **Automation**: Automatically grabs GPS coordinates and drafts an emergency SMS to 911/emergency contacts.

---

## 4. Technical Architecture
*   **Language**: Swift (Native performance).
*   **Frameworks**: 
    *   **ARKit**: For 6DOF tracking and LiDAR mesh ingestion.
    *   **Vision/CoreML**: For on-device neural processing.
    *   **AVFoundation**: For low-latency spatial audio feedback.
*   **Optimizations**: 
    *   Custom `OmniPipeline` to prevent ARFrame retention and camera lag.
    *   Thread-isolated vision processing to maintain 60fps UI.

---

## 5. Why OmniSight Wins
1.  **Innovation**: Translates LiDAR depth into haptic "vision."
2.  **Reliability**: Works entirely offline. No data required for navigation.
3.  **Human-Centric**: Designed with "Deaf-Blind" awareness—haptics work even when audio is muted.
4.  **Scalability**: Built on standard iOS hardware, making high-end assistive tech accessible to anyone with a phone.

---

## 6. Demo Script Highlights
*   *"Watch as I walk toward this chair. The app doesn't just see it; it feels it."*
*   *"Notice the warning for the stairs—the LiDAR detected the 1.5m drop-off before I even reached the edge."*
*   *"In an emergency, I don't need to find a button. Triple-tap, and help is on the way."*

---

## 7. Competition Checklist
- [ ] Model loaded and validated (YOLOv8m)
- [ ] LiDAR hardware check (iPad Pro/iPhone Pro)
- [ ] SOS coordinates verification
- [ ] Haptic engine calibration (Check intensity)
- [ ] Voice synthesis test (English-US)

---
*OmniSight: See the world, differently.*
