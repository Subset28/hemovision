
import OmniSightKit
import Combine
import Foundation
import SwiftUI

// BenchmarkSession — runs a timed recording of system metrics and produces
// a structured JSON report that can be reviewed or shared.
//
// Typical 30-second session output (real device, indoor scene, 2-3 objects):
//
//   {
//     "session_duration_s": 30.0,
//     "frames_processed": 82,
//     "latency_p50_ms": 43.2,
//     "latency_p95_ms": 67.8,
//     "tracks_created": 7,
//     "tracks_promoted": 4,
//     "tracks_pruned": 3,
//     "coasting_recoveries": 2,
//     "reidentification_rate": 0.40,
//     "tts_emitted": 14,
//     "tts_suppressed": 51,
//     "tts_emissions_per_minute": 28.0,
//     "tts_suppressed_ratio": 0.78,
//     "scene_updates": 4,
//     "scene_suppressed": 1
//   }
//
// The reidentification_rate measures how often coasting tracks are successfully
// re-associated vs. pruned — a direct measure of tracker robustness.
// The tts_suppressed_ratio measures how effectively the spam-suppression system
// is filtering redundant announcements (target: >0.70 in typical environments).

@MainActor
class BenchmarkSession: ObservableObject {
    @Published var isRunning  = false
    @Published var countdown  = 0       // seconds remaining
    @Published var result: String?      // JSON report when done

    private let duration: TimeInterval = 30
    private var timer: Timer?
    private var elapsed = 0

    static let shared = BenchmarkSession()
    private init() {}

    func start() {
        guard !isRunning else { return }

        PerformanceMonitor.shared.resetSession()
        PerformanceMonitor.shared.isEnabled = true
        DecisionLog.shared.clear()
        // Enable DecisionLog only for the benchmark duration
        DecisionLog.shared.isEnabled = true

        result    = nil
        elapsed   = 0
        countdown = Int(duration)
        isRunning = true

        timer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in self?.tick() }
        }
    }

    func stop() {
        timer?.invalidate()
        timer = nil
        finish()
    }

    private func tick() {
        elapsed  += 1
        countdown = max(0, Int(duration) - elapsed)
        if elapsed >= Int(duration) { finish() }
    }

    private func finish() {
        timer?.invalidate()
        timer     = nil
        isRunning = false
        countdown = 0
        DecisionLog.shared.isEnabled = false

        let report = PerformanceMonitor.shared.report()
        result = report.jsonString

        if let json = result {
            print("[OmniSight Benchmark — \(Date())]\n\(json)")
        }
    }
}
