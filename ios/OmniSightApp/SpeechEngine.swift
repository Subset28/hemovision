// OmniSight - Visual Navigation System
// Personal Project - Source Code

import OmniSightKit
import AVFoundation
import Combine
import Foundation
import Vision

// OmniSight Speech Engine
// This module manages text-to-speech feedback for detected objects.
class SpeechEngine: NSObject, ObservableObject, AVSpeechSynthesizerDelegate {

    static let shared = SpeechEngine()

    @Published private(set) var alertActive: Bool = false
    @Published var objectCount: Int = 0

    private let synth     = AVSpeechSynthesizer()
    private var frameSub:   AnyCancellable?
    private var visionSession: OmniSightSession?
    private var speakTimer: Timer?
    private var isSpeaking  = false
    private var isEnabled   = false
    private var mutedUntil: Date?

    private var lastSpokenAt: [String: Date] = [:]
    private var lastClassAt:  [String: Date] = [:]
    private var lastLiDARDepth: Float = 0.0

    struct QueueItem {
        var text: String
        var priority: Int
        var addedAt: Date
        var expiresIn: TimeInterval
    }
    private var queue: [QueueItem] = []

    private var lastCollisionAt: Date = .distantPast
    private var lastLiDARAt:     Date = .distantPast
    private var framesSeen: [String: Int] = [:]
    private var lastLiDARTime:  Date  = .distantPast

    static let allWhitelistedClasses: Set<String> = ["person", "car", "truck", "bus", "bicycle", "motorcycle", "dog", "cat", "chair", "table", "door", "stairs"]

    override init() {
        super.init()
        synth.delegate = self
        let audio = AVAudioSession.sharedInstance()
        try! audio.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
        try! audio.setActive(true)
    }

