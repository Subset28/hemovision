
import CoreImage
import CoreVideo
import Foundation
import Vision

// Detects pedestrian walk/don't-walk signals using on-device OCR.
// Text-first: matches "WALK" / "DON'T WALK" / "WAIT" in frame.
// Color fallback: bright-white dominant → walk person, orange dominant → don't-walk hand.
// Requires 2 consecutive agreeing frames before firing onSignalChange.
// Throttled to 1 fps — does not run on every camera frame.

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

        let raw = textResult() ?? colorResult(pixelBuffer)

        DispatchQueue.main.async { [weak self] in
            self?.integrate(raw)
        }
    }

    // MARK: - Text detection

    private func textResult() -> Signal? {
        guard let observations = textRequest.results, !observations.isEmpty else { return nil }
        let joined = observations
            .compactMap { $0.topCandidates(1).first?.string }
            .joined(separator: " ")
            .uppercased()

        if joined.contains("DON'T WALK") || joined.contains("DONT WALK") || joined.contains("WAIT") {
            return .dontWalk
        }
        // Match standalone "WALK" — avoid "WALKWAY", "BOARDWALK", "JAYWALKING"
        let words = joined.components(separatedBy: .whitespacesAndNewlines)
        if words.contains("WALK") {
            return .walk
        }
        return nil
    }

    // MARK: - Color fallback (symbol-only signs)

    private func colorResult(_ pixelBuffer: CVPixelBuffer) -> Signal {
        let ciImage = CIImage(cvPixelBuffer: pixelBuffer)
        let extent = ciImage.extent
        // Sample the upper-center third of the frame where signs typically appear
        let sampleRect = CGRect(
            x: extent.width  * 0.25,
            y: extent.height * 0.1,
            width:  extent.width  * 0.5,
            height: extent.height * 0.4
        )
        let cropped = ciImage.cropped(to: sampleRect)

        guard let avgColor = averageColor(of: cropped) else { return .unknown }
        let (r, g, b) = avgColor

        // Orange hand: high red, moderate green, low blue
        if r > 0.55 && g > 0.25 && g < 0.55 && b < 0.25 { return .dontWalk }
        // White walking person: all channels high (bright white on black bg)
        if r > 0.60 && g > 0.60 && b > 0.60 { return .walk }
        return .unknown
    }

    private func averageColor(of image: CIImage) -> (Float, Float, Float)? {
        let filter = CIFilter(name: "CIAreaAverage", parameters: [
            kCIInputImageKey: image,
            kCIInputExtentKey: CIVector(cgRect: image.extent)
        ])
        guard let output = filter?.outputImage else { return nil }
        var bitmap = [Float](repeating: 0, count: 4)
        let ctx = CIContext()
        ctx.render(output,
                   toBitmap: &bitmap,
                   rowBytes: 16,
                   bounds: CGRect(x: 0, y: 0, width: 1, height: 1),
                   format: .RGBAf,
                   colorSpace: nil)
        return (bitmap[0], bitmap[1], bitmap[2])
    }

    // MARK: - Confirmation gate

    private func integrate(_ raw: Signal) {
        if raw == lastRaw {
            streak += 1
        } else {
            lastRaw = raw
            streak = 1
        }
        guard streak >= 2, raw != .unknown, raw != confirmed else { return }
        confirmed = raw
        onSignalChange?(raw)
    }
}
