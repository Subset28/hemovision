// OmniSight - Visual Navigation System
// Personal Project - Source Code

import Foundation
import CoreGraphics

// ObjectTracker
// Keeps track of objects between camera frames so we can:
//   1. Give each object a consistent ID even as it moves
//   2. Calculate how fast the object is approaching (velocity)

public class ObjectTracker {
    private var nextId = 1
    private var tracks: [TrackedObject] = []
    private let matchThreshold: Double = 0.22  
    private let maxGhostFrames: Int = 15       

    public var onStalePrune: ((Int) -> Void)?
    public init(highPriorityDistanceM: Double) {}

    public func update(detections: [RawDetection], now: TimeInterval, frameIndex: Int) -> [TrackedObject] {
        var newTracks: [TrackedObject] = []
        var unmatched = detections

        for var track in tracks {
            var bestMatchIndex: Int = -1
            var bestDistance: Double = matchThreshold

            for i in 0..<unmatched.count {
                let det = unmatched[i]
                if det.className != track.className { continue }

                let dx = det.xCenterNorm - track.xCenterNorm
                let dy = det.yCenterNorm - track.yCenterNorm
                let screenDist = sqrt(dx * dx + dy * dy)

                if screenDist < bestDistance {
                    bestDistance   = screenDist
                    bestMatchIndex = i
                }
            }

            if bestMatchIndex >= 0 {
                let matched = unmatched.remove(at: bestMatchIndex)
                track.update(with: matched, now: now)
                newTracks.append(track)
            } else {
                track.enterGhostMode(now: now)
                if track.ghostCount < maxGhostFrames {
                    newTracks.append(track)
                }
            }
        }

        for det in unmatched {
            let newTrack = TrackedObject(id: "\(nextId)", detection: det, now: now)
            nextId += 1
            newTracks.append(newTrack)
        }

        tracks = newTracks
        return tracks
    }
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
    public var ghostCount:  Int = 0
    public var isGhost:     Bool { ghostCount > 0 }

    private var prevDistanceM: Double
    private var prevTime:      TimeInterval

    init(id: String, detection: RawDetection, now: TimeInterval) {
        objectId      = id
        className     = detection.className
        xCenterNorm   = detection.xCenterNorm
        yCenterNorm   = detection.yCenterNorm
        widthNorm     = detection.widthNorm
        heightNorm    = detection.heightNorm
        confidence    = detection.confidence
        distanceM     = detection.distanceM
        panValue      = detection.panValue
        lastSeen      = now
        prevDistanceM = detection.distanceM
        prevTime      = now
    }

    mutating func update(with det: RawDetection, now: TimeInterval) {
        let timeDelta = now - prevTime
        ghostCount = 0 

        // Update Speed: Distance change / Time change
        if timeDelta > 0.05 {
            velocityMps = (det.distanceM - prevDistanceM) / timeDelta
            prevDistanceM = det.distanceM
            prevTime = now
        }

        xCenterNorm = det.xCenterNorm
        yCenterNorm = det.yCenterNorm
        widthNorm   = det.widthNorm
        heightNorm  = det.heightNorm
        confidence  = det.confidence
        distanceM   = det.distanceM
        panValue    = det.panValue
        lastSeen    = now
    }

    mutating func enterGhostMode(now: TimeInterval) {
        let timeDelta = now - prevTime
        ghostCount += 1
        
        if timeDelta > 0.05 {
            // New Distance = Old Distance + (Speed * Time)
            distanceM += velocityMps * timeDelta
            distanceM = max(0.5, distanceM)
            prevTime = now
            confidence *= 0.95
        }
    }
}