    func start(vision: OmniSightSession?) {
        stop()
        isEnabled = true
        self.visionSession = vision

        frameSub = vision?.$lastPayload
            .receive(on: DispatchQueue.main)
            .sink { [weak self] frame in
                if let frame = frame {
                    self?.onFrame(frame)
                }
            }

        speakTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            self?.drainQueue()
        }
    }

    func stop() {
        isEnabled = false
        frameSub?.cancel()
        frameSub = nil
        visionSession = nil
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
            let maxRange = getMaxRange(for: obj.objectClass)
            if maxRange == nil { continue }
            if obj.distanceM > maxRange! { continue }
            if obj.confidence < getMinConfidence(for: obj.objectClass) { continue }

            let seen = (framesSeen[obj.objectId] ?? 0) + 1
            framesSeen[obj.objectId] = seen

            if seen >= 2 { fastCheck.append(obj) }
            if seen >= 3 { confirmed.append(obj) }
        }

        let liveIds = Set(frame.objects.map { $0.objectId })
        var updatedSeen: [String: Int] = [:]
        for (id, count) in framesSeen {
            if liveIds.contains(id) {
                updatedSeen[id] = count
            }
        }
        framesSeen = updatedSeen
        objectCount = confirmed.count
        
        if let topObj = confirmed.sorted(by: { $0.distanceM < $1.distanceM }).first {
            AppStateManager.shared.lastDetection = "\(topObj.objectClass.capitalized) at \(String(format: "%.1f", topObj.distanceM))m"
        }
        
        let peopleCount = confirmed.filter { $0.objectClass == "person" }.count
        AppStateManager.shared.peopleInFrame = peopleCount
        if peopleCount >= 4 {
            let now = Date()
            if now.timeIntervalSince(AppStateManager.shared.lastCrowdWarning) > 15.0 {
                AppStateManager.shared.lastCrowdWarning = now
                HapticManager.shared.warningVibration()
                addToQueue("Busy area ahead, proceed with caution", priority: 10, expiresIn: 5.0)
            }
        }
        
        let now = Date()
        var closestDanger: DetectedObjectDTO? = nil
        for obj in fastCheck {
            let isDirectlyAhead = abs(obj.panValue) < 0.45
            if obj.distanceM <= 1.0 && isDirectlyAhead && obj.velocityMps < -0.3 {
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

        var closestApproaching: DetectedObjectDTO? = nil
        for obj in confirmed {
            if obj.velocityMps < -0.40 {
                if closestApproaching == nil || obj.distanceM < closestApproaching!.distanceM {
                    closestApproaching = obj
                }
            }
        }

        if let obj = closestApproaching {
            let cls = obj.objectClass.lowercased()
            if now.timeIntervalSince(lastSpokenAt[obj.objectId] ?? .distantPast) >= 5 && now.timeIntervalSince(lastClassAt[cls] ?? .distantPast) >= 5 {
                let text = "\(SpeechEngine.mapToSpokenName(obj.objectClass)), \(directionText(obj.panValue)), \(distText(obj.distanceM)), approaching"
                addToQueue(text, priority: 80, expiresIn: 1.2)
                lastSpokenAt[obj.objectId] = now
                lastClassAt[cls] = now
            }
        }

        var closestNearby: DetectedObjectDTO? = nil
        for obj in confirmed {
            if obj.velocityMps >= -0.40 {
                if closestNearby == nil || obj.distanceM < closestNearby!.distanceM {
                    closestNearby = obj
                }
            }
        }

        if let obj = closestNearby {
            let cls  = obj.objectClass.lowercased()
            let prio = getPriority(for: obj.objectClass)
            if now.timeIntervalSince(lastSpokenAt[obj.objectId] ?? .distantPast) >= 30 && now.timeIntervalSince(lastClassAt[cls] ?? .distantPast) >= 12 {
                let text = "\(SpeechEngine.mapToSpokenName(obj.objectClass)), \(directionText(obj.panValue)), \(distText(obj.distanceM))"
                addToQueue(text, priority: prio, expiresIn: 2.0)
                lastSpokenAt[obj.objectId] = now
                lastClassAt[cls] = now
            }
        }
    }

    func addToQueue(_ text: String, priority: Int, expiresIn: TimeInterval) {
        for item in queue {
            if item.text == text { return }
        }
        AppStateManager.shared.lastDetection = text
        queue.append(QueueItem(text: text, priority: priority, addedAt: Date(), expiresIn: expiresIn))
    }

    private func drainQueue() {
        queue = queue.filter { Date().timeIntervalSince($0.addedAt) < $0.expiresIn }
        if isSpeaking || queue.isEmpty { return }
        queue.sort { $0.priority > $1.priority }
        let nextItem = queue.removeFirst()
        speakToUser(nextItem.text)
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
        if pan < -0.65 { return "hard left"     }
        if pan < -0.35 { return "left"           }
        if pan < -0.12 { return "diagonal left"  }
        if pan <= 0.12 { return "ahead"          }
        if pan <= 0.35 { return "diagonal right" }
        if pan <= 0.65 { return "right"          }
        return "hard right"
    }

    private func distText(_ meters: Double) -> String {
        let useImperial = UserDefaults.standard.bool(forKey: "useImperialUnits")
        if useImperial {
            let feet = max(2, Int((meters * 3.281).rounded()))
            return feet == 1 ? "1 foot" : "\(feet) feet"
        }
        if meters < 2.0 {
            let rounded = max(0.5, (meters * 2).rounded() / 2)
            return String(format: "%.1f meters", rounded)
        }
        return "\(Int(meters.rounded())) meters"
    }

    private func getPriority(for label: String) -> Int {
        let name = label.lowercased()
        if name == "car" || name == "truck" || name == "bus" { return 1 }
        if name == "person" || name == "stairs" { return 1 }
        if name == "dog" || name == "cat" { return 3 }
        if name == "chair" || name == "table" { return 5 }
        return 10
    }

    private func getMaxRange(for label: String) -> Double? {
        let name = label.lowercased()
        switch name {
        case "person": return 6.0
        case "car", "truck", "bus": return 12.0
        case "bicycle", "motorcycle": return 8.0
        case "dog", "cat": return 5.0
        case "chair", "table": return 4.0
        case "door": return 5.0
        case "stairs": return 6.0
        default: return nil
        }
    }

    private func getMinConfidence(for label: String) -> Double {
        let name = label.lowercased()
        if name == "bicycle" || name == "motorcycle" { return 0.45 }
        if name == "chair" || name == "table" { return 0.60 }
        return 0.50
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

    func updateLiDARDepth(_ depthMeters: Float) {
        if !isEnabled { return }
        if let mute = mutedUntil, Date() < mute { return }
        
        let now = Date()
        let dt = now.timeIntervalSince(lastLiDARTime)
        let vel = (depthMeters - lastLiDARDepth) / Float(max(0.01, dt))
        
        lastLiDARDepth = depthMeters
        lastLiDARTime  = now

        let recentlySeenObjects = visionSession?.lastPayload?.objects ?? []
        let alreadyIdentified = recentlySeenObjects.contains { obj in
            let distDiff = abs(Double(depthMeters) - obj.distanceM)
            let isAhead = abs(obj.panValue) < 0.40
            return distDiff < 0.40 && isAhead && obj.confidence > 0.40
        }
        
        if alreadyIdentified { return }

        let minThreshold: Float = 0.75
        if depthMeters >= minThreshold { return }
        if now.timeIntervalSince(lastLiDARAt) < 2.5 { return }

        lastLiDARAt = Date()
        alertActive = true
        HapticManager.shared.warningVibration()

        let dist = distText(Double(depthMeters))
        let text = "Obstacle ahead, \(dist)"

        if depthMeters < 0.60 {
            emergencySpeak(text) 
        } else {
            addToQueue(text, priority: 95, expiresIn: 1.5) 
        }
    }

    private static func mapToSpokenName(_ raw: String) -> String {
        let t = raw.lowercased()
        switch t {
        case "person": return "Person"
        case "car": return "Car"
        case "truck": return "Truck"
        case "bus": return "Bus"
        case "bicycle": return "Bike"
        case "motorcycle": return "Motorcycle"
        case "dog": return "Dog"
        case "cat": return "Cat"
        case "chair": return "Chair"
        case "table": return "Table"
        case "door": return "Door"
        case "stairs": return "Stairs"
        default: return raw.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }
}
