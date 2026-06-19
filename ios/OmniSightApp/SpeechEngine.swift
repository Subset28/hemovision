

import OmniSightKit

import AVFoundation
import Combine
import Foundation

// SpeechEngine — voice feedback controller for OmniSight.
//
// Improvements over v1:
//   • Uses tracker's matchCount/isCoasting from DTO instead of a redundant
//     local framesSeen dictionary. Coasting tracks (extrapolated position) are
//     excluded from announcements to avoid stale-location speech.
//   • SceneContextEngine generates scene-level summaries every 6s ("Two people
//     ahead, one approaching from the right") so the user gets a holistic view
//     in busy environments without per-object spam.
//   • Mode-aware: in .finding(target:) mode all speech is suppressed except
//     when the target class is detected, at which point it fires at priority 95.
//   • Emergency TTS rate increased to 0.56 (was 0.52) so warnings arrive faster.

@MainActor
class SpeechEngine: NSObject, ObservableObject, AVSpeechSynthesizerDelegate {
    @Published private(set) var alertActive: Bool = false
    @Published var objectCount: Int = 0

    private let synth = AVSpeechSynthesizer()
    private var frameSub: AnyCancellable?
    private var scanningSession: OmniSightSession?
    private var speakTimer: Timer?
    private var isSpeaking  = false
    private var isEnabled   = false
    private var mutedUntil: Date?

    // Per-object and per-class cooldowns
    private var lastSpokenAt: [String: Date] = [:]  // objectId → last spoken
    private var lastClassAt:  [String: Date] = [:]  // className → last spoken

    private var userInVehicle = false
    private var travelVelocitySamples: [Double] = []

    private var lastLiDARDepth: Float = 0.0
    private var lastCollisionAt: Date = .distantPast
    private var lastLiDARAt:     Date = .distantPast
    private var lastLiDARTime:   Date = .distantPast

    // Scene-level summaries (fires every ~6s, replaces per-object listing in calm scenes)
    private let sceneEngine = SceneContextEngine(cooldown: 6.0)
    private var lastSceneSummaryAt: Date = .distantPast

    // Current operating mode — set by AppStateManager
    var mode: AppMode = .navigation
    // Cooldown for finding-mode "found it" announcements
    private var lastFindAt: Date = .distantPast

    struct QueueItem {
        var text: String
        var priority: Int
        var addedAt: Date
        var expiresIn: TimeInterval
    }
    private var queue: [QueueItem] = []

    static let allWhitelistedClasses: Set<String> = [
        "person", "car", "truck", "bus", "bicycle", "motorcycle",
        "dog", "cat", "chair", "table", "door", "stairs",
    ]

    // MARK: — Setup

    override init() {
        super.init()
        synth.delegate = self
        let audio = AVAudioSession.sharedInstance()
        try? audio.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
        try? audio.setActive(true)
    }

