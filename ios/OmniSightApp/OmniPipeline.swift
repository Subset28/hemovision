

import OmniSightKit


import ARKit
import Foundation
import Combine

// Unified ARKit Pipeline
// Handles camera frames for YOLO and LiDAR for walls.
// Avoids AVCaptureSession/ARSession conflicts.

class OmniPipeline: NSObject, ARSessionDelegate, ObservableObject {
    private let scannerSession: OmniSightSession
    let arSession = ARSession()
    
    static let isSupported: Bool = {
        if #available(iOS 14.0, *) {
            return ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth)
        }
        return false
    }()

    @Published var middleSensorDist: Float = 999.0
    @Published var isRunning = false

    init(scannerSession: OmniSightSession) {
        self.scannerSession = scannerSession
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
        scannerSession.ingest(arFrame: frame)
        
        // 2. If LiDAR is available, update the center depth reading
        if OmniPipeline.isSupported, let depthMap = frame.sceneDepth?.depthMap {
            let depth = depthMap.sampleDepth(at: CGPoint(x: 0.5, y: 0.5)) ?? 999.0
            print("LiDAR DEBUG: middle distance is \(depth) meters")
            DispatchQueue.main.async {
                self.middleSensorDist = depth
            }
        }
    }
}
