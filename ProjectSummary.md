# OmniSight: Project Executive Summary
**TSA Competition 2026**

## 1. The Vision: Why OmniSight?
Most assistive technology for the visually impaired hasn't changed in decades. White canes and guide dogs are reactive—they tell you when you've *already* hit something. We chose this idea because we wanted to create a **proactive** system. By leveraging the same LiDAR and Computer Vision used in autonomous vehicles, we can give users a "Digital Twin" of the world, allowing them to perceive their environment before they ever touch it.

## 2. How It Works (High Level)
OmniSight operates as a **Real-Time Spatial Pipeline**:
*   **The Intake**: The system captures a constant stream of 3D data via LiDAR and high-resolution video.
*   **The Intelligence**: A custom-trained Neural Network (YOLOv8) identifies critical objects (doors, stairs, people) while ARKit maps the floor geometry.
*   **The Translation**: The app converts this complex data into a "Physical UI"—a combination of spatial audio and distinct haptic patterns that the user feels through the device.

## 3. The Creativity: Beyond the Screen
Our biggest creative breakthrough was moving away from a screen-based interface. 
*   **The Physical UI**: We treated vibrations as a language. A high-frequency buzz means "immediate danger," while a subtle tap indicates a "nearby object." 
*   **Spatial Radar**: We didn't just use cameras; we used LiDAR to detect "invisible" obstacles like glass doors and sudden drop-offs (stairs) that traditional computer vision often misses.

## 4. Biggest Challenges & Technical Grit
*   **The Latency War**: In navigation, 500ms is the difference between stopping and tripping. We spent the majority of our development time optimizing the pipeline for **sub-100ms latency**, ensuring the feedback feels "instant."
*   **Hardware Hardening**: Running heavy AI models on a mobile device is a thermal and memory nightmare. We had to implement custom memory management (`autoreleasepools`) and hardware-specific routing to keep the system stable during prolonged use.
*   **Signal vs. Noise**: A major problem was "information overload." We had to write complex logic to prioritize which sounds and vibrations are most important, ensuring the user only hears what they *need* to know.

## 5. The Workflow: Native & On-Device
*   **Native-First Stack**: We used Apple’s native frameworks (Swift, ARKit, CoreML) to ensure we had direct access to the hardware for maximum speed.
*   **Privacy by Design**: Every calculation happens on-device. No data ever leaves the phone, ensuring total privacy for the user in their most personal spaces.
*   **Rapid Pruning**: We followed an iterative workflow where we aggressively "pruned" features that were distracting or unstable (like Speech-to-Text), focusing instead on a rock-solid, high-performance core for the competition.
