

import Foundation
import CoreGraphics

// ObjectTracker — SORT-inspired multi-object tracker for OmniSight.
//
// Improvements over the prior center-distance matcher:
//   • IoU matching — correctly handles multiple same-class objects in proximity.
//     Falls back to center-distance when boxes don't overlap (common at 15fps
//     when a fast object jumps frame-to-frame).
//   • Track state machine — TENTATIVE → CONFIRMED → COASTING → pruned.
//     A track coasts for up to maxCoastFrames before being deleted, so a brief
//     occlusion or detection gap doesn't kill a confirmed track.
//   • Screen-space velocity — during coasting, the predicted position is
//     extrapolated from the track's historical screen velocity, keeping IoU
//     matching accurate on re-entry.
//
// Matching is O(NM log NM) greedy on sorted scores — fine for <20 objects.

public class ObjectTracker {
    private var nextId = 1
    private var tracks: [TrackedObject] = []

    private let maxCoastFrames = 3    // frames a confirmed track survives without a match
    private let confirmFrames  = 3    // matches to promote tentative → confirmed
    private let iouThreshold   = 0.10 // minimum IoU to count as a valid match
    private let centerFallback = 0.22 // max center-distance for fallback scoring

    public var onStalePrune: ((Int) -> Void)?
    public init(highPriorityDistanceM: Double) {}

    public func update(detections: [RawDetection], now: TimeInterval, frameIndex: Int) -> [TrackedObject] {
        // 1. Predict positions for tracks that missed last frame
        for i in tracks.indices { tracks[i].predictPosition(now: now) }

        // 2. Score every same-class (track, detection) pair
        struct Candidate { let ti: Int; let di: Int; let score: Double }
        var candidates: [Candidate] = []

        for ti in tracks.indices {
            for di in detections.indices {
                guard detections[di].className == tracks[ti].className else { continue }
                let iou = boxIoU(det: detections[di], track: tracks[ti])
                let score: Double
                if iou >= iouThreshold {
                    score = iou
                } else {
                    let dx = detections[di].xCenterNorm - tracks[ti].predictedX
                    let dy = detections[di].yCenterNorm - tracks[ti].predictedY
                    let d = sqrt(dx * dx + dy * dy)
                    guard d < centerFallback else { continue }
                    // Map [0, centerFallback) → (0, 0.09] so it never beats a real IoU match
                    score = (centerFallback - d) / centerFallback * 0.09
                }
                candidates.append(Candidate(ti: ti, di: di, score: score))
            }
        }
        candidates.sort { $0.score > $1.score }

        // 3. Greedy assignment — highest score wins each slot
        var usedTracks = Set<Int>()
        var usedDets   = Set<Int>()
        var matched:   [(Int, Int)] = []

        for c in candidates {
            guard !usedTracks.contains(c.ti), !usedDets.contains(c.di) else { continue }
            usedTracks.insert(c.ti); usedDets.insert(c.di)
            matched.append((c.ti, c.di))
        }

        // 4. Update matched tracks
        for (ti, di) in matched { tracks[ti].update(with: detections[di], now: now) }

        // 5. Age unmatched tracks; transition to coasting
        for ti in tracks.indices where !usedTracks.contains(ti) {
            tracks[ti].coastFrames += 1
            if tracks[ti].state != .coasting { tracks[ti].state = .coasting }
        }

        // 6. Prune dead tracks
        let dead = tracks.filter { $0.coastFrames > maxCoastFrames }
        for t in dead { onStalePrune?(Int(t.objectId) ?? -1) }
        tracks = tracks.filter { $0.coastFrames <= maxCoastFrames }

        // 7. Spawn new tracks for unmatched detections (start as tentative)
        for di in detections.indices where !usedDets.contains(di) {
            tracks.append(TrackedObject(id: "\(nextId)", detection: detections[di], now: now))
            nextId += 1
        }

        // 8. Promote tentative → confirmed
        for i in tracks.indices {
            if tracks[i].matchCount >= confirmFrames && tracks[i].state == .tentative {
                tracks[i].state = .confirmed
            }
        }

        return tracks
    }

