import CoreVideo
import Foundation

final class StepHazardDetector {

    enum StepHazard {
        case clear
        case stepDown(distanceM: Float?)
        case stepUp(distanceM: Float?)
        case stairsDescending(distanceM: Float?)
        case stairsAscending(distanceM: Float?)
    }

    // Set exactly once during init, before the pipeline starts. Serial-queue reads are safe
    // because initialization completes before the first ARKit frame is delivered.
    var onHazardChange: ((StepHazard) -> Void)?

    private let queue = DispatchQueue(label: "com.orbconcepts.omnisight.stephazard", qos: .utility)
    private var lastHazardAt: TimeInterval = 0

    func process(depthMap: CVPixelBuffer?, timestamp: TimeInterval) {
        guard let dm = depthMap else { return }
        queue.async { [weak self, timestamp] in
            guard let self else { return }
            let enabled = (UserDefaults.standard.object(forKey: "stepDetectionEnabled") as? Bool) ?? true
            guard enabled else { return }
            guard timestamp - self.lastHazardAt >= 3.0 else { return }
            self.lastHazardAt = timestamp
            let hazard = self.analyzeDepth(dm)
            if case .clear = hazard { return }
            DispatchQueue.main.async { [weak self] in self?.onHazardChange?(hazard) }
        }
    }

    // MARK: - Depth analysis
    // Samples a 10-column × 5-row grid across the bottom 40% of the LiDAR depth frame.
    // Detects abrupt column-wise depth changes that indicate steps, curbs, or stairs.
    // LiDAR depthMap format: kCVPixelFormatType_DepthFloat32, depth in meters per pixel.
    // "Bottom 40%" = rows 60%–100% of frame height = ground closest to user's feet.
    private func analyzeDepth(_ depthMap: CVPixelBuffer) -> StepHazard {
        CVPixelBufferLockBaseAddress(depthMap, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(depthMap, .readOnly) }

        let width  = CVPixelBufferGetWidth(depthMap)
        let height = CVPixelBufferGetHeight(depthMap)
        let bpr    = CVPixelBufferGetBytesPerRow(depthMap)
        guard let base = CVPixelBufferGetBaseAddress(depthMap), width > 0, height > 0 else { return .clear }

        let floats = base.assumingMemoryBound(to: Float32.self)
        let rowStride = bpr / MemoryLayout<Float32>.size

        let cols    = 10
        let rows    = 5
        let startY  = Int(Double(height) * 0.60)
        let rowStep = max(1, (height - startY) / rows)
        let colStep = max(1, width / cols)

        var grid = [[Float32]](repeating: [Float32](repeating: 0, count: cols), count: rows)
        for r in 0..<rows {
            for c in 0..<cols {
                let py = min(height - 1, startY + r * rowStep)
                let px = min(width  - 1, c * colStep)
                let v  = floats[py * rowStride + px]
                grid[r][c] = (v > 0 && v.isFinite && v < 20.0) ? v : 0
            }
        }

        struct Disc { let row: Int; let delta: Float32 }
        let threshold: Float32 = 0.15  // 15cm — catches stair treads (typically 17–18cm)
        var discs: [Disc] = []

        for c in 0..<cols {
            for r in 0..<(rows - 1) {
                let d0 = grid[r][c]
                let d1 = grid[r + 1][c]
                guard d0 > 0, d1 > 0 else { continue }
                let delta = d1 - d0
                if abs(delta) >= threshold { discs.append(Disc(row: r, delta: delta)) }
            }
        }

        guard !discs.isEmpty else { return .clear }

        let avgDelta  = discs.map(\.delta).reduce(0, +) / Float32(discs.count)
        let goingDown = avgDelta > 0  // depth increases going further = ground drops = step DOWN

        // Stairs: 3+ discontinuities with tread spacing 0.15–0.35m
        let stairLike = discs.filter { abs($0.delta) >= 0.15 && abs($0.delta) <= 0.35 }
        let isStairs  = stairLike.count >= 3

        let nearestRow = discs.map(\.row).min() ?? 0
        let distM: Float? = grid[nearestRow][cols / 2] > 0 ? grid[nearestRow][cols / 2] : nil

        switch (isStairs, goingDown) {
        case (true,  true):  return .stairsDescending(distanceM: distM)
        case (true,  false): return .stairsAscending(distanceM: distM)
        case (false, true):  return .stepDown(distanceM: distM)
        case (false, false): return .stepUp(distanceM: distM)
        }
    }
}
