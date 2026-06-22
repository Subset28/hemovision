
import Foundation

// AppMode — controls what OmniSight scans for and how it reports.
//
//   .navigation      — standard: warn about obstacles, announce nearby objects,
//                      fire scene summaries every 6s.
//   .finding(cls)    — focus: suppress all speech except when `cls` is detected;
//                      repeat direction+distance until user dismisses.
//   .hazardPriority  — safety: suppress non-hazard objects entirely; tighter
//                      cooldowns; optimized for dense urban / crossing traffic.

enum AppMode: Equatable, Hashable {
    case navigation
    case finding(target: String)
    case hazardPriority

    var displayName: String {
        switch self {
        case .navigation:       return "Navigation"
        case .finding(let t):   return "Finding: \(t.capitalized)"
        case .hazardPriority:   return "Hazard Priority"
        }
    }

    var isFinding: Bool {
        if case .finding = self { return true }
        return false
    }

    var findingTarget: String? {
        if case .finding(let t) = self { return t }
        return nil
    }

    var isHazardPriority: Bool { self == .hazardPriority }
}

// Objects users can actively search for — must match allWhitelistedClasses exactly,
// otherwise OpticalProcessor filters them before they reach finding mode.
let findableObjects: [String] = [
    "person", "chair", "table", "door", "stairs",
    "car", "truck", "bus", "bicycle", "motorcycle",
    "dog", "cat",
]

// hazardClasses — defined in OmniSightKit (public let hazardClasses) and imported via OmniSightKit
