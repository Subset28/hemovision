

import UIKit

class HapticManager {
    static let shared = HapticManager()

    private let light        = UIImpactFeedbackGenerator(style: .light)
    private let medium       = UIImpactFeedbackGenerator(style: .medium)
    private let notification = UINotificationFeedbackGenerator()

    private var hapticsEnabled: Bool {
        (UserDefaults.standard.object(forKey: "hapticsEnabled") as? Bool) ?? true
    }

    private init() {
        light.prepare()
        medium.prepare()
        notification.prepare()
    }

    func smallVibration() {
        guard hapticsEnabled else { return }
        light.impactOccurred()
    }

    func mediumVibration() {
        guard hapticsEnabled else { return }
        medium.impactOccurred()
    }

    func warningVibration() {
        guard hapticsEnabled else { return }
        notification.notificationOccurred(.error)
    }
}
