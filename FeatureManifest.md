# OmniSight: Complete Feature Manifest
**The "Feature Bible" for TSA 2026**

---

### 1. AI Object Recognition (YOLOv8m)
*   **The Feature**: Identifies 12 specific classes of objects in the user’s path.
*   **How it Works**: Uses a YOLOv8 (You Only Look Once) neural network optimized for iOS. It processes camera frames at high speed, identifies bounding boxes, and calculates the distance to the object by cross-referencing its size and position with the LiDAR depth map.
*   **User Value**: Provides semantic context (e.g., "Person ahead," "Car to the left").

### 2. Spatial LiDAR Radar
*   **The Feature**: A constant depth-sensing "bubble" that detects obstacles AI might miss.
*   **How it Works**: Continuously samples the LiDAR point cloud at the center of the frame. Unlike the camera, LiDAR doesn't care about lighting or texture—it can detect clear glass doors, black walls, or thin poles.
*   **User Value**: Prevents collisions with unlabeled or "invisible" obstacles.

### 3. Surface & Drop-off Detection (Stair Warning)
*   **The Feature**: Alerts the user to stairs, curbs, or sudden floor changes.
*   **How it Works**: The system samples depth at the ground level (0.5, 0.85 in normalized coordinates). If the distance to the ground suddenly increases by more than 1.5 meters compared to the center depth, the system flags a "Drop-off."
*   **User Value**: Critical safety for navigating stairs or transit platforms.

### 4. Scene Classification (Contextual Intelligence)
*   **The Feature**: Tells the user what kind of room they are in.
*   **How it Works**: Uses a global scene classifier to analyze the entire frame (not just individual objects). Every 10 seconds, it updates the "Current Room" state (e.g., "Kitchen," "Office," "Street").
*   **User Value**: Provides high-level orientation and peace of mind.

### 5. Dynamic Speech Queue
*   **The Feature**: Manages multiple simultaneous alerts without "talking over" itself.
*   **How it Works**: A custom priority-based scheduler. 
    *   **Priority 1 (Emergency)**: Collision alerts immediately stop all other speech.
    *   **Priority 5-10 (Awareness)**: Furniture or scene info is queued and spoken only when the air is clear. 
*   **User Value**: Prevents information overload.

### 6. Physical UI (Multimodal Haptics)
*   **The Feature**: Communicates distance and danger through touch.
*   **How it Works**: Maps object proximity to Taptic Engine intensities. 
    *   **<1m**: Continuous urgent vibration.
    *   **1m-3m**: Intermittent pulses.
    *   **Surface Change**: A distinct "warning" vibration pattern.
*   **User Value**: Works in loud environments where audio feedback is useless.

### 7. SOS Gesture Trigger
*   **The Feature**: A fast, screen-free way to call for help.
*   **How it Works**: Monitors for a "Triple Tap" gesture on the device. Once triggered, it starts a 5-second audible countdown, grabs the precise GPS coordinates, and opens a pre-filled SMS to 911 or an emergency contact.
*   **User Value**: Ultimate safety fallback for dangerous situations.

### 8. Crowd Awareness Alert
*   **The Feature**: Warns the user when entering a high-traffic area.
*   **How it Works**: Continuously counts the number of "Person" detections in the frame. If the count exceeds 4, the system triggers a "Busy area ahead" warning.
*   **User Value**: Helps the user navigate through social anxiety or high-density transit hubs.

### 9. Automatic Travel Mode
*   **The Feature**: Switches behavior when the user is in a vehicle.
*   **How it Works**: Monitors the relative velocity of static objects (like chairs or tables). If the background environment is moving >4 m/s relative to the user, the app automatically switches to "Travel Mode," increasing the distance thresholds for warnings.
*   **User Value**: Prevents the app from constantly shouting about objects when the user is just sitting on a bus or train.

---
*OmniSight: Total Spatial Awareness.*
