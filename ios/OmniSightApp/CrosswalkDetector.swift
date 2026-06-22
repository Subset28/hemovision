
import CoreVideo
import Foundation
import Vision

// Detects pedestrian walk/don't-walk signals using on-device OCR.
// Matches "WALK" / "DON'T WALK" / "WAIT" as standalone words in frame text.
// Requires 2 consecutive agreeing frames before firing onSignalChange.
// Resets confirmed state after 5 consecutive unknown frames so re-entering
// the same crosswalk type re-announces correctly.
// Throttled to 1 fps — does not run on every camera frame.
//
// Color fallback intentionally omitted: averaging the frame's upper region
// produces false positives on bright outdoor scenes (sky, sunlit walls).
// OCR on text-based signs is reliable and fails safe (silence on no match).

class CrosswalkDetector {
    enum Signal: Equatable {
        case walk
        case dontWalk
        case unknown
    }

    var onSignalChange: ((Signal) -> Void)?

    private let textRequest: VNRecognizeTextRequest = {
        let r = VNRecognizeTextRequest()
        r.recognitionLevel = .fast
        r.usesLanguageCorrection = false
        return r
    }()

    private var lastRunTime: TimeInterval = 0
    private var lastRaw: Signal = .unknown
    private var streak = 0
    private var unknownStreak = 0
    private var confirmed: Signal = .unknown

    func process(pixelBuffer: CVPixelBuffer, timestamp: TimeInterval) {
        guard timestamp - lastRunTime >= 1.0 else { return }
        lastRunTime = timestamp
        let retained = pixelBuffer
        CVPixelBufferRetain(retained)
        DispatchQueue.global(qos: .utility).async { [weak self] in
            self?.runDetection(on: retained)
            CVPixelBufferRelease(retained)
        }
    }

    private func runDetection(on pixelBuffer: CVPixelBuffer) {
        let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, options: [:])
        try? handler.perform([textRequest])
        let raw = textResult()
        DispatchQueue.main.async { [weak self] in
            self?.integrate(raw)
        }
    }

    // MARK: - Text detection

    private func textResult() -> Signal {
        guard let observations = textRequest.results, !observations.isEmpty else { return .unknown }
        let joined = observations
            .compactMap { $0.topCandidates(1).first?.string }
            .joined(separator: " ")
            .uppercased()

        let words = joined.components(separatedBy: .whitespacesAndNewlines)

        // Check don't-walk phrases before standalone WALK to avoid substring collision
        if joined.contains("DON'T WALK") || joined.contains("DONT WALK") { return .dontWalk }
        if words.contains("WAIT") { return .dontWalk }
        if words.contains("WALK") { return .walk }
        return .unknown
    }

    // MARK: - Confirmation gate

    private func integrate(_ raw: Signal) {
        if raw == .unknown {
            unknownStreak += 1
            // After 5 consecutive unknowns (~5s), reset so the next sign re-announces
            if unknownStreak >= 5 { confirmed = .unknown }
            streak = 0
            lastRaw = .unknown
            return
        }

        unknownStreak = 0
        if raw == lastRaw {
            streak += 1
        } else {
            lastRaw = raw
            streak = 1
        }
        guard streak >= 2, raw != confirmed else { return }
        confirmed = raw
        onSignalChange?(raw)
    }
}
