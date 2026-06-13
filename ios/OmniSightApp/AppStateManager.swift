

import OmniSightKit


import AVFoundation
import Foundation
import SwiftUI
import ARKit
import Combine

// AppStateManager
// Central controller for the app.
// Uses unified ARKit cameraManager to prevent camera freezes.

@MainActor
class AppStateManager: ObservableObject {
    static let shared = AppStateManager()

    @Published var isScanning = false
    @Published var engineAvailable = false
    @Published var cameraPermissionDenied = false

    let speechEngine = SpeechEngine()

    private(set) var cameraManager: OmniPipeline?
    private(set) var session: OmniSightSession?

    private var cameraManagerSub: AnyCancellable?
    private var isTransitioning = false

    private init() {
        guard let detector = try? CoreMLDetector(modelResourceName: "ScanningData", bundle: .main) else {
            return
        }
        var config = detector.config
        config.allowedClasses = SpeechEngine.allWhitelistedClasses

        let engine = OpticalProcessor(detector: detector)
        engine.config = config

        session = OmniSightSession(engine: engine)
        engineAvailable = true

        cameraManager = OmniPipeline(scannerSession: session!)

        speechEngine.start(scanning: session!)
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

        if on {
            let status = AVCaptureDevice.authorizationStatus(for: .video)
            switch status {
            case .denied, .restricted:
                cameraPermissionDenied = true
                return
            case .notDetermined:
                AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                    Task { @MainActor [weak self] in
                        if granted {
                            self?.setScanning(true)
                        } else {
                            self?.cameraPermissionDenied = true
                        }
                    }
                }
                return
            default:
                cameraPermissionDenied = false
            }
        }

        isTransitioning = true
        isScanning = on

        if on {
            cameraManager?.start()
            speechEngine.start(scanning: session)
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
