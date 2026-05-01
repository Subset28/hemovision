// OmniSight - Visual Navigation System
// Personal Project - Source Code


import OmniSightKit


import Foundation
import SwiftUI
import ARKit
import Combine

// AppStateManager
// Central controller for the app. 
// Uses unified ARKit cameraManager to prevent camera freezes.

class AppStateManager: ObservableObject {
    static let shared = AppStateManager()

    @Published var isScanning     = false
    @Published var modelAvailable = false

    let speechEngine = SpeechEngine()
    
    // Unified cameraManager for both Video and LiDAR
    private(set) var cameraManager: OmniPipeline?
    private(set) var session:  OmniSightSession?

    private var cameraManagerSub: AnyCancellable?
    private var isTransitioning = false

    private init() {
        // Load the YOLOv8 model
        // If this fails, the app is broken anyway.
        let detector = try! CoreMLDetector(modelResourceName: "yolov8m-oiv7", bundle: .main)
        var config = detector.config
        config.allowedClasses = SpeechEngine.allWhitelistedClasses
        
        let engine = OnDeviceVisionEngine(detector: detector)
        engine.config = config // Apply the filtered config
        
        session        = OmniSightSession(engine: engine)
        modelAvailable = true
        
        // Initialize the unified cameraManager
        // We force unwrap session because we know it exists here
        cameraManager = OmniPipeline(vision: session!)
        
        speechEngine.start(vision: session!)
        setupDepthSubscription()
    }

    private func setupDepthSubscription() {
        cameraManagerSub = cameraManager?.$middleSensorDist
            .receive(on: DispatchQueue.main)
            .sink { [weak self] depth in
                self?.speechEngine.updateLiDARDepth(depth)
            }
    }

    func setScanning(_ on: Bool) {
        guard !isTransitioning, isScanning != on else { return }
        isTransitioning = true
        isScanning = on

        if on {
            cameraManager?.start()
            speechEngine.start(vision: session)
            speechEngine.speakImmediate("Scanning started")
        } else {
            cameraManager?.stop()
            speechEngine.stop()
            session?.clearPayload()
            speechEngine.speakImmediate("Scanning stopped")
        }

        // 1.5s debounce to protect the camera session
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
            self.isTransitioning = false
        }
    }
}
