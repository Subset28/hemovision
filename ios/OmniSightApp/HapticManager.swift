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
}