    // IoU on predicted track position vs. raw detection box
    private func boxIoU(det: RawDetection, track: TrackedObject) -> Double {
        let ax1 = det.xCenterNorm - det.widthNorm  / 2
        let ax2 = det.xCenterNorm + det.widthNorm  / 2
        let ay1 = det.yCenterNorm - det.heightNorm / 2
        let ay2 = det.yCenterNorm + det.heightNorm / 2

        let bx1 = track.predictedX - track.widthNorm  / 2
        let bx2 = track.predictedX + track.widthNorm  / 2
        let by1 = track.predictedY - track.heightNorm / 2
        let by2 = track.predictedY + track.heightNorm / 2

        let ix = max(0, min(ax2, bx2) - max(ax1, bx1))
        let iy = max(0, min(ay2, by2) - max(ay1, by1))
        let inter = ix * iy
        guard inter > 0 else { return 0 }
        let union = det.widthNorm * det.heightNorm + track.widthNorm * track.heightNorm - inter
        return inter / max(union, 1e-9)
    }
}

public enum TrackState: Equatable {
    case tentative   // fewer than confirmFrames matches — not yet announced
    case confirmed   // stably tracked
    case coasting    // missed ≤ maxCoastFrames; position is extrapolated
}

public struct TrackedObject {
    public let objectId:    String
    public var className:   String
    public var xCenterNorm: Double
    public var yCenterNorm: Double
    public var widthNorm:   Double
    public var heightNorm:  Double
    public var confidence:  Double
    public var distanceM:   Double
    public var panValue:    Double
    public var velocityMps: Double = 0
    public var priority:    String = "NORMAL"
    public var lastSeen:    TimeInterval
    public var state:       TrackState = .tentative
    public var coastFrames: Int        = 0
    public var matchCount:  Int        = 1

    // Predicted screen position — used during coasting for IoU matching
    public private(set) var predictedX: Double
    public private(set) var predictedY: Double

    // Screen-space velocity (normalized units/second)
    private var vX: Double = 0
    private var vY: Double = 0

    private var prevDist: Double
    private var prevTime: TimeInterval
    private var prevX:    Double
    private var prevY:    Double

    init(id: String, detection: RawDetection, now: TimeInterval) {
        objectId    = id
        className   = detection.className
        xCenterNorm = detection.xCenterNorm
        yCenterNorm = detection.yCenterNorm
        widthNorm   = detection.widthNorm
        heightNorm  = detection.heightNorm
        confidence  = detection.confidence
        distanceM   = detection.distanceM
        panValue    = detection.panValue
        lastSeen    = now
        prevDist    = detection.distanceM
        prevTime    = now
        prevX       = detection.xCenterNorm
        prevY       = detection.yCenterNorm
        predictedX  = detection.xCenterNorm
        predictedY  = detection.yCenterNorm
    }

    // Linear extrapolation from screen velocity — called each frame before matching
    mutating func predictPosition(now: TimeInterval) {
        guard coastFrames > 0 else { return }
        let dt = now - lastSeen
        predictedX = (xCenterNorm + vX * dt).clamped(to: 0...1)
        predictedY = (yCenterNorm + vY * dt).clamped(to: 0...1)
    }

    mutating func update(with det: RawDetection, now: TimeInterval) {
        let dt = now - prevTime
        if dt > 0.03 {
            // Depth velocity (negative = approaching the camera)
            let rawV = (det.distanceM - prevDist) / dt
            velocityMps = velocityMps * 0.6 + rawV * 0.4

            // Screen velocity EMA for coasting prediction
            let rawVX = (det.xCenterNorm - prevX) / dt
            let rawVY = (det.yCenterNorm - prevY) / dt
            vX = vX * 0.7 + rawVX * 0.3
            vY = vY * 0.7 + rawVY * 0.3

            prevDist = det.distanceM
            prevTime = now
            prevX    = det.xCenterNorm
            prevY    = det.yCenterNorm
        }

        xCenterNorm = det.xCenterNorm
        yCenterNorm = det.yCenterNorm
        predictedX  = det.xCenterNorm
        predictedY  = det.yCenterNorm
        widthNorm   = det.widthNorm
        heightNorm  = det.heightNorm
        confidence  = det.confidence
        distanceM   = det.distanceM
        panValue    = det.panValue
        lastSeen    = now
        coastFrames = 0
        matchCount += 1
        if state == .coasting { state = .tentative }
    }
}

private extension Comparable {
    func clamped(to range: ClosedRange<Self>) -> Self {
        Swift.min(Swift.max(self, range.lowerBound), range.upperBound)
    }
}
