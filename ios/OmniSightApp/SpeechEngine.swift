
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
    private var lastCooldown: TimeInterval = 6.0

    // Crowd density state
    private var crowdModeActive = false
    private var lastCrowdAt:    Date = .distantPast
    private var crowdExitAt:    Date = .distantPast

    // Finding mode cooldown
    private var lastFindAt: Date = .distantPast

    // Current mode
    var mode: AppMode = .navigation

    // Last snapshotted speech rate — updated each frame, used by drainQueue
    private var currentSpeechRate: Float = 0.52

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
        let verbosity:          String
        let hazardAlarmsOn:     Bool
        let hapticsOn:          Bool
        let useImperial:        Bool
        let emergencyDistanceM: Double
        let rangeMultiplier:    Double
        let sceneCooldown:      TimeInterval
        let speechRate:         Float
        let disabledClasses:    Set<String>

        init() {
            let ud = UserDefaults.standard
            verbosity          = ud.string(forKey: "verbosityMode") ?? "normal"
            hazardAlarmsOn     = (ud.object(forKey: "hazardAlarmsEnabled") as? Bool) ?? true
            hapticsOn          = (ud.object(forKey: "hapticsEnabled") as? Bool) ?? true
            useImperial        = ud.bool(forKey: "useImperialUnits")
            emergencyDistanceM = ud.object(forKey: "emergencyDistanceM") as? Double ?? 1.2
            rangeMultiplier    = ud.object(forKey: "rangeMultiplier")    as? Double ?? 1.0
            sceneCooldown      = ud.object(forKey: "sceneCooldown")      as? Double ?? 6.0
            let storedRate     = Float(ud.double(forKey: "speechRate"))
            speechRate         = storedRate > 0.1 ? storedRate : 0.52
            disabledClasses    = SpeechEngine.allWhitelistedClasses.filter {
                !(ud.object(forKey: "classEnabled_\($0)") as? Bool ?? true)
            }
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
        crowdModeActive = false
        lastCrowdAt     = .distantPast
        crowdExitAt     = .distantPast
    }

    // MARK: - Frame pipeline

    private func onFrame(_ frame: FramePayload) {
        guard isEnabled else { return }
        if let mute = mutedUntil, Date() < mute { return }

        let settings = Settings()
        currentSpeechRate = settings.speechRate
        if settings.sceneCooldown != lastCooldown {
            lastCooldown = settings.sceneCooldown
            sceneEngine.cooldown = settings.sceneCooldown
        }

        // Speech-filtered analysis respects class-disable toggles for announcements.
        let analysis = filterObjects(frame.objects, settings: settings)
        objectCount  = analysis.confirmed.count

        // Emergency detection always runs in all modes, on hazard-class objects
        // that bypass the class-disable filter — so turning off "person" in class
        // toggles doesn't silently disable collision alarms.
        let safetyAnalysis = filterForEmergency(frame.objects, settings: settings)
        detectEmergency(analysis: safetyAnalysis, settings: settings)

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
        queueCrowdDensity(analysis: analysis)

        // When in a crowd, suppress individual person announcements — TTS would
        // flood with "person left / person right / person ahead" every few seconds.
        let active = crowdModeActive
        let thinned = active ? FrameAnalysis(
            fastCheck: analysis.fastCheck.filter { $0.objectClass.lowercased() != "person" },
            confirmed:  analysis.confirmed.filter  { $0.objectClass.lowercased() != "person" }
        ) : analysis

        queueApproaching(analysis: thinned, settings: settings)
        queueSceneSummary(analysis: thinned)
        queueStaticObject(analysis: thinned, settings: settings)
    }

    // MARK: - Filter step

    private func filterObjects(_ objects: [DetectedObjectDTO], settings: Settings) -> FrameAnalysis {
        var fastCheck: [DetectedObjectDTO] = []
        var confirmed: [DetectedObjectDTO] = []

        for obj in objects {
            if obj.isCoasting {
                DecisionLog.shared.log(layer: .tts, decision: "Skipped coasting",
                    detail: "objectId=\(obj.objectId) class=\(obj.objectClass)")
                continue
            }
            if settings.disabledClasses.contains(obj.objectClass.lowercased()) { continue }
            guard let base = maxRange(for: obj.objectClass) else { continue }
            guard obj.distanceM <= base * settings.rangeMultiplier else { continue }
            guard obj.confidence >= minConfidence(for: obj.objectClass) else { continue }

            if obj.matchCount >= 2 { fastCheck.append(obj) }
            if obj.matchCount >= 3 { confirmed.append(obj) }
        }
        return FrameAnalysis(fastCheck: fastCheck, confirmed: confirmed)
    }

    // Safety filter: hazard classes only, no class-disable gate.
    // Used exclusively by detectEmergency so disabled class toggles never suppress
    // collision alarms — matching the promise in Settings footer.
    private func filterForEmergency(_ objects: [DetectedObjectDTO], settings: Settings) -> FrameAnalysis {
        var fastCheck: [DetectedObjectDTO] = []
        for obj in objects {
            if obj.isCoasting { continue }
            guard hazardClasses.contains(obj.objectClass.lowercased()) else { continue }
            guard let base = maxRange(for: obj.objectClass) else { continue }
            guard obj.distanceM <= base * settings.rangeMultiplier else { continue }
            guard obj.confidence >= minConfidence(for: obj.objectClass) else { continue }
            if obj.matchCount >= 2 { fastCheck.append(obj) }
        }
        return FrameAnalysis(fastCheck: fastCheck, confirmed: [])
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
            if settings.hapticsOn { HapticManager.shared.smallVibration() }
            addToQueue(userInVehicle ? "Travel mode active" : "Walking mode active",
                       priority: 100, expiresIn: 2.0, reason: "mode transition")
        }
    }

    // MARK: - Emergency detection

    private func detectEmergency(analysis: FrameAnalysis, settings: Settings) {
        guard settings.hazardAlarmsOn else { return }
        let limit = userInVehicle ? settings.emergencyDistanceM + 0.3 : settings.emergencyDistanceM

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
        let isNew    = lastSpokenAt[obj.objectId] == nil

        // Per-object cooldown always applies. Class cooldown is bypassed for brand-new
        // objects — otherwise a new hazard appearing right after one of the same class
        // would be silently suppressed, which is dangerous in traffic.
        guard sinceObj >= 5 && (sinceCls >= cd || isNew) else {
            PerformanceMonitor.shared.ttsSuppressed += 1
            DecisionLog.shared.log(layer: .tts, decision: "Suppressed approaching",
                detail: "class=\(cls) objectCD=\(String(format:"%.1f",sinceObj))s<5s, classCD=\(String(format:"%.1f",sinceCls))s<\(cd)s")
            return
        }

        let text = "\(Self.spoken(obj.objectClass)), \(dirText(obj.panValue)), \(distText(obj.distanceM)), \(approachVerb(obj.velocityMps))"
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

        if settings.verbosity != "normal" && prio < 50 {
            PerformanceMonitor.shared.ttsSuppressed += 1
            DecisionLog.shared.log(layer: .tts, decision: "Suppressed static",
                detail: "class=\(cls), verbosity=\(settings.verbosity), priority=\(prio)<50")
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

    // MARK: - Crowd density

    private func queueCrowdDensity(analysis: FrameAnalysis) {
        let persons = analysis.confirmed.filter {
            $0.objectClass.lowercased() == "person" && $0.distanceM <= 4.0
        }
        let count = persons.count
        let now   = Date()

        if count >= 3 {
            crowdModeActive = true
            crowdExitAt = now.addingTimeInterval(5.0)
        } else if crowdModeActive && now > crowdExitAt {
            // 5-second hysteresis: don't deactivate immediately when count dips below 3
            // so a person briefly leaving frame doesn't oscillate person suppression.
            crowdModeActive = false
        }

        guard crowdModeActive, count >= 3 else { return }
        guard now.timeIntervalSince(lastCrowdAt) >= 10.0 else { return }
        lastCrowdAt = now

        let text = count >= 6 ? "Dense crowd, \(count) people" : "Crowd ahead, \(count) people"
        addToQueue(text, priority: 72, expiresIn: 3.0, reason: "crowd count=\(count)")
    }

    // MARK: - Finding mode

    private func handleFindingMode(target: String, confirmed: [DetectedObjectDTO], settings: Settings) {
        guard let found = confirmed.filter({ $0.objectClass.lowercased() == target.lowercased() })
                                   .min(by: { $0.distanceM < $1.distanceM }) else { return }
        let now = Date()
        guard now.timeIntervalSince(lastFindAt) >= 4.0 else { return }
        lastFindAt = now
        if settings.hapticsOn { HapticManager.shared.mediumVibration() }
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

    private func speakToUser(_ text: String, rate: Float? = nil) {
        let utt  = AVSpeechUtterance(string: text)
        utt.rate = rate ?? currentSpeechRate
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

    private func approachVerb(_ mps: Double) -> String {
        if mps < -1.5 { return "closing fast" }
        if mps < -0.6 { return "approaching" }
        return "moving closer"
    }

    private func distText(_ meters: Double) -> String {
        formatDistance(meters, imperial: UserDefaults.standard.bool(forKey: "useImperialUnits"))
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

    // Crosswalk signals bypass the mute timer — a blind user at a crosswalk
    // must hear this regardless of whether they muted for another reason.
    func announceCrosswalk(_ text: String) {
        synth.stopSpeaking(at: .immediate)
        queue.removeAll()
        isSpeaking = false
        speakToUser(text, rate: 0.50)
        HapticManager.shared.mediumVibration()
    }

    // Step hazard alerts bypass the queue — same safety rationale as announceCrosswalk.
    func announceStepHazard(_ hazard: StepHazardDetector.StepHazard) {
        let enabled = (UserDefaults.standard.object(forKey: "stepDetectionEnabled") as? Bool) ?? true
        guard enabled else { return }

        let text: String
        let useWarning: Bool

        switch hazard {
        case .clear:
            return
        case .stepDown(let dist):
            text = dist.map { "Step down, \(distText(Double($0)))" } ?? "Step down ahead"
            useWarning = true
        case .stepUp(let dist):
            text = dist.map { "Curb or step up, \(distText(Double($0)))" } ?? "Curb or step up"
            useWarning = false
        case .stairsDescending(let dist):
            text = dist.map { "Stairs descending, \(distText(Double($0)))" } ?? "Stairs descending ahead"
            useWarning = true
        case .stairsAscending(let dist):
            text = dist.map { "Stairs ascending, \(distText(Double($0)))" } ?? "Stairs ascending ahead"
            useWarning = false
        }

        synth.stopSpeaking(at: .immediate)
        queue.removeAll()
        isSpeaking = false
        speakToUser(text, rate: 0.50)

        let hapticsOn = (UserDefaults.standard.object(forKey: "hapticsEnabled") as? Bool) ?? true
        if hapticsOn {
            useWarning ? HapticManager.shared.warningVibration() : HapticManager.shared.mediumVibration()
        }
    }

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

        let baseLimit = Float((UserDefaults.standard.object(forKey: "emergencyDistanceM") as? Double) ?? 1.2)
        let limit: Float = userInVehicle ? baseLimit + 0.3 : baseLimit
        guard depthMeters < limit else { return }
        if userInVehicle && vel > -0.2 { return }
        guard now.timeIntervalSince(lastLiDARAt) >= 2.5 else { return }

        let hazardAlarmsOn = (UserDefaults.standard.object(forKey: "hazardAlarmsEnabled") as? Bool) ?? true
        guard hazardAlarmsOn else { return }

        lastLiDARAt = now
        alertActive = true
        HapticManager.shared.warningVibration()

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
