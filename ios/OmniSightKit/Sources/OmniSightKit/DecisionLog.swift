
import Foundation

// DecisionLog — explainability layer for OmniSight.
//
// Every non-trivial system decision at each pipeline layer emits a LogEntry.
// When enabled, entries are printed to console and held in a capped ring buffer
// so the UI can display them in real time.
//
// Entries explain WHY the system acted (or didn't act), turning the app from an
// opaque black box into an interpretable system:
//   [TRACKER] Track #5 confirmed: person (matched 3 frames)
//   [TTS] Suppressed: person objectId=3 (classCD: 1.8s elapsed < 5.0s required)
//   [SCENE] Updated: "Person approaching right" (density=moderate, urgency=60)
//
// Thread-safe via NSLock. Toggle `isEnabled` at any time.

public final class DecisionLog: @unchecked Sendable {
    public static let shared = DecisionLog()

    public var isEnabled = false

    private let lock = NSLock()
    private let maxEntries = 60
    private var _entries: [LogEntry] = []

    private init() {}

    // MARK: - Entry type

    public struct LogEntry: Identifiable {
        public let id = UUID()
        public let timestamp: Date
        public let layer: Layer
        public let decision: String
        public let detail: String

        public enum Layer: String {
            case tracker = "TRACKER"
            case tts     = "TTS"
            case scene   = "SCENE"
            case pipeline = "PIPELINE"
        }

        public var formatted: String {
            "[\(layer.rawValue)] \(decision): \(detail)"
        }
    }

    // Read-only snapshot — safe to call from @MainActor
    public var entries: [LogEntry] {
        lock.lock(); defer { lock.unlock() }
        return _entries
    }

    // MARK: - Logging

    public func log(layer: LogEntry.Layer, decision: String, detail: String) {
        guard isEnabled else { return }
        let entry = LogEntry(timestamp: Date(), layer: layer, decision: decision, detail: detail)
        lock.lock()
        if _entries.count >= maxEntries { _entries.removeFirst() }
        _entries.append(entry)
        lock.unlock()
        print("[OmniSight:\(layer.rawValue)] \(decision): \(detail)")
    }

    public func clear() {
        lock.lock(); defer { lock.unlock() }
        _entries.removeAll()
    }

    // MARK: - Track event convenience

    public func recordTrackEvents(_ events: [TrackEvent]) {
        guard isEnabled, !events.isEmpty else { return }
        for e in events {
            switch e.kind {
            case .created(let id, let cls, let dist):
                log(layer: .tracker, decision: "Track #\(id) created",
                    detail: "class=\(cls), dist=\(String(format: "%.1f", dist))m")
            case .promoted(let id, let cls, let count):
                log(layer: .tracker, decision: "Track #\(id) confirmed",
                    detail: "class=\(cls), matched=\(count) frames")
            case .coasting(let id, let cls, let frame):
                log(layer: .tracker, decision: "Track #\(id) coasting",
                    detail: "class=\(cls), frame \(frame)/3")
            case .reidentified(let id, let cls, let iou, let coasted):
                log(layer: .tracker, decision: "Track #\(id) re-identified",
                    detail: "class=\(cls), IoU=\(String(format: "%.2f", iou)), coasted \(coasted) frames")
            case .pruned(let id, let cls, let lifetime):
                log(layer: .tracker, decision: "Track #\(id) pruned",
                    detail: "class=\(cls), lifetime=\(lifetime) frames")
            }
        }
    }
}
