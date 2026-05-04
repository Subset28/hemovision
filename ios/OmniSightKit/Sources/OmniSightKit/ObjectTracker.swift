// OmniSight - Visual Navigation System
// Personal Project - Source Code




import Foundation
import CoreGraphics

// ObjectTracker
// Keeps track of objects between camera frames so we can:
//   1. Give each object a consistent ID even as it moves
//   2. Calculate how fast the object is approaching (velocity)
//
// How matching works:
//   Each frame, we compare new detections against our saved tracks.
//   If a new detection is the same class AND close on screen, it's the same object.
//   If nothing matches, it's a brand-new object and gets a new ID.

public class ObjectTracker {
    private var nextId = 1
    private var tracks: [TrackedObject] = []
    private let matchThreshold: Double = 0.22  // Slightly wider for easier matching
    private let maxGhostFrames: Int = 15       // Keep objects alive for ~1.5s at 10fps

    public var onStalePrune: ((Int) -> Void)?
    public init(highPriorityDistanceM: Double) {}

    public func update(detections: [RawDetection], now: TimeInterval, frameIndex: Int) -> [TrackedObject] {
        var newTracks: [TrackedObject] = []
        // We'll pull matched detections out of this list as we go
        var unmatched = detections

        // Try to match each existing track to a new detection
        for var track in tracks {
            var bestMatchIndex: Int = -1
            var bestDistance: Double = matchThreshold

            for i in 0..<unmatched.count {
                let det = unmatched[i]

                // Must be the same class to match
                if det.className != track.className { continue }

                // Calculate how far apart they are on screen
                let dx = det.xCenterNorm - track.xCenterNorm
                let dy = det.yCenterNorm - track.yCenterNorm
                let screenDist = sqrt(dx * dx + dy * dy)

                if screenDist < bestDistance {
                    bestDistance   = screenDist
                    bestMatchIndex = i
                }
            }

            if bestMatchIndex >= 0 {
                // Found a match — update the track with the new position
                let matched = unmatched.remove(at: bestMatchIndex)
                track.update(with: matched, now: now)
                newTracks.append(track)
            } else {
                // No match found — enter "Ghost Mode"
                track.enterGhostMode(now: now)
                if track.ghostCount < maxGhostFrames {
                    newTracks.append(track)
                }
            }
        }

        // Everything left in unmatched is a brand-new object
        for det in unmatched {
            let newTrack = TrackedObject(id: "\(nextId)", detection: det, now: now)
            nextId += 1
            newTracks.append(newTrack)
        }

        tracks = newTracks
        return tracks
    }
}

// TrackedObject
// Stores everything we know about a single object across time.
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
    public var velocityMps: Double = 0  // negative = getting closer, positive = moving away
    public var priority:    String = "NORMAL"
    public var lastSeen:    TimeInterval
    public var ghostCount:  Int = 0
    public var isGhost:     Bool { ghostCount > 0 }

    // Used to calculate velocity — we compare current distance to previous distance
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
        ghostCount = 0 // Reset ghosting on successful match

        // Only update velocity if enough time has passed
        if timeDelta > 0.04 {
            let rawVelocity = (det.distanceM - prevDistanceM) / timeDelta
            velocityMps   = velocityMps * 0.7 + rawVelocity * 0.3
            prevDistanceM = det.distanceM
            prevTime      = now
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

    /// Extrapolate position when the object is lost (Dead Reckoning)
    mutating func enterGhostMode(now: TimeInterval) {
        let timeDelta = now - prevTime
        ghostCount += 1
        
        if timeDelta > 0.04 {
            // Predict new distance based on last known velocity
            distanceM += velocityMps * timeDelta
            // Sanity check: distance can't be negative
            distanceM = max(0.1, distanceM)
            prevTime = now
            
            // Confidence decays while ghosting
            confidence *= 0.9
        }
    }
}
