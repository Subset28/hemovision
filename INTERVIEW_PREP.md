# TSA Interview Prep: Coding Explanation (X3 Multiplier)

The judges will ask you to explain a random section of your code. If you can explain the **math** and the **logic** clearly, you will win this section. Here are the most likely "Complex" areas they will ask about:

## 1. How does the "Safety Check" work?
**Location**: `SpeechEngine.swift`
**Explanation**: 
"We check two things: **Distance** and **Time**. We warn the user if an object is less than 1 meter away, OR if it's moving so fast that it will hit them in less than 1.8 seconds. We calculate the 'Time to Impact' by dividing the **Distance** by the **Speed**. This is a simple physics formula that provides a high level of safety."

## 2. What is "Prediction" (Ghosting)?
**Location**: `ObjectTracker.swift`
**Explanation**:
"If the camera is momentarily blocked, most apps would 'forget' the object. Our app enters a prediction mode. We keep the object in memory and use its last known **Speed** and **Time** to predict where it *should* be ($D = S \times T$). This ensures the user is still safe even if the object is hidden for a second."

## 3. How does "Intelligent Path Guidance" work?
**Location**: `SpeechEngine.swift` (findClearPath)
**Explanation**:
"Most apps for the blind only tell you what is *in your way*. OmniSight does the opposite—it looks for the **gaps**. We analyze the horizontal space (the 'pan' values) of all detected objects. If we find a gap wider than 70cm (roughly shoulder-width), we guide the user toward it by saying 'Path clear ahead' or 'Path clear to your right.' This is a major leap in true autonomous navigation."

## 4. How do you detect if the camera is blocked?
**Location**: `OnDeviceVisionEngine.swift` (checkCameraHealth)
**Explanation**:
"We check the brightness of the camera feed in 5 key spots (the center and the 4 corners). If the average brightness is too low, it means the lens is likely covered by a finger or the user's clothes. The app then gives a verbal warning so the user knows the system is obstructed."

## 4. Why use YOLOv8 instead of Apple's built-in Vision?
**Explanation**:
"We chose YOLOv8 because it allows for custom model optimization. We used the 'Medium' version (yolov8m) and converted it to CoreML to leverage the **Apple Neural Engine**. This allows us to run complex detections in under 20ms without draining the battery or overheating the phone, which is vital for an app that needs to run for hours of walking."

## 5. How does the Radar work?
**Location**: `RadarView.swift`
**Explanation**:
"The Radar takes the 3D spatial coordinates (X and Z) provided by ARKit and maps them onto a 2D circle. We use a coordinate transform to place the user at the center and rotate the detections based on the phone's heading, giving a 'tactical' top-down view for visual assistants."
