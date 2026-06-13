

import OmniSightKit


import AVFoundation
import Combine
import Foundation

// OmniSight Speech Engine
// This manages the voice feedback for the objects we find.
// We tried a few different "levels" but settled on: 1=Emergency, 2=Approaching, 3=Nearby

// Configuration moved to functions for better organization.

@MainActor
class SpeechEngine: NSObject, ObservableObject, AVSpeechSynthesizerDelegate {
    @Published private(set) var alertActive: Bool = false

    private let synth = AVSpeechSynthesizer()
    private var frameSub: AnyCancellable?
    private var scanningSession: OmniSightSession?
    private var speakTimer: Timer?
    private var isSpeaking = false
    private var isEnabled = false
    private var mutedUntil: Date?

    @Published var objectCount: Int = 0

    private var lastSpokenAt: [String: Date] = [:]
    private var lastClassAt: [String: Date] = [:]

    private var userInVehicle = false
    private var travelVelocitySamples: [Double] = []

    private var lastLiDARDepth: Float = 0.0

    struct QueueItem {
        var text: String
        var priority: Int
        var addedAt: Date
        var expiresIn: TimeInterval
    }
    private var queue: [QueueItem] = []

    private var lastCollisionAt: Date = .distantPast
    private var lastLiDARAt: Date = .distantPast

    private var framesSeen: [String: Int] = [:]
    
    private var lastLiDARTime: Date = .distantPast

    // These are the only things we want the scanner to actually talk about
    static let allWhitelistedClasses: Set<String> = ["person", "car", "truck", "bus", "bicycle", "motorcycle", "dog", "cat", "chair", "table", "door", "stairs"]

    // Setup
    override init() {
        super.init()
        synth.delegate = self
        let audio = AVAudioSession.sharedInstance()
        do {
            try audio.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
            try audio.setActive(true)
        } catch {
            // TTS will be silent but the app won't crash
        }
    }

