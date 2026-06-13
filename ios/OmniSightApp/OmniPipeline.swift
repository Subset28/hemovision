

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
    private var lastIngestTime: TimeInterval = 0
    private let ingestQueue = DispatchQueue(label: "com.orbconcepts.omnisight.ingest", qos: .userInitiated)
    private var isIngesting = false
    
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
        
        config.isLightEstimationEnabled = false
        
        arSession.run(config, options: [.resetTracking, .removeExistingAnchors])
        isRunning = true
    }

    func stop() {
        arSession.pause()
        isRunning = false
        middleSensorDist = 999.0
    }

    // ARSessionDelegate
    
    // Called ~60fps on ARKit's internal thread. Must return fast or frames pile up.
    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        // LiDAR depth -- cheap sample, fine inline
        if OmniPipeline.isSupported, let depthMap = frame.sceneDepth?.depthMap {
            let depth = depthMap.sampleDepth(at: CGPoint(x: 0.5, y: 0.5)) ?? 999.0
            DispatchQueue.main.async { self.middleSensorDist = depth }
        }

        // ML ingest -- throttled to ~15fps, dispatched off ARKit's thread so frames don't pile up
        let now = frame.timestamp
        guard now - lastIngestTime >= 0.067, !isIngesting else { return }
        lastIngestTime = now
        isIngesting = true
        ingestQueue.async { [weak self, frame] in
            self?.scannerSession.ingest(arFrame: frame)
            self?.isIngesting = false
        }
    }
}
