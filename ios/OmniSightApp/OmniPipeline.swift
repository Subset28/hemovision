// OmniSight - Visual Navigation System
// Personal Project - Source Code

import OmniSightKit
import ARKit
import Foundation
import Combine
import Vision

// Unified ARKit Pipeline
// Handles camera frames for YOLO and LiDAR for walls.
class OmniPipeline: NSObject, ARSessionDelegate, ObservableObject {
    private let vision: OmniSightSession
    
    // The single AR session that drives everything
    let arSession = ARSession()
    
    // True if this device has a LiDAR scanner
    static let isSupported: Bool = {
        if #available(iOS 14.0, *) {
            return ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth)
        }
        return false
    }()

    // Published depth for the speech engine to watch
    @Published var middleSensorDist: Float = 999.0
    @Published var isRunning = false
    
    private var lastSurfaceTime: Date = .distantPast
    private var lastSceneClassTime: Date = .distantPast
    private var lastSceneResult: String = ""
    
    // Vision threading protection
    private let visionQueue = DispatchQueue(label: "com.omnisight.vision", qos: .userInitiated)
    private var isVisionBusy = false

    init(vision: OmniSightSession) {
        self.vision = vision
        super.init()
        arSession.delegate = self
    }

    func start() {
        let config = ARWorldTrackingConfiguration()
        
        // Enable LiDAR depth if the device supports it
        if OmniPipeline.isSupported {
            config.frameSemantics = .sceneDepth
        }
        
        // Smooth out the camera feed for the judges
        config.isLightEstimationEnabled = true
        
        arSession.run(config, options: [.resetTracking, .removeExistingAnchors])
        isRunning = true
    }

    func stop() {
        arSession.pause()
        isRunning = false
        middleSensorDist = 999.0
    }

    // ARSessionDelegate
    
    // This is called every time a new camera frame arrives (~60 fps)
    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        // 1. Feed the camera image to the YOLO engine
        vision.ingest(arFrame: frame)
        
        // 2. If LiDAR is available, update the center depth reading
        if OmniPipeline.isSupported, let depthMap = frame.sceneDepth?.depthMap {
            let centerDepth = depthMap.sampleDepth(at: CGPoint(x: 0.5, y: 0.5)) ?? 999.0
            
            // Feature 5: Surface Change / Stairs Warning
            let groundDepth = depthMap.sampleDepth(at: CGPoint(x: 0.5, y: 0.85)) ?? 999.0
            let now = Date()
            
            // If the ground suddenly "disappears" (drop off)
            if groundDepth > centerDepth + 1.5 && groundDepth < 5.0 {
                if now.timeIntervalSince(lastSurfaceTime) > 3.0 {
                    lastSurfaceTime = now
                    HapticManager.shared.playSurfaceDropoff()
                    AppStateManager.shared.speechEngine.speakImmediate("Step or drop-off detected, slow down")
                }
            }

            DispatchQueue.main.async {
                self.middleSensorDist = centerDepth
            }
        }
        
        // 3. Scene Classification (Feature 2)
        let now = Date()
        if !isVisionBusy && now.timeIntervalSince(lastSceneClassTime) > 10.0 {
            lastSceneClassTime = now
            isVisionBusy = true
            let pixelBuffer = frame.capturedImage
            visionQueue.async { [weak self] in
                self?.classifyScene(pixelBuffer: pixelBuffer)
            }
        }
    }

    private func classifyScene(pixelBuffer: CVPixelBuffer) {
        defer { isVisionBusy = false }
        let request = VNClassifyImageRequest { [weak self] request, error in
            autoreleasepool {
                guard let results = request.results as? [VNClassificationObservation],
                      let topResult = results.first,
                      topResult.confidence > 0.6 else { return }
                
                let scene = topResult.identifier.replacingOccurrences(of: "_", with: " ")
                if scene != self?.lastSceneResult {
                    self?.lastSceneResult = scene
                    DispatchQueue.main.async {
                        AppStateManager.shared.currentRoom = scene
                        AppStateManager.shared.speechEngine.addToQueue("You appear to be in a \(scene)", priority: 50, expiresIn: 10.0)
                    }
                }
            }
        }
        
        let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, options: [:])
        try? handler.perform([request])
    }
}
