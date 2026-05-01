// OmniSight - Visual Navigation System
// Personal Project - Source Code


import OmniSightKit


import Foundation
import SwiftUI
import ARKit
import Combine
import CoreLocation

enum AccessibilityMode: String, CaseIterable {
    case blind = "Blind"
    case deaf = "Deaf"
    case both = "Both"
}

// AppStateManager
// Central controller for the app. 
// Uses unified ARKit cameraManager to prevent camera freezes.

class AppStateManager: ObservableObject {
    static let shared = AppStateManager()

    @Published var isScanning     = false
    @Published var modelAvailable = false
    
    // Pro Features State
    @Published var mode: AccessibilityMode = .blind
    @Published var currentRoom: String = ""
    @Published var peopleInFrame: Int = 0
    @Published var lastCrowdWarning: Date = .distantPast
    @Published var lastSurfaceWarning: Date = .distantPast
    @Published var detectedSign: String = ""
    
    // SOS State
    @Published var isSOSActive = false
    @Published var sosCountdown = 5
    @Published var lastLocation: String = "Unknown Location"
    private var sosTimer: Timer?
    private let locationManager = CLLocationManager()

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
        
        // Load saved mode if exists
        if let savedMode = UserDefaults.standard.string(forKey: "omnisight_mode"),
           let mode = AccessibilityMode(rawValue: savedMode) {
            self.mode = mode
        }
        
        setupLocation()
    }
    
    private func setupLocation() {
        locationManager.requestWhenInUseAuthorization()
        locationManager.desiredAccuracy = kCLLocationAccuracyBest
        locationManager.startUpdatingLocation()
    }
    
    func triggerSOS() {
        if isSOSActive { return }
        isSOSActive = true
        sosCountdown = 5
        HapticManager.shared.playEmergencyBuzz()
        
        // Get current coordinates
        if let loc = locationManager.location {
            lastLocation = "\(String(format: "%.5f", loc.coordinate.latitude)), \(String(format: "%.5f", loc.coordinate.longitude))"
        }
        
        sosTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] timer in
            guard let self = self else { return }
            if self.sosCountdown > 1 {
                self.sosCountdown -= 1
                self.speechEngine.speakImmediate("\(self.sosCountdown)")
            } else {
                self.sosCountdown = 0
                timer.invalidate()
                self.executeSOS()
            }
        }
    }
    
    func cancelSOS() {
        isSOSActive = false
        sosTimer?.invalidate()
        sosTimer = nil
        speechEngine.speakImmediate("SOS Cancelled")
    }
    
    private func executeSOS() {
        let message = "EMERGENCY: I need help. My current location is \(lastLocation). Sent via OmniSight."
        speechEngine.speakImmediate("Emergency mode. Your location is \(lastLocation). Sending message.")
        
        // Open SMS URL Scheme
        if let url = URL(string: "sms:911&body=\(message.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "")") {
            UIApplication.shared.open(url)
        }
    }
        
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
