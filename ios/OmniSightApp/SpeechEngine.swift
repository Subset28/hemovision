
import OmniSightKit

import AVFoundation
import Combine
import Foundation

// SpeechEngine — voice feedback controller for OmniSight.
//
// Pipeline (data flow per frame):
//   FramePayload
//     → filterObjects()            — whitelist + range + confidence + isCoasting gate
//     → [mode dispatch]            — navigation / finding / hazardPriority
//     → detectEmergency()          — collision warning at priority 99
//     → queueApproaching()         — approaching object at priority 80
//     → queueSceneSummary()        — SceneContextEngine summary at priority ≤60
//     → queueStaticObject()        — closest static object at configurable priority
//     → drainQueue()               — timer at 10Hz, priority-sorted, expiry-filtered
//     → AVSpeechSynthesizer        → user hears it
//
// Every suppression decision is logged to DecisionLog. Every emission is
// counted by PerformanceMonitor. This makes all TTS decisions auditable.

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
    private var lastSpokenAt: [String: Date] = [:]
    private var lastClassAt:  [String: Date] = [:]

    // Travel mode detection
    private var userInVehicle = false
    private var travelVelocitySamples: [Double] = []

    // LiDAR state
    private var lastLiDARDepth: Float = 0.0
    private var lastCollisionAt: Date = .distantPast
    private var lastLiDARAt:     Date = .distantPast
    private var lastLiDARTime:   Date = .distantPast

    // Scene summarizer
    private let sceneEngine = SceneContextEngine(cooldown: 6.0)

    // Finding mode cooldown
    private var lastFindAt: Date = .distantPast

    // Current mode
    var mode: AppMode = .navigation

    // TTS queue
    struct QueueItem {
        let text: String; let priority: Int; let addedAt: Date; let expiresIn: TimeInterval
    }
    private var queue: [QueueItem] = []

    static let allWhitelistedClasses: Set<String> = [
        "person", "car", "truck", "bus", "bicycle", "motorcycle",
        "dog", "cat", "chair", "table", "door", "stairs",
    ]

    // MARK: - Settings snapshot (read once per frame)

    private struct Settings {
        let verbosity:      String
        let hazardAlarmsOn: Bool
        let hapticsOn:      Bool
        let useImperial:    Bool

        init() {
            let ud = UserDefaults.standard
            verbosity      = ud.string(forKey: "verbosityMode") ?? "normal"
            hazardAlarmsOn = (ud.object(forKey: "hazardAlarmsEnabled") as? Bool) ?? true
            hapticsOn      = (ud.object(forKey: "hapticsEnabled") as? Bool) ?? true
            useImperial    = ud.bool(forKey: "useImperialUnits")
        }
    }

    // MARK: - Filtered view of a frame

    private struct FrameAnalysis {
        let fastCheck:   [DetectedObjectDTO]   // matched ≥ 2 frames, in range
        let confirmed:   [DetectedObjectDTO]   // matched ≥ 3 frames, in range
    }

    // MARK: - Setup

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
        travelVelocitySamples.removeAll()
    }

    // MARK: - Frame pipeline

    private func onFrame(_ frame: FramePayload) {
        guard isEnabled else { return }
        if let mute = mutedUntil, Date() < mute { return }

        let settings  = Settings()
        let analysis  = filterObjects(frame.objects)
        objectCount   = analysis.confirmed.count

        switch mode {
        case .finding(let target):
            handleFindingMode(target: target, confirmed: analysis.confirmed, settings: settings)
            return
        case .hazardPriority:
            handleHazardPriority(analysis: analysis, settings: settings)
            return
        case .navigation:
            break
        }

        updateTravelMode(analysis.confirmed, settings: settings)
        detectEmergency(analysis: analysis, settings: settings)
        queueApproaching(analysis: analysis, settings: settings)
        queueSceneSummary(analysis: analysis)
        queueStaticObject(analysis: analysis, settings: settings)
    }

    // MARK: - Filter step

    private func filterObjects(_ objects: [DetectedObjectDTO]) -> FrameAnalysis {
        var fastCheck: [DetectedObjectDTO] = []
        var confirmed: [DetectedObjectDTO] = []

        for obj in objects {
            // Skip coasting tracks — their position is extrapolated, not measured
            if obj.isCoasting {
                DecisionLog.shared.log(layer: .tts, decision: "Skipped coasting",
                    detail: "objectId=\(obj.objectId) class=\(obj.objectClass)")
                continue
            }
            guard let maxRange = maxRange(for: obj.objectClass) else { continue }
            guard obj.distanceM <= maxRange else { continue }
            guard obj.confidence >= minConfidence(for: obj.objectClass) else { continue }

            if obj.matchCount >= 2 { fastCheck.append(obj) }
            if obj.matchCount >= 3 { confirmed.append(obj) }
        }
        return FrameAnalysis(fastCheck: fastCheck, confirmed: confirmed)
    }

    // MARK: - Travel mode

    private func updateTravelMode(_ confirmed: [DetectedObjectDTO], settings: Settings) {
        let highSpeed = confirmed.filter { $0.velocityMps < -4.0 }
        travelVelocitySamples.append(highSpeed.count >= 2 ? 1.0 : 0.0)
        if travelVelocitySamples.count > 30 { travelVelocitySamples.removeFirst() }
        let score = travelVelocitySamples.reduce(0, +) / Double(travelVelocitySamples.count)
        let nowTraveling = score > 0.5
        if nowTraveling != userInVehicle {
            userInVehicle = nowTraveling
            if settings.hapticsOn { HapticManager.shared.warningVibration() }
            addToQueue(userInVehicle ? "Travel mode active" : "Walking mode active",
                       priority: 100, expiresIn: 2.0, reason: "mode transition")
        }
    }

    // MARK: - Emergency detection

    private func detectEmergency(analysis: FrameAnalysis, settings: Settings) {
        guard settings.hazardAlarmsOn else { return }
        let limit = userInVehicle ? 1.5 : 1.2

        let danger = analysis.fastCheck.filter {
            abs($0.panValue) < 0.45 && $0.distanceM <= limit && $0.velocityMps < -0.3
        }.min(by: { $0.distanceM < $1.distanceM })

        if let d = danger {
            alertActive = true
            if settings.hapticsOn { HapticManager.shared.warningVibration() }
            let now = Date()
            if now.timeIntervalSince(lastCollisionAt) > 3.0 {
                lastCollisionAt = now
                let text = "Warning! \(Self.spoken(d.objectClass)), \(distText(d.distanceM))!"
                DecisionLog.shared.log(layer: .tts, decision: "Emergency",
                    detail: "objectId=\(d.objectId) dist=\(String(format:"%.1f",d.distanceM))m vel=\(String(format:"%.1f",d.velocityMps))m/s")
                emergencySpeak(text)
            }
        } else {
            alertActive = false
        }
    }

    // MARK: - Approaching objects

    private func queueApproaching(analysis: FrameAnalysis, settings: Settings) {
        guard let obj = analysis.confirmed.filter({ $0.velocityMps < -0.40 })
                                          .min(by: { $0.distanceM < $1.distanceM }) else { return }

        let cls  = obj.objectClass.lowercased()
        let prio = priority(for: obj.objectClass)
        let now  = Date()

        if settings.verbosity != "normal" && prio < 50 {
            PerformanceMonitor.shared.ttsSuppressed += 1
            DecisionLog.shared.log(layer: .tts, decision: "Suppressed approaching",
                detail: "class=\(cls), verbosity=\(settings.verbosity), priority=\(prio)<50")
            return
        }

        let sinceObj = now.timeIntervalSince(lastSpokenAt[obj.objectId] ?? .distantPast)
        let sinceCls = now.timeIntervalSince(lastClassAt[cls] ?? .distantPast)
        let cd       = classCooldown(for: cls, verbosity: settings.verbosity)

        guard sinceObj >= 5 && sinceCls >= cd else {
            PerformanceMonitor.shared.ttsSuppressed += 1
            DecisionLog.shared.log(layer: .tts, decision: "Suppressed approaching",
                detail: "class=\(cls) objectCD=\(String(format:"%.1f",sinceObj))s<5s, classCD=\(String(format:"%.1f",sinceCls))s<\(cd)s")
            return
        }

        let text = "\(Self.spoken(obj.objectClass)), \(dirText(obj.panValue)), \(distText(obj.distanceM)), approaching"
        addToQueue(text, priority: 80, expiresIn: 1.2, reason: "approaching objectId=\(obj.objectId)")
        lastSpokenAt[obj.objectId] = now
        lastClassAt[cls]           = now
    }

    // MARK: - Scene summary

    private func queueSceneSummary(analysis: FrameAnalysis) {
        let hasHighPriority = queue.contains { $0.priority >= 80 }
        guard !hasHighPriority else { return }

        if let ctx = sceneEngine.update(objects: analysis.confirmed) {
            let prio = min(ctx.urgency, 60)
            addToQueue(ctx.summary, priority: prio, expiresIn: 3.0, reason: "scene summary")
        }
    }

    // MARK: - Static object

    private func queueStaticObject(analysis: FrameAnalysis, settings: Settings) {
        let hasHighPriority = queue.contains { $0.priority >= 80 }
        guard !hasHighPriority else { return }

        guard let obj = analysis.confirmed.filter({ $0.velocityMps >= -0.40 })
                                          .min(by: { $0.distanceM < $1.distanceM }) else { return }

        let cls  = obj.objectClass.lowercased()
        let prio = priority(for: obj.objectClass)

        if settings.verbosity == "criticalOnly" && prio < 50 {
            PerformanceMonitor.shared.ttsSuppressed += 1
            DecisionLog.shared.log(layer: .tts, decision: "Suppressed static",
                detail: "class=\(cls), verbosity=criticalOnly, priority=\(prio)<50")
            return
        }
        if settings.verbosity == "lowNoise" && prio < 50 {
            PerformanceMonitor.shared.ttsSuppressed += 1
            DecisionLog.shared.log(layer: .tts, decision: "Suppressed static",
                detail: "class=\(cls), verbosity=lowNoise, priority=\(prio)<50")
            return
        }

        let now      = Date()
        let sinceObj = now.timeIntervalSince(lastSpokenAt[obj.objectId] ?? .distantPast)
        let sinceCls = now.timeIntervalSince(lastClassAt[cls] ?? .distantPast)
        let cd       = classCooldown(for: cls, verbosity: settings.verbosity)

        guard sinceObj >= 30 && sinceCls >= cd else {
            PerformanceMonitor.shared.ttsSuppressed += 1
            DecisionLog.shared.log(layer: .tts, decision: "Suppressed static",
                detail: "class=\(cls) objectCD=\(String(format:"%.1f",sinceObj))s<30s, classCD=\(String(format:"%.1f",sinceCls))s<\(cd)s")
            return
        }

        let text = "\(Self.spoken(obj.objectClass)), \(dirText(obj.panValue)), \(distText(obj.distanceM))"
        addToQueue(text, priority: prio, expiresIn: 2.0, reason: "static objectId=\(obj.objectId)")
        lastSpokenAt[obj.objectId] = now
        lastClassAt[cls]           = now
    }

    // MARK: - Finding mode

    private func handleFindingMode(target: String, confirmed: [DetectedObjectDTO], settings: Settings) {
        guard let found = confirmed.filter({ $0.objectClass.lowercased() == target.lowercased() })
                                   .min(by: { $0.distanceM < $1.distanceM }) else { return }
        let now = Date()
        guard now.timeIntervalSince(lastFindAt) >= 4.0 else { return }
        lastFindAt = now
        if settings.hapticsOn { HapticManager.shared.warningVibration() }
        let dir  = dirText(found.panValue)
        let dist = distText(found.distanceM)
        addToQueue("Found \(Self.spoken(target)), \(dir), \(dist)", priority: 95, expiresIn: 3.0,
                   reason: "finding mode match objectId=\(found.objectId)")
    }

    // MARK: - Hazard Priority mode
    //
    // Suppresses all non-hazard objects. Shortens cooldowns to 3s.
    // Tighter announcement range (4m). No scene summaries.
    // Optimized for dense urban / traffic crossing scenarios.

    private func handleHazardPriority(analysis: FrameAnalysis, settings: Settings) {
        // Always run emergency detection
        detectEmergency(analysis: analysis, settings: settings)

        let hazards = analysis.confirmed.filter { hazardClasses.contains($0.objectClass.lowercased()) }

        // Suppress non-hazard objects — log the suppression
        let suppressed = analysis.confirmed.filter { !hazardClasses.contains($0.objectClass.lowercased()) }
        for obj in suppressed {
            PerformanceMonitor.shared.ttsSuppressed += 1
            DecisionLog.shared.log(layer: .tts, decision: "Suppressed (hazardPriority)",
                detail: "class=\(obj.objectClass) non-hazard, objectId=\(obj.objectId)")
        }

        // Announce closest approaching hazard
        if let obj = hazards.filter({ $0.velocityMps < -0.40 }).min(by: { $0.distanceM < $1.distanceM }) {
            let cls = obj.objectClass.lowercased()
            let now = Date()
            let sinceObj = now.timeIntervalSince(lastSpokenAt[obj.objectId] ?? .distantPast)
            let sinceCls = now.timeIntervalSince(lastClassAt[cls] ?? .distantPast)

            if sinceObj >= 3 && sinceCls >= 3 && obj.distanceM <= 6.0 {
                let text = "Caution: \(Self.spoken(obj.objectClass)), \(dirText(obj.panValue)), \(distText(obj.distanceM))"
                addToQueue(text, priority: 85, expiresIn: 1.5, reason: "hazardPriority approaching")
                lastSpokenAt[obj.objectId] = now
                lastClassAt[cls]           = now
            } else {
                PerformanceMonitor.shared.ttsSuppressed += 1
                DecisionLog.shared.log(layer: .tts, decision: "Suppressed (hazardPriority)",
                    detail: "class=\(cls) still in cooldown or out of range")
            }
            return
        }

        // Announce closest static hazard if within 3m
        if let obj = hazards.min(by: { $0.distanceM < $1.distanceM }), obj.distanceM <= 3.0 {
            let cls = obj.objectClass.lowercased()
            let now = Date()
            let sinceObj = now.timeIntervalSince(lastSpokenAt[obj.objectId] ?? .distantPast)
            let sinceCls = now.timeIntervalSince(lastClassAt[cls] ?? .distantPast)

            if sinceObj >= 10 && sinceCls >= 6 {
                let text = "\(Self.spoken(obj.objectClass)), \(dirText(obj.panValue)), \(distText(obj.distanceM))"
                addToQueue(text, priority: 65, expiresIn: 2.0, reason: "hazardPriority static")
                lastSpokenAt[obj.objectId] = now
                lastClassAt[cls]           = now
            } else {
                PerformanceMonitor.shared.ttsSuppressed += 1
                DecisionLog.shared.log(layer: .tts, decision: "Suppressed (hazardPriority)",
                    detail: "class=\(cls) static, still in cooldown")
            }
        }
    }

    // MARK: - Queue management

    private func addToQueue(_ text: String, priority: Int, expiresIn: TimeInterval, reason: String = "") {
        if queue.contains(where: { $0.text == text }) {
            PerformanceMonitor.shared.ttsSuppressed += 1
            DecisionLog.shared.log(layer: .tts, decision: "Suppressed duplicate",
                detail: "\"\(text)\"")
            return
        }
        queue.append(QueueItem(text: text, priority: priority, addedAt: Date(), expiresIn: expiresIn))
        PerformanceMonitor.shared.ttsEmitted += 1
        DecisionLog.shared.log(layer: .tts, decision: "Queued",
            detail: "\"\(text)\" priority=\(priority) reason=\(reason)")
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
        let utt  = AVSpeechUtterance(string: text)
        utt.rate = rate
        utt.voice = AVSpeechSynthesisVoice(language: "en-US")
        synth.speak(utt)
    }

    // MARK: - Spatial text helpers

    private func dirText(_ pan: Double) -> String {
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

    // MARK: - Priority / range tables

    private func priority(for label: String) -> Int {
        let n = label.lowercased()
        if ["car", "truck", "bus"].contains(n)   { return 75 }
        if ["person", "stairs"].contains(n)       { return 70 }
        if ["chair", "table"].contains(n)         { return 30 }
        return 10
    }

    private func maxRange(for label: String) -> Double? {
        switch label.lowercased() {
        case "person":            return 6.0
        case "car","truck","bus": return 12.0
        case "chair","table":     return 4.0
        case "stairs":            return 6.0
        case "door":              return 5.0
        default:                  return 5.0
        }
    }

    private func minConfidence(for label: String) -> Double {
        ["chair", "table"].contains(label.lowercased()) ? 0.60 : 0.50
    }

    private func classCooldown(for cls: String, verbosity: String) -> TimeInterval {
        let base: TimeInterval = ["chair", "table"].contains(cls) ? 15 : 5
        return verbosity == "lowNoise" ? base * 2 : base
    }

    private static func spoken(_ raw: String) -> String {
        raw.replacingOccurrences(of: "_", with: " ").capitalized
    }

    // MARK: - AVSpeechSynthesizerDelegate

    nonisolated func speechSynthesizer(_ s: AVSpeechSynthesizer, didStart _: AVSpeechUtterance) {
        Task { @MainActor [weak self] in self?.isSpeaking = true }
    }
    nonisolated func speechSynthesizer(_ s: AVSpeechSynthesizer, didFinish _: AVSpeechUtterance) {
        Task { @MainActor [weak self] in self?.isSpeaking = false }
    }
    nonisolated func speechSynthesizer(_ s: AVSpeechSynthesizer, didCancel _: AVSpeechUtterance) {
        Task { @MainActor [weak self] in self?.isSpeaking = false }
    }

    // MARK: - Public API

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
        guard mode != newMode else { return }
        mode = newMode
        sceneEngine.reset()
        lastFindAt = .distantPast
        DecisionLog.shared.log(layer: .pipeline, decision: "Mode changed", detail: newMode.displayName)
        switch newMode {
        case .finding(let t):   speakImmediate("Finding \(Self.spoken(t)). Hold camera up.")
        case .hazardPriority:   speakImmediate("Hazard priority mode")
        case .navigation:       speakImmediate("Navigation mode")
        }
    }

    // MARK: - LiDAR obstacle detection

    func updateLiDARDepth(_ depthMeters: Float) {
        guard isEnabled else { return }
        if let mute = mutedUntil, Date() < mute { return }

        let now = Date()
        let dt  = now.timeIntervalSince(lastLiDARTime)
        let vel = (depthMeters - lastLiDARDepth) / Float(max(0.01, dt))
        lastLiDARDepth = depthMeters
        lastLiDARTime  = now

        let recentObjects = scanningSession?.lastPayload?.objects ?? []
        let alreadyTagged = recentObjects.contains {
            abs(Double(depthMeters) - $0.distanceM) < 0.40 && abs($0.panValue) < 0.40 && $0.confidence > 0.40
        }
        if alreadyTagged { return }

        let limit: Float = userInVehicle ? 1.5 : 1.2
        guard depthMeters < limit else { return }
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

        DecisionLog.shared.log(layer: .pipeline, decision: "LiDAR obstacle",
            detail: "depth=\(String(format:"%.2f",depthMeters))m vel=\(String(format:"%.2f",vel))m/s")

        if depthMeters < 0.90 {
            emergencySpeak(text)
        } else {
            addToQueue(text, priority: 99, expiresIn: 1.5, reason: "LiDAR obstacle")
        }
    }
}
