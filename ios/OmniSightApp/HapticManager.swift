// OmniSight - Visual Navigation System
// Personal Project - Source Code


import UIKit

// This class makes the phone vibrate for alerts.
class HapticManager {
    static let shared = HapticManager()
    
    private let light = UIImpactFeedbackGenerator(style: .light)
    private let medium = UIImpactFeedbackGenerator(style: .medium)
    private let heavy = UIImpactFeedbackGenerator(style: .heavy)
    private let notification = UINotificationFeedbackGenerator()
    
    private init() {
        light.prepare()
        medium.prepare()
        heavy.prepare()
        notification.prepare()
    }
    
    func smallVibration() {
        // small vibrate
        light.impactOccurred()
    }
    
    func mediumVibration() {
        medium.impactOccurred()
    }
    
    func warningVibration() {
        // BIG VIBRATE FOR WHEN YOU ARE GOING TO HIT SOMETHING
        // DON'T IGNORE THIS
        heavy.impactOccurred()
        notification.notificationOccurred(.error)
    }

    func playObjectNearby() {
        // Single tap for deaf mode
        medium.impactOccurred()
    }

    func playCollisionWarning() {
        // Double tap for deaf mode
        heavy.impactOccurred()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
            self.heavy.impactOccurred()
        }
    }

    func playEmergencyBuzz() {
        // Long buzz for emergency
        notification.notificationOccurred(.error)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
            self.notification.notificationOccurred(.error)
        }
    }

    func playSurfaceDropoff() {
        // Rapid triple pulse for stairs/curbs
        for i in 0..<3 {
            DispatchQueue.main.asyncAfter(deadline: .now() + Double(i) * 0.15) {
                self.medium.impactOccurred()
            }
        }
    }
}
