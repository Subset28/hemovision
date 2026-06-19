
import Foundation

// PerformanceMonitor — lightweight per-session metrics for OmniSight.
//
// Counters and a ring buffer for latency percentiles. All writes are
// NSLock-protected so they're safe from the Vision workQueue and @MainActor.
// The report() method produces a Codable snapshot suitable for logging/sharing.
//
// Toggle via `isEnabled`. When disabled every record* call is a no-op.

public final class PerformanceMonitor: @unchecked Sendable {
    public static let shared = PerformanceMonitor()

    public var isEnabled = false

    private let lock = NSLock()
    private var sessionStart = Date()

    // Frame latency ring buffer (ms) — Vision workQueue writes, report reads
    private var latencyBuf: [Double] = []
    private let latencyBufSize = 120

    // Tracking counters
    private var tracksCreated:    Int = 0
    private var tracksPromoted:   Int = 0
    private var tracksPruned:     Int = 0
    private var coastRecoveries:  Int = 0

    // TTS counters (written on @MainActor, read on @MainActor via report())
    public var ttsEmitted:    Int = 0
    public var ttsSuppressed: Int = 0

    // Scene counters
    public var sceneUpdates:     Int = 0
    public var sceneSuppressed:  Int = 0

    private init() {}

    // MARK: - Record

    public func recordFrame(latencyMs: Double) {
        guard isEnabled else { return }
        lock.lock(); defer { lock.unlock() }
        if latencyBuf.count >= latencyBufSize { latencyBuf.removeFirst() }
        latencyBuf.append(latencyMs)
    }

    public func recordTrackEvents(_ events: [TrackEvent]) {
        guard isEnabled, !events.isEmpty else { return }
        lock.lock(); defer { lock.unlock() }
        for e in events {
            switch e.kind {
            case .created:       tracksCreated  += 1
            case .promoted:      tracksPromoted += 1
            case .pruned:        tracksPruned   += 1
            case .reidentified:  coastRecoveries += 1
            case .coasting:      break
            }
        }
    }

    // MARK: - Report

    public func report() -> MetricsReport {
        lock.lock()
        let buf       = latencyBuf
        let created   = tracksCreated
        let promoted  = tracksPromoted
        let pruned    = tracksPruned
        let recoveries = coastRecoveries
        lock.unlock()

        let p50 = percentile(0.50, of: buf)
        let p95 = percentile(0.95, of: buf)
        let elapsed = max(1, Date().timeIntervalSince(sessionStart))
        let minutes = elapsed / 60

        let emitted    = ttsEmitted
        let suppressed = ttsSuppressed
        let total      = emitted + suppressed
        let sceneUp    = sceneUpdates
        let sceneSupp  = sceneSuppressed

        return MetricsReport(
            sessionDurationS:    elapsed,
            framesProcessed:     buf.count,
            latencyP50Ms:        p50,
            latencyP95Ms:        p95,
            tracksCreated:       created,
            tracksPromoted:      promoted,
            tracksPruned:        pruned,
            coastingRecoveries:  recoveries,
            reidentificationRate: pruned > 0 ? Double(recoveries) / Double(recoveries + pruned) : 0,
            ttsEmitted:          emitted,
            ttsSuppressed:       suppressed,
            ttsEmissionsPerMin:  minutes > 0 ? Double(emitted) / minutes : 0,
            ttsSuppressedRatio:  total > 0 ? Double(suppressed) / Double(total) : 0,
            sceneUpdates:        sceneUp,
            sceneSuppressed:     sceneSupp
        )
    }

    public func resetSession() {
        lock.lock(); defer { lock.unlock() }
        latencyBuf.removeAll()
        tracksCreated   = 0
        tracksPromoted  = 0
        tracksPruned    = 0
        coastRecoveries = 0
        ttsEmitted      = 0
        ttsSuppressed   = 0
        sceneUpdates    = 0
        sceneSuppressed = 0
        sessionStart    = Date()
    }

    // MARK: - Helpers

    private func percentile(_ p: Double, of arr: [Double]) -> Double {
        guard !arr.isEmpty else { return 0 }
        let sorted = arr.sorted()
        let idx = Int((Double(sorted.count - 1) * p).rounded())
        return sorted[Swift.min(idx, sorted.count - 1)]
    }
}

// MARK: - Report type

public struct MetricsReport: Encodable {
    public let sessionDurationS:     Double
    public let framesProcessed:      Int
    public let latencyP50Ms:         Double
    public let latencyP95Ms:         Double
    public let tracksCreated:        Int
    public let tracksPromoted:       Int
    public let tracksPruned:         Int
    public let coastingRecoveries:   Int
    public let reidentificationRate: Double
    public let ttsEmitted:           Int
    public let ttsSuppressed:        Int
    public let ttsEmissionsPerMin:   Double
    public let ttsSuppressedRatio:   Double
    public let sceneUpdates:         Int
    public let sceneSuppressed:      Int

    enum CodingKeys: String, CodingKey {
        case sessionDurationS     = "session_duration_s"
        case framesProcessed      = "frames_processed"
        case latencyP50Ms         = "latency_p50_ms"
        case latencyP95Ms         = "latency_p95_ms"
        case tracksCreated        = "tracks_created"
        case tracksPromoted       = "tracks_promoted"
        case tracksPruned         = "tracks_pruned"
        case coastingRecoveries   = "coasting_recoveries"
        case reidentificationRate = "reidentification_rate"
        case ttsEmitted           = "tts_emitted"
        case ttsSuppressed        = "tts_suppressed"
        case ttsEmissionsPerMin   = "tts_emissions_per_minute"
        case ttsSuppressedRatio   = "tts_suppressed_ratio"
        case sceneUpdates         = "scene_updates"
        case sceneSuppressed      = "scene_suppressed"
    }

    // Returns indented JSON string, nil if encoding fails
    public var jsonString: String? {
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted, .sortedKeys]
        guard let data = try? enc.encode(self) else { return nil }
        return String(data: data, encoding: .utf8)
    }
}
