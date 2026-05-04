# OmniSight: Design and Development Process

## 1. Problem Identification & Requirements
**Societal Need**: According to the World Health Organization, over 2.2 billion people have a near or distant vision impairment. Current assistive tools (like canes or guide dogs) are effective for low-level obstacles but lack spatial awareness for dynamic environments (moving cars, people, hanging obstructions).

**Project Goal**: To create a "Visual Radar" that provides predictive safety warnings and spatial awareness using edge-computing.

**Key Requirements**:
- **Privacy**: No data should leave the device.
- **Speed**: Detections must happen in real-time (<30ms).
- **Safety**: The system must handle sensor failures and temporary obstructions.

## 2. System Architecture & Design
We chose **Swift** and the **Apple Vision/ARKit** ecosystem for its tight integration with the Neural Engine.

### Core Modules:
- **OmniSightKit**: A modular framework containing the vision and tracking engines.
- **CoreMLDetector**: Loads the YOLOv8m (You Only Look Once) model, optimized for the iPhone's NPU.
- **ObjectTracker**: A custom-built tracking layer that assigns persistent IDs to detected objects and calculates velocity vectors.
- **SpeechEngine**: A priority-based auditory interface that "triages" announcements so the user isn't overwhelmed.

## 3. Engineering Innovations
- **Time to Impact**: Instead of simple distance, we use physics-based prediction ($T = D/S$) to warn of approaching hazards.
- **Object Prediction**: We implemented a tracking layer that predicts object movement even when the camera lens is momentarily blocked or blurred.
- **Intelligent Path Guidance**: The app doesn't just list objects; it analyzes the gaps between obstacles and provides verbal cues like "Path clear to your left," allowing for smoother navigation.
- **Lens Health Monitoring**: A safety-critical module that performs a 5-point brightness check on the camera feed to warn the user of obstructions.

## 4. Implementation Log
- **Phase 1 (Spring 2025)**: Initial research into YOLO models and CoreML conversion.
- **Phase 2 (Winter 2025)**: Integration of ARKit for LiDAR depth mapping. Transitioned from standard bounding boxes to 3D spatial coordinates.
- **Phase 3 (Spring 2026)**: Focus on safety. Implemented the Ghosting and TTC logic. Added haptic discovery pulses for a "silent" mode.

## 5. Testing & Quality Assurance
We utilized **Unit Testing (XCTest)** to verify our core algorithms:
- **Tracking Accuracy**: Verified that objects maintain IDs across frames.
- **Prediction Logic**: Tested the TTC math with simulated velocities.
- **Sensor Failure**: Verified that the app correctly triggers "Camera Covered" warnings.