    func start(scanning: OmniSightSession?) {
        stop()
        isEnabled = true
        self.scanningSession = scanning

        frameSub = scanning?.$lastPayload
            .receive(on: DispatchQueue.main)
            .sink { [weak self] frame in
                // Only process if the frame isn't nil
                if frame != nil {
                    self?.onFrame(frame!)
                }
            }

        // Check the queue every 0.1s to see if we need to say something new
        speakTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            self?.drainQueue()
        }
    }

    func stop() {
        isEnabled = false
        frameSub?.cancel()
        frameSub = nil
        scanningSession = nil
        speakTimer?.invalidate()
        speakTimer = nil
        synth.stopSpeaking(at: .immediate)
        queue.removeAll()
        framesSeen.removeAll()
        lastSpokenAt.removeAll()
        lastClassAt.removeAll()
        isSpeaking  = false
        alertActive = false
    }

    private func onFrame(_ frame: FramePayload) {
        if !isEnabled { return }
        if let mute = mutedUntil, Date() < mute { return }

        var fastCheck:  [DetectedObjectDTO] = []
        var confirmed:  [DetectedObjectDTO] = []

        for obj in frame.objects {
            // Debug log for active scanning
            print("DEBUG: Just saw a \(obj.objectClass) at \(obj.distanceM) meters")
            
            let maxRange = getMaxRange(for: obj.objectClass)
            if maxRange == nil { continue }               // not whitelisted
            if obj.distanceM > maxRange! { continue }     // too far away
            if obj.confidence < getMinConfidence(for: obj.objectClass) { continue }

            let seen = (framesSeen[obj.objectId] ?? 0) + 1
            framesSeen[obj.objectId] = seen

            // Multi-frame confirmation to prevent false positives
            if seen >= 2 { fastCheck.append(obj) }
            if seen >= 3 { confirmed.append(obj) }
        }

        // Automated Travel Mode
        // Determines if the user is in a vehicle based on object velocity
        let highSpeedApproachers = confirmed.filter { $0.velocityMps < -4.0 }
        if highSpeedApproachers.count >= 2 {
            travelVelocitySamples.append(1.0)
        } else {
            travelVelocitySamples.append(0.0)
        }
        if travelVelocitySamples.count > 30 { travelVelocitySamples.removeFirst() }
        
        let travelScore = travelVelocitySamples.reduce(0, +) / Double(travelVelocitySamples.count)
        let newTraveling = travelScore > 0.5
        if newTraveling != userInVehicle {
            userInVehicle = newTraveling
            if userInVehicle {
                HapticManager.shared.warningVibration()
                addToQueue("Travel mode active", priority: 100, expiresIn: 2.0)
            } else {
                addToQueue("Walking mode active", priority: 100, expiresIn: 2.0)
            }
        }

        // Cleanup old IDs
        let liveIds = Set(frame.objects.map { $0.objectId })
        var updatedSeen: [String: Int] = [:]
        for (id, count) in framesSeen {
            if liveIds.contains(id) {
                updatedSeen[id] = count
            }
        }
        framesSeen = updatedSeen
        objectCount = confirmed.count

        let now = Date()

        // Emergency Warnings
        var closestDanger: DetectedObjectDTO? = nil
        let interiorLimit = userInVehicle ? 1.5 : 1.2 
        
        for obj in fastCheck {
            let isDirectlyAhead = abs(obj.panValue) < 0.45
            if obj.distanceM <= interiorLimit && isDirectlyAhead && obj.velocityMps < -0.3 {
                if closestDanger == nil || obj.distanceM < closestDanger!.distanceM {
                    closestDanger = obj
                }
            }
        }

        if let danger = closestDanger {
            alertActive = true
            HapticManager.shared.warningVibration()
            if now.timeIntervalSince(lastCollisionAt) > 3.0 {
                lastCollisionAt = now
                let text = "Warning! \(SpeechEngine.mapToSpokenName(danger.objectClass)), \(distText(danger.distanceM))!"
                emergencySpeak(text)   
            }
        } else {
            alertActive = false
        }

        // Objects Approaching
        var closestApproaching: DetectedObjectDTO? = nil
        for obj in confirmed {
            let isApproaching = obj.velocityMps < -0.40
            if isApproaching {
                if closestApproaching == nil || obj.distanceM < closestApproaching!.distanceM {
                    closestApproaching = obj
                }
            }
        }

        if let obj = closestApproaching {
            let cls = obj.objectClass.lowercased()
            let timeSinceObject = now.timeIntervalSince(lastSpokenAt[obj.objectId] ?? .distantPast)
            let timeSinceClass  = now.timeIntervalSince(lastClassAt[cls] ?? .distantPast)

            if timeSinceObject >= 5 && timeSinceClass >= 5 {
                let text = "\(SpeechEngine.mapToSpokenName(obj.objectClass)), \(directionText(obj.panValue)), \(distText(obj.distanceM)), approaching"
                addToQueue(text, priority: 80, expiresIn: 1.2)
                lastSpokenAt[obj.objectId] = now
                lastClassAt[cls] = now
            }
        }

        // Nearby Static Objects
        // Don't interrupt high-priority warnings
        for item in queue {
            if item.priority >= 80 { return }
        }

        let verbosity = UserDefaults.standard.string(forKey: "verbosityMode") ?? "normal"

        // Closest static object
        var closestNearby: DetectedObjectDTO? = nil
        for obj in confirmed {
            let isApproaching = obj.velocityMps < -0.40
            if !isApproaching {
                if closestNearby == nil || obj.distanceM < closestNearby!.distanceM {
                    closestNearby = obj
                }
            }
        }

        if let obj = closestNearby {
            let cls  = obj.objectClass.lowercased()
            let prio = getPriority(for: obj.objectClass)
            if verbosity == "criticalOnly" && prio < 50 { return }

            let timeSinceObject = now.timeIntervalSince(lastSpokenAt[obj.objectId] ?? .distantPast)
            let timeSinceClass  = now.timeIntervalSince(lastClassAt[cls] ?? .distantPast)

            if timeSinceObject >= 30 && timeSinceClass >= 12 {
                let text = "\(SpeechEngine.mapToSpokenName(obj.objectClass)), \(directionText(obj.panValue)), \(distText(obj.distanceM))"
                addToQueue(text, priority: prio, expiresIn: 2.0)
                lastSpokenAt[obj.objectId] = now
                lastClassAt[cls] = now
            }
        }
    }


    private func addToQueue(_ text: String, priority: Int, expiresIn: TimeInterval) {
        for item in queue {
            if item.text == text { return }
        }
        queue.append(QueueItem(text: text, priority: priority, addedAt: Date(), expiresIn: expiresIn))
    }

    private func drainQueue() {
        queue = queue.filter { Date().timeIntervalSince($0.addedAt) < $0.expiresIn }
        if isSpeaking || queue.isEmpty { return }
        queue.sort { $0.priority > $1.priority }
        speakToUser(queue.removeFirst().text)
    }


    private func emergencySpeak(_ text: String) {
        synth.stopSpeaking(at: .immediate)
        isSpeaking = false
        queue.removeAll()
        speakToUser(text)
    }

    private func speakToUser(_ text: String) {
        let utterance       = AVSpeechUtterance(string: text)
        utterance.rate      = 0.52
        utterance.voice     = AVSpeechSynthesisVoice(language: "en-US")
        synth.speak(utterance)
    }


    private func directionText(_ pan: Double) -> String {
        if pan < -0.75 { return "far left" }
        if pan < -0.45 { return "left" }
        if pan < -0.15 { return "slightly left" }
        if pan <= 0.15 { return "straight ahead" }
        if pan <= 0.45 { return "slightly right" }
        if pan <= 0.75 { return "right" }
        return "far right"
    }


    private func distText(_ meters: Double) -> String {
        let useImperial = UserDefaults.standard.bool(forKey: "useImperialUnits")

        if useImperial {
            let feet = max(2, Int((meters * 3.281).rounded()))
            if feet == 1 { return "1 foot" }
            return "\(feet) feet"
        }

        return String(format: "%.1f meters", meters)
    }


    // Priorities based on testing in various environments
    private func getPriority(for label: String) -> Int {
        let name = label.lowercased()
        if ["car", "truck", "bus"].contains(name) { return 75 }
        if ["person", "stairs"].contains(name) { return 70 }
        if ["chair", "table"].contains(name) { return 30 }
        return 10
    }

    private func getMaxRange(for label: String) -> Double? {
        let name = label.lowercased()
        switch name {
        case "person": return 6.0
        case "car", "truck", "bus": return 12.0
        case "chair", "table": return 4.0
        case "stairs": return 6.0
        case "door": return 5.0
        default: return 5.0
        }
    }

    private func getMinConfidence(for label: String) -> Double {
        return ["chair", "table"].contains(label.lowercased()) ? 0.60 : 0.50
    }


    func speechSynthesizer(_ s: AVSpeechSynthesizer, didStart _: AVSpeechUtterance)  { isSpeaking = true  }
    func speechSynthesizer(_ s: AVSpeechSynthesizer, didFinish _: AVSpeechUtterance) { isSpeaking = false }
    func speechSynthesizer(_ s: AVSpeechSynthesizer, didCancel _: AVSpeechUtterance) { isSpeaking = false }


    func speakImmediate(_ text: String) {
        synth.stopSpeaking(at: .immediate)
        queue.removeAll()
        isSpeaking = false
        speakToUser(text)
    }

    func muteFor(seconds: TimeInterval) {
        mutedUntil = Date().addingTimeInterval(seconds)
        synth.stopSpeaking(at: .immediate)
        queue.removeAll()
        isSpeaking = false
    }

    func setScanningSpeechEnabled(_ on: Bool) { isEnabled = on }
    func announceSystemMessageOnce(key: String, message: String) { speakImmediate(message) }

    // LiDAR logic
    func updateLiDARDepth(_ depthMeters: Float) {
        if !isEnabled { return }
        if let mute = mutedUntil, Date() < mute { return }
        
        let now = Date()
        let dt = now.timeIntervalSince(lastLiDARTime)
        let vel = (depthMeters - lastLiDARDepth) / Float(max(0.01, dt))
        
        lastLiDARDepth = depthMeters
        lastLiDARTime  = now

        // Skip if the optical system already labeled this spot
        let recentlySeenObjects = scanningSession?.lastPayload?.objects ?? []
        let alreadyIdentified = recentlySeenObjects.contains { obj in
            let distDiff = abs(Double(depthMeters) - obj.distanceM)
            let isAhead = abs(obj.panValue) < 0.40
            return distDiff < 0.40 && isAhead && obj.confidence > 0.40
        }
        
        if alreadyIdentified { return }

        // Collision logic
        let minThreshold: Float = userInVehicle ? 1.5 : 1.2
        if depthMeters >= minThreshold { return }
        if userInVehicle && vel > -0.2 { return } 
        
        if now.timeIntervalSince(lastLiDARAt) < 2.5 { return }  // shorter cooldown

        lastLiDARAt = Date()
        alertActive = true
        HapticManager.shared.warningVibration()

        let dist = distText(Double(depthMeters))
        let text = "Obstacle ahead, \(dist)"

        if depthMeters < 0.90 {
            emergencySpeak(text) 
        } else {
            addToQueue(text, priority: 99, expiresIn: 1.5) 
        }
    }


    private static func mapToSpokenName(_ raw: String) -> String {
        return raw.replacingOccurrences(of: "_", with: " ").capitalized
    }
}
