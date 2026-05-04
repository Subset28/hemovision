// OmniSight - Visual Navigation System
// Personal Project - Source Code

import OmniSightKit
import AVFoundation
import Combine
import Foundation

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
    private var lastPathAdviceAt: Date = .distantPast

    private var userInVehicle: Bool = false
    private var travelVelocitySamples: [Double] = []

    private var lastLiDARDepth: Float = 0.0
    private var lastLiDARTime:  Date  = .distantPast
    private var lastLiDARAt:     Date = .distantPast
    private var lastCollisionAt: Date = .distantPast
    private var lastLensWarningAt: Date = .distantPast

    struct QueueItem {
        var text: String
        var priority: Int
        var addedAt: Date
        var expiresIn: TimeInterval
    }
    private var queue: [QueueItem] = []
    private var framesSeen: [String: Int] = [:]
    
    static let allWhitelistedClasses: Set<String> = ["person", "car", "truck", "bus", "bicycle", "motorcycle", "dog", "cat", "chair", "table", "door", "stairs"]

    override init() {
        super.init()
        synth.delegate = self
        let audio = AVAudioSession.sharedInstance()
        try? audio.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
        try? audio.setActive(true)
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

        // 1. Camera Health Check
        if let health = frame.camera, let warning = health.lensAnnounce {
            if Date().timeIntervalSince(lastLensWarningAt) > 60.0 {
                lastLensWarningAt = Date()
                speakImmediate(warning)
            }
        }

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

        // 2. Intelligent Path Guidance (Gap Finder)
        if Date().timeIntervalSince(lastPathAdviceAt) > 8.0 {
            if let advice = findClearPath(in: frame.objects) {
                lastPathAdviceAt = Date()
                addToQueue(advice, priority: 60, expiresIn: 2.0)
            }
        }

        // 3. Travel Mode Logic
        let highSpeedApproachers = confirmed.filter { $0.velocityMps < -4.0 }
        travelVelocitySamples.append(highSpeedApproachers.count >= 2 ? 1.0 : 0.0)
        if travelVelocitySamples.count > 30 { travelVelocitySamples.removeFirst() }
        
        let travelScore = travelVelocitySamples.reduce(0, +) / Double(travelVelocitySamples.count)
        if (travelScore > 0.5) != userInVehicle {
            userInVehicle = (travelScore > 0.5)
            let mode = userInVehicle ? "Travel mode active" : "Walking mode active"
            addToQueue(mode, priority: 100, expiresIn: 2.0)
        }

        // Cleanup stale objects
        let liveIds = Set(frame.objects.map { $0.objectId })
        framesSeen = framesSeen.filter { liveIds.contains($0.key) }
        objectCount = confirmed.count

        // 4. Emergency Checks
        var closestDanger: DetectedObjectDTO? = nil
        for obj in fastCheck {
            let isDirectlyAhead = abs(obj.panValue) < 0.45
            let ttc = obj.velocityMps < -0.1 ? (obj.distanceM / abs(obj.velocityMps)) : 99.0
            if isDirectlyAhead && (obj.distanceM < 1.0 || ttc < 1.8) {
                if closestDanger == nil || obj.distanceM < closestDanger!.distanceM {
                    closestDanger = obj
                }
            }
        }

        if let danger = closestDanger {
            alertActive = true
            HapticManager.shared.warningVibration()
            if Date().timeIntervalSince(lastCollisionAt) > 3.0 {
                lastCollisionAt = Date()
                let text = "Warning! \(SpeechEngine.mapToSpokenName(danger.objectClass)), \(distText(danger.distanceM))!"
                emergencySpeak(text)
            }
        } else {
            alertActive = false
        }

        // 5. Normal Announcements (Approaching & Nearby)
        processStandardAnnouncements(confirmed: confirmed)
    }

    private func processStandardAnnouncements(confirmed: [DetectedObjectDTO]) {
        let now = Date()
        let verbosity = UserDefaults.standard.string(forKey: "verbosityMode") ?? "normal"

        for obj in confirmed.sorted(by: { $0.distanceM < $1.distanceM }) {
            let cls = obj.objectClass.lowercased()
            let prio = getPriority(for: obj.objectClass)
            if verbosity == "criticalOnly" && prio < 50 { continue }

            let isApproaching = obj.velocityMps < -0.40
            let timeSinceObject = now.timeIntervalSince(lastSpokenAt[obj.objectId] ?? .distantPast)
            let timeSinceClass  = now.timeIntervalSince(lastClassAt[cls] ?? .distantPast)

            let minObjectCooldown: TimeInterval = isApproaching ? 5.0 : 30.0
            let minClassCooldown: TimeInterval = isApproaching ? 5.0 : 12.0

            if timeSinceObject >= minObjectCooldown && timeSinceClass >= minClassCooldown {
                var text = "\(SpeechEngine.mapToSpokenName(obj.objectClass)), \(directionText(obj.panValue)), \(distText(obj.distanceM))"
                if isApproaching { text += ", approaching" }
                
                addToQueue(text, priority: isApproaching ? 80 : prio, expiresIn: 2.0)
                lastSpokenAt[obj.objectId] = now
                lastClassAt[cls] = now
                break // Only one standard announcement per frame to avoid spam
            }
        }
    }

    private func findClearPath(in objects: [DetectedObjectDTO]) -> String? {
        let obstacles = objects.filter { $0.distanceM < 4.0 }.sorted { $0.panValue < $1.panValue }
        if obstacles.isEmpty { return "Path is completely clear" }
        
        var gaps: [(start: Double, end: Double, size: Double)] = []
        var lastEdge = -1.0
        for obs in obstacles {
            let leftEdge = obs.panValue - 0.25
            if leftEdge > lastEdge {
                gaps.append((lastEdge, leftEdge, leftEdge - lastEdge))
            }
            lastEdge = max(lastEdge, obs.panValue + 0.25)
        }
        if 1.0 > lastEdge { gaps.append((lastEdge, 1.0, 1.0 - lastEdge)) }
        
        if let biggest = gaps.max(by: { $0.size < $1.size }), biggest.size > 0.7 {
            let center = (biggest.start + biggest.end) / 2.0
            if center < -0.4 { return "Path clear to your left" }
            if center > 0.4  { return "Path clear to your right" }
            if abs(center) <= 0.4 { return "Path clear ahead" }
        }
        return nil
    }

    private func addToQueue(_ text: String, priority: Int, expiresIn: TimeInterval) {
        if queue.contains(where: { $0.text == text }) { return }
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
        queue.removeAll()
        isSpeaking = false
        speakToUser(text)
    }

    private func speakToUser(_ text: String) {
        let utterance = AVSpeechUtterance(string: text)
        utterance.rate = 0.52
        utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
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
            return "\(feet) feet"
        }
        return meters < 2.0 ? String(format: "%.1f meters", meters) : "\(Int(meters.rounded())) meters"
    }

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

    func speechSynthesizer(_ s: AVSpeechSynthesizer, didStart _: AVSpeechUtterance) { isSpeaking = true }
    func speechSynthesizer(_ s: AVSpeechSynthesizer, didFinish _: AVSpeechUtterance) { isSpeaking = false }
    func speechSynthesizer(_ s: AVSpeechSynthesizer, didCancel _: AVSpeechUtterance) { isSpeaking = false }

    func speakImmediate(_ text: String) {
        synth.stopSpeaking(at: .immediate)
        queue.removeAll()
        isSpeaking = false
        speakToUser(text)
    }

    private static func mapToSpokenName(_ raw: String) -> String {
        return raw.replacingOccurrences(of: "_", with: " ").capitalized
    }
}
