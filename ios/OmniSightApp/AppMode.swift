
import Foundation

// AppMode — controls what OmniSight scans for and how it reports.
//
//   .navigation    — standard: warn about obstacles, announce nearby objects.
//   .finding(cls)  — focus: suppress all speech except when `cls` is detected;
//                    repeat its direction+distance until dismissed.

enum AppMode: Equatable {
    case navigation
    case finding(target: String)

    var displayName: String {
        switch self {
        case .navigation:       return "Navigation"
        case .finding(let t):   return "Finding: \(t.capitalized)"
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
}

// Objects users can actively search for (superset of whitelist, filtered at runtime)
let findableObjects: [String] = [
    "person", "chair", "table", "door", "stairs",
    "car", "truck", "bus", "bicycle", "motorcycle",
    "dog", "cat", "bottle", "backpack", "suitcase", "fire hydrant",
]
