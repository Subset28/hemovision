

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
    @Published var mode: AppMode = .navigation {
        didSet { speechEngine.setMode(mode) }
    }

    let speechEngine = SpeechEngine()

    private(set) var cameraManager: OmniPipeline?
    private(set) var session: OmniSightSession?

    private var cameraManagerSub: AnyCancellable?
    private var isTransitioning = false
    private var pendingScanStart = false

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
        setupCrosswalkSubscription()
    }

    private func setupCrosswalkSubscription() {
        cameraManager?.crosswalkDetector.onSignalChange = { [weak self] signal in
            guard let self else { return }
            switch signal {
            case .walk:     self.speechEngine.announceCrosswalk("Walk signal")
            case .dontWalk: self.speechEngine.announceCrosswalk("Don't walk")
            case .unknown:  break
            }
        }
    }

    private func setupDepthSubscription() {
        cameraManagerSub = cameraManager?.$middleSensorDist
            .receive(on: DispatchQueue.main)
            .sink { [weak self] depth in
                self?.speechEngine.updateLiDARDepth(depth)
            }
    }

    func enableDemoMode() {
        PerformanceMonitor.shared.resetSession()
        PerformanceMonitor.shared.isEnabled = true
        DecisionLog.shared.isEnabled = true
        speechEngine.speakImmediate("Demo mode. Instruments enabled.")
    }

    func setScanning(_ on: Bool) {
        if isTransitioning {
            // Debounce window active — record intent so it fires after window closes
            if on { pendingScanStart = true }
            return
        }
        guard isScanning != on else { return }

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
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in
            guard let self else { return }
            self.isTransitioning = false
            if self.pendingScanStart {
                self.pendingScanStart = false
                self.setScanning(true)
            }
        }
    }
}
