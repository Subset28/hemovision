
import Foundation

// SceneContextEngine — converts per-frame detections into natural-language scene summaries.
//
// The core TTS loop announces individual objects one at a time, which is fine for
// "person, 2 meters, right" but produces a wall of speech in busy environments.
// This engine generates higher-level summaries fired at a low cadence (default 6s):
//   "Two people ahead, one approaching from the right"
//   "Busy area — 5 objects nearby"
//   "Path ahead is clear"
//
// Change detection: the engine compares a lightweight signature of the current scene
// against the last-spoken signature. If the scene is essentially unchanged (same
// classes at similar distances), the summary is suppressed even if the cooldown
// has elapsed — avoids repeating "Path clear" forever in an empty hallway.

public class SceneContextEngine {

    public struct SceneContext {
        public enum Density: Int { case clear, sparse, moderate, crowded }
        public let density:  Density
        public let summary:  String
        public let urgency:  Int    // 0–100; maps to TTS queue priority
        public let changed:  Bool   // false ⟹ suppress even if cooldown elapsed
    }

    private let cooldown: TimeInterval
    private var lastAt:   Date   = .distantPast
    private var lastSig:  String = ""

    public init(cooldown: TimeInterval = 6.0) { self.cooldown = cooldown }

    // Returns a context when cooldown has elapsed AND the scene has meaningfully changed.
    public func update(objects: [DetectedObjectDTO], now: Date = Date()) -> SceneContext? {
        guard now.timeIntervalSince(lastAt) >= cooldown else { return nil }
        let sig = signature(of: objects)
        let changed = sig != lastSig
        lastSig = sig
        lastAt  = now
        let ctx = buildContext(objects: objects, changed: changed)

        if changed || ctx.urgency > 50 {
            PerformanceMonitor.shared.sceneUpdates += 1
            DecisionLog.shared.log(layer: .scene, decision: "Updated",
                detail: "\"\(ctx.summary)\" (density=\(ctx.density.rawValue), urgency=\(ctx.urgency))")
            return ctx
        } else {
            PerformanceMonitor.shared.sceneSuppressed += 1
            DecisionLog.shared.log(layer: .scene, decision: "Suppressed",
                detail: "signature unchanged (objects: \(objects.count))")
            return nil
        }
    }

    // Immediate summary, bypassing cooldown (use for mode transitions).
    public func forceSummarize(objects: [DetectedObjectDTO]) -> SceneContext {
        lastAt  = Date()
        let ctx = buildContext(objects: objects, changed: true)
        lastSig = signature(of: objects)
        return ctx
    }

    public func reset() {
        lastAt  = .distantPast
        lastSig = ""
    }

    // Cheap change signal: classes present + 1-meter distance bucket
    private func signature(of objects: [DetectedObjectDTO]) -> String {
        objects
            .filter { $0.distanceM < 7.0 }
            .map { "\($0.objectClass):\(Int($0.distanceM))" }
            .sorted()
            .joined(separator: "|")
    }

    private func buildContext(objects: [DetectedObjectDTO], changed: Bool) -> SceneContext {
        guard !objects.isEmpty else {
            return SceneContext(density: .clear, summary: "Path ahead is clear", urgency: 0, changed: changed)
        }

        let nearby   = objects.filter { $0.distanceM < 3.0 }
        let hazards  = objects.filter { isHazard($0.objectClass) }
        let closing  = objects.filter { $0.velocityMps < -0.4 }
        let urgency  = computeUrgency(hazards: hazards, closing: closing)
        let density  = computeDensity(all: objects, nearby: nearby)
        let summary  = buildSummary(objects: objects, hazards: hazards, closing: closing, density: density)

        return SceneContext(density: density, summary: summary, urgency: urgency, changed: changed)
    }

    private func computeUrgency(hazards: [DetectedObjectDTO], closing: [DetectedObjectDTO]) -> Int {
        if let ch = closing.filter({ isHazard($0.objectClass) }).min(by: { $0.distanceM < $1.distanceM }) {
            if ch.distanceM < 2.0 { return 80 }
            return 60
        }
        if let h = hazards.min(by: { $0.distanceM < $1.distanceM }) {
            if h.distanceM < 1.5 { return 85 }
            if h.distanceM < 3.0 { return 50 }
            return 25
        }
        return 10
    }

    private func computeDensity(all: [DetectedObjectDTO], nearby: [DetectedObjectDTO]) -> SceneContext.Density {
        if all.isEmpty  { return .clear }
        if all.count <= 2 && nearby.isEmpty { return .sparse }
        if all.count <= 4 { return .moderate }
        return .crowded
    }

    private func buildSummary(
        objects:  [DetectedObjectDTO],
        hazards:  [DetectedObjectDTO],
        closing:  [DetectedObjectDTO],
        density:  SceneContext.Density
    ) -> String {
        // Closing hazard takes priority
        if let t = closing.filter({ isHazard($0.objectClass) }).min(by: { $0.distanceM < $1.distanceM }) {
            return "\(humanName(t.objectClass).capitalized) approaching \(direction(t.panValue))"
        }

        // Describe closest hazard if one is nearby
        if let h = hazards.min(by: { $0.distanceM < $1.distanceM }), h.distanceM < 5.0 {
            let dir  = direction(h.panValue)
            let dist = distString(h.distanceM)
            // Count multiples of the same class
            let sameClass = hazards.filter { $0.objectClass == h.objectClass }.count
            let name = sameClass > 1 ? "\(sameClass) \(humanName(h.objectClass))s" : humanName(h.objectClass)
            return "\(name.capitalized) \(dir), \(dist)"
        }

        switch density {
        case .clear:
            return "Path ahead is clear"
        case .sparse:
            guard let first = objects.min(by: { $0.distanceM < $1.distanceM }) else {
                return "Path mostly clear"
            }
            return "\(humanName(first.objectClass).capitalized) \(direction(first.panValue)), \(distString(first.distanceM))"
        case .moderate:
            let counts = Dictionary(grouping: objects, by: { $0.objectClass }).mapValues(\.count)
            let parts  = counts.sorted { $0.value > $1.value }.prefix(2).map { (k, v) in
                v > 1 ? "\(v) \(humanName(k))s" : humanName(k)
            }
            return parts.joined(separator: " and ").capitalized
        case .crowded:
            return "Busy area — \(objects.count) objects nearby"
        }
    }

    private func direction(_ pan: Double) -> String {
        if pan < -0.5  { return "to your left" }
        if pan < -0.15 { return "slightly left" }
        if pan <= 0.15 { return "ahead" }
        if pan <= 0.5  { return "slightly right" }
        return "to your right"
    }

    private func distString(_ m: Double) -> String {
        let useImperial = UserDefaults.standard.bool(forKey: "useImperialUnits")
        if useImperial {
            let ft = max(1, Int((m * 3.281).rounded()))
            return ft == 1 ? "1 foot" : "\(ft) feet"
        }
        return String(format: "%.1f meters", m)
    }

    private func isHazard(_ cls: String) -> Bool {
        ["person", "car", "truck", "bus", "bicycle", "motorcycle", "stairs", "dog"].contains(cls.lowercased())
    }

    private func humanName(_ cls: String) -> String {
        cls.replacingOccurrences(of: "_", with: " ").lowercased()
    }
}