    func start(scanning: OmniSightSession?) {
        stop()
        isEnabled = true
        self.scanningSession = scanning

        frameSub = scanning?.$lastPayload
            .receive(on: DispatchQueue.main)
            .sink { [weak self] frame in
                if let f = frame { self?.onFrame(f) }
            }

        speakTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in self?.drainQueue() }
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
        lastSpokenAt.removeAll()
        lastClassAt.removeAll()
        isSpeaking  = false
        alertActive = false
        sceneEngine.reset()
    }

    // MARK: — Frame processing

    private func onFrame(_ frame: FramePayload) {
        guard isEnabled else { return }
        if let mute = mutedUntil, Date() < mute { return }

        let hazardAlarmsOn = (UserDefaults.standard.object(forKey: "hazardAlarmsEnabled") as? Bool) ?? true
        let hapticsOn      = (UserDefaults.standard.object(forKey: "hapticsEnabled") as? Bool) ?? true

        // Only use actively-detected (non-coasting) objects — coasting tracks have
        // extrapolated positions and should not trigger new announcements.
        let activeObjects = frame.objects.filter { !$0.isCoasting }

        // Filter by whitelist + range + confidence
        var fastCheck:  [DetectedObjectDTO] = []
        var confirmed:  [DetectedObjectDTO] = []

        for obj in activeObjects {
            guard let maxRange = getMaxRange(for: obj.objectClass) else { continue }
            guard obj.distanceM <= maxRange else { continue }
            guard obj.confidence >= getMinConfidence(for: obj.objectClass) else { continue }
            if obj.matchCount >= 2 { fastCheck.append(obj) }
            if obj.matchCount >= 3 { confirmed.append(obj) }
        }

        // — Finding mode: suppress everything except the target —
        if case .finding(let target) = mode {
            handleFindingMode(target: target, confirmed: confirmed, hapticsOn: hapticsOn)
            objectCount = confirmed.count
            return
        }

        // — Navigation mode —

        // Automated travel detection
        let highSpeedApproachers = confirmed.filter { $0.velocityMps < -4.0 }
        travelVelocitySamples.append(highSpeedApproachers.count >= 2 ? 1.0 : 0.0)
        if travelVelocitySamples.count > 30 { travelVelocitySamples.removeFirst() }
        let travelScore = travelVelocitySamples.reduce(0, +) / Double(travelVelocitySamples.count)
        let newTraveling = travelScore > 0.5
        if newTraveling != userInVehicle {
            userInVehicle = newTraveling
            if hapticsOn { HapticManager.shared.warningVibration() }
            addToQueue(userInVehicle ? "Travel mode active" : "Walking mode active",
                       priority: 100, expiresIn: 2.0)
        }

        objectCount = confirmed.count
        let now = Date()
        let verbosity = UserDefaults.standard.string(forKey: "verbosityMode") ?? "normal"

        // — Emergency: fast-approaching object directly ahead —
        let interiorLimit = userInVehicle ? 1.5 : 1.2
        let danger = fastCheck.filter {
            abs($0.panValue) < 0.45 && $0.distanceM <= interiorLimit && $0.velocityMps < -0.3
        }.min(by: { $0.distanceM < $1.distanceM })

        if let d = danger, hazardAlarmsOn {
            alertActive = true
            if hapticsOn { HapticManager.shared.warningVibration() }
            if now.timeIntervalSince(lastCollisionAt) > 3.0 {
                lastCollisionAt = now
                let text = "Warning! \(SpeechEngine.spoken(d.objectClass)), \(distText(d.distanceM))!"
                emergencySpeak(text)
            }
        } else {
            alertActive = false
        }

        // — Approaching objects —
        if let obj = confirmed.filter({ $0.velocityMps < -0.40 }).min(by: { $0.distanceM < $1.distanceM }) {
            let cls  = obj.objectClass.lowercased()
            let prio = getPriority(for: obj.objectClass)

            let suppressApproaching = verbosity != "normal" && prio < 50
            if !suppressApproaching {
                let sinceObj   = now.timeIntervalSince(lastSpokenAt[obj.objectId] ?? .distantPast)
                let sinceCls   = now.timeIntervalSince(lastClassAt[cls] ?? .distantPast)
                let classCooldown = getClassCooldown(for: cls, verbosity: verbosity)

                if sinceObj >= 5 && sinceCls >= classCooldown {
                    let text = "\(SpeechEngine.spoken(obj.objectClass)), \(directionText(obj.panValue)), \(distText(obj.distanceM)), approaching"
                    addToQueue(text, priority: 80, expiresIn: 1.2)
                    lastSpokenAt[obj.objectId] = now
                    lastClassAt[cls] = now
                }
            }
        }

        // — Scene summary (every 6s, replaces per-object listing) —
        // Fires when no high-priority items are queued, so it doesn't interrupt warnings.
        let hasHighPriority = queue.contains { $0.priority >= 80 }
        if !hasHighPriority, let ctx = sceneEngine.update(objects: confirmed, now: now) {
            let scenePrio = min(ctx.urgency, 60)  // cap below approaching-object priority
            addToQueue(ctx.summary, priority: scenePrio, expiresIn: 3.0)
        } else if hasHighPriority {
            // Don't announce static objects if something important is queued
            return
        }

        // — Closest static object (fallback when scene summary didn't fire) —
        if let obj = confirmed.filter({ $0.velocityMps >= -0.40 }).min(by: { $0.distanceM < $1.distanceM }) {
            let cls  = obj.objectClass.lowercased()
            let prio = getPriority(for: obj.objectClass)

            if verbosity == "criticalOnly" && prio < 50 { return }
            if verbosity == "lowNoise"     && prio < 50 { return }

            let sinceObj  = now.timeIntervalSince(lastSpokenAt[obj.objectId] ?? .distantPast)
            let sinceCls  = now.timeIntervalSince(lastClassAt[cls] ?? .distantPast)
            let classCooldown = getClassCooldown(for: cls, verbosity: verbosity)

            if sinceObj >= 30 && sinceCls >= classCooldown {
                let text = "\(SpeechEngine.spoken(obj.objectClass)), \(directionText(obj.panValue)), \(distText(obj.distanceM))"
                addToQueue(text, priority: prio, expiresIn: 2.0)
                lastSpokenAt[obj.objectId] = now
                lastClassAt[cls] = now
            }
        }
    }

    // MARK: — Finding mode

    private func handleFindingMode(target: String, confirmed: [DetectedObjectDTO], hapticsOn: Bool) {
        guard let found = confirmed.filter({ $0.objectClass.lowercased() == target.lowercased() })
                                   .min(by: { $0.distanceM < $1.distanceM }) else { return }

        let now = Date()
        guard now.timeIntervalSince(lastFindAt) >= 4.0 else { return }
        lastFindAt = now

        if hapticsOn { HapticManager.shared.warningVibration() }
        let dir  = directionText(found.panValue)
        let dist = distText(found.distanceM)
        addToQueue("Found \(SpeechEngine.spoken(target)), \(dir), \(dist)", priority: 95, expiresIn: 3.0)
    }

    // MARK: — Queue management

    private func addToQueue(_ text: String, priority: Int, expiresIn: TimeInterval) {
        guard !queue.contains(where: { $0.text == text }) else { return }
        queue.append(QueueItem(text: text, priority: priority, addedAt: Date(), expiresIn: expiresIn))
    }

    private func drainQueue() {
        queue = queue.filter { Date().timeIntervalSince($0.addedAt) < $0.expiresIn }
        guard !isSpeaking, !queue.isEmpty else { return }
        queue.sort { $0.priority > $1.priority }
        speakToUser(queue.removeFirst().text)
    }

    private func emergencySpeak(_ text: String) {
        synth.stopSpeaking(at: .immediate)
        isSpeaking = false
        queue.removeAll()
        speakToUser(text, rate: 0.56)
    }

    private func speakToUser(_ text: String, rate: Float = 0.52) {
        let utterance  = AVSpeechUtterance(string: text)
        utterance.rate = rate
        utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
        synth.speak(utterance)
    }

    // MARK: — Spatial text helpers

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
            return feet == 1 ? "1 foot" : "\(feet) feet"
        }
        return String(format: "%.1f meters", meters)
    }

    // MARK: — Priority / range tables

    private func getPriority(for label: String) -> Int {
        let name = label.lowercased()
        if ["car", "truck", "bus"].contains(name) { return 75 }
        if ["person", "stairs"].contains(name)    { return 70 }
        if ["chair", "table"].contains(name)      { return 30 }
        return 10
    }

    private func getMaxRange(for label: String) -> Double? {
        switch label.lowercased() {
        case "person":          return 6.0
        case "car","truck","bus": return 12.0
        case "chair","table":   return 4.0
        case "stairs":          return 6.0
        case "door":            return 5.0
        default:                return 5.0
        }
    }

    private func getMinConfidence(for label: String) -> Double {
        ["chair", "table"].contains(label.lowercased()) ? 0.60 : 0.50
    }

    private func getClassCooldown(for cls: String, verbosity: String) -> TimeInterval {
        let isFurniture = ["chair", "table"].contains(cls)
        let base: TimeInterval = isFurniture ? 15 : 5
        return verbosity == "lowNoise" ? base * 2 : base
    }

    private static func spoken(_ raw: String) -> String {
        raw.replacingOccurrences(of: "_", with: " ").capitalized
    }

    // MARK: — AVSpeechSynthesizerDelegate

    nonisolated func speechSynthesizer(_ s: AVSpeechSynthesizer, didStart _: AVSpeechUtterance) {
        Task { @MainActor [weak self] in self?.isSpeaking = true }
    }
    nonisolated func speechSynthesizer(_ s: AVSpeechSynthesizer, didFinish _: AVSpeechUtterance) {
        Task { @MainActor [weak self] in self?.isSpeaking = false }
    }
    nonisolated func speechSynthesizer(_ s: AVSpeechSynthesizer, didCancel _: AVSpeechUtterance) {
        Task { @MainActor [weak self] in self?.isSpeaking = false }
    }

    // MARK: — Public API

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

    func setMode(_ newMode: AppMode) {
        let changed = mode != newMode
        mode = newMode
        if changed {
            sceneEngine.reset()
            lastFindAt = .distantPast
            if case .finding(let t) = newMode {
                speakImmediate("Finding \(SpeechEngine.spoken(t)). Hold camera up.")
            } else {
                speakImmediate("Navigation mode")
            }
        }
    }

    // MARK: — LiDAR obstacle detection

    func updateLiDARDepth(_ depthMeters: Float) {
        guard isEnabled else { return }
        if let mute = mutedUntil, Date() < mute { return }
        // Finding mode: still warn about collisions

        let now = Date()
        let dt  = now.timeIntervalSince(lastLiDARTime)
        let vel = (depthMeters - lastLiDARDepth) / Float(max(0.01, dt))

        lastLiDARDepth = depthMeters
        lastLiDARTime  = now

        // Skip if optical system already identified this spot
        let recentObjects = scanningSession?.lastPayload?.objects ?? []
        let alreadyTagged = recentObjects.contains {
            abs(Double(depthMeters) - $0.distanceM) < 0.40 && abs($0.panValue) < 0.40 && $0.confidence > 0.40
        }
        if alreadyTagged { return }

        let minThreshold: Float = userInVehicle ? 1.5 : 1.2
        guard depthMeters < minThreshold else { return }
        if userInVehicle && vel > -0.2 { return }
        guard now.timeIntervalSince(lastLiDARAt) >= 2.5 else { return }

        let hazardAlarmsOn = (UserDefaults.standard.object(forKey: "hazardAlarmsEnabled") as? Bool) ?? true
        let hapticsOn      = (UserDefaults.standard.object(forKey: "hapticsEnabled") as? Bool) ?? true
        guard hazardAlarmsOn else { return }

        lastLiDARAt = now
        alertActive = true
        if hapticsOn { HapticManager.shared.warningVibration() }

        let dist = distText(Double(depthMeters))
        let text = "Obstacle ahead, \(dist)"

        if depthMeters < 0.90 {
            emergencySpeak(text)
        } else {
            addToQueue(text, priority: 99, expiresIn: 1.5)
        }
    }
}
