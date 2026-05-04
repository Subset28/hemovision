// OmniSight - Visual Navigation System
// Quality Assurance Suite

import XCTest
@testable import OmniSightKit

final class ObjectTrackerTests: XCTestCase {
    
    var tracker: ObjectTracker!
    
    override func setUp() {
        super.setUp()
        tracker = ObjectTracker(highPriorityDistanceM: 1.5)
    }
    
    func testObjectPersistenceGhosting() {
        let now = Date().timeIntervalSince1970
        let det = RawDetection(className: "person", confidence: 0.9, xCenterNorm: 0.5, yCenterNorm: 0.5, widthNorm: 0.1, heightNorm: 0.2, distanceM: 3.0, panValue: 0.0)
        
        // Frame 1: Initial detection
        var tracks = tracker.update(detections: [det], now: now, frameIndex: 1)
        XCTAssertEqual(tracks.count, 1)
        XCTAssertFalse(tracks[0].isGhost)
        
        // Frame 2: Object disappears (should enter ghost mode)
        tracks = tracker.update(detections: [], now: now + 0.1, frameIndex: 2)
        XCTAssertEqual(tracks.count, 1, "Object should persist in ghost mode")
        XCTAssertTrue(tracks[0].isGhost)
        XCTAssertEqual(tracks[0].ghostCount, 1)
    }
    
    func testDeadReckoningPrediction() {
        let now = Date().timeIntervalSince1970
        
        // Frame 1: 5.0 meters
        let det1 = RawDetection(className: "car", confidence: 0.9, xCenterNorm: 0.5, yCenterNorm: 0.5, widthNorm: 0.1, heightNorm: 0.2, distanceM: 5.0, panValue: 0.0)
        _ = tracker.update(detections: [det1], now: now, frameIndex: 1)
        
        // Frame 2: 4.0 meters (velocity is -10 m/s)
        let det2 = RawDetection(className: "car", confidence: 0.9, xCenterNorm: 0.5, yCenterNorm: 0.5, widthNorm: 0.1, heightNorm: 0.2, distanceM: 4.0, panValue: 0.0)
        var tracks = tracker.update(detections: [det2], now: now + 0.1, frameIndex: 2)
        
        let velocity = tracks[0].velocityMps
        XCTAssertLessThan(velocity, 0, "Velocity should be negative for approaching object")
        
        // Frame 3: Object disappears. Predict new distance based on velocity.
        // Last velocity was ~ -10m/s. In 0.1s, it should move ~ 1 meter closer.
        tracks = tracker.update(detections: [], now: now + 0.2, frameIndex: 3)
        XCTAssertEqual(tracks.count, 1)
        XCTAssertTrue(tracks[0].isGhost)
        
        // Expected distance should be approx 3.0m (4.0m - 1.0m)
        XCTAssertTrue(tracks[0].distanceM < 4.0, "Predicted distance should be less than last seen distance")
        XCTAssertTrue(tracks[0].distanceM > 2.0, "Predicted distance should be reasonable")
    }
    
    func testPriorityInversionFix() {
        // We just fixed this in SpeechEngine, but we can verify the DTOs here
        // If a car is closer than a chair, it should be reflected in the payload
    }
}
