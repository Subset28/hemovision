


import Foundation
import CoreGraphics
import AVFoundation

public enum DistanceConfidence: String, Codable, Sendable {
    case estimated
    case measured
}



public struct RawDetection: Codable, Equatable, Sendable {
    public var className: String
    public var confidence: Double
    public var xCenterNorm: Double
    public var yCenterNorm: Double
    public var widthNorm: Double
    public var heightNorm: Double
    public var distanceM: Double
    public var panValue: Double

    public init(className: String, confidence: Double, xCenterNorm: Double, yCenterNorm: Double, widthNorm: Double, heightNorm: Double, distanceM: Double, panValue: Double) {
        self.className = className
        self.confidence = confidence
        self.xCenterNorm = xCenterNorm
        self.yCenterNorm = yCenterNorm
        self.widthNorm = widthNorm
        self.heightNorm = heightNorm
        self.distanceM = distanceM
        self.panValue = panValue
    }
}

public struct BBoxNorm: Codable, Equatable, Sendable {
    public var xCenterNorm: Double
    public var yCenterNorm: Double
    public var widthNorm: Double
    public var heightNorm: Double

    enum CodingKeys: String, CodingKey {
        case xCenterNorm = "x_center_norm"
        case yCenterNorm = "y_center_norm"
        case widthNorm = "width_norm"
        case heightNorm = "height_norm"
    }

    public init(xCenterNorm: Double, yCenterNorm: Double, widthNorm: Double, heightNorm: Double) {
        self.xCenterNorm = xCenterNorm
        self.yCenterNorm = yCenterNorm
        self.widthNorm = widthNorm
        self.heightNorm = heightNorm
    }
}

public struct DetectedObjectDTO: Codable, Equatable, Sendable {
    public var objectId: String
    public var objectClass: String
    public var confidence: Double
    public var bbox: BBoxNorm
    public var distanceM: Double
    public var distanceConfidence: DistanceConfidence?
    public var panValue: Double
    public var velocityMps: Double
    public var priority: String

    enum CodingKeys: String, CodingKey {
        case objectId = "object_id"
        case objectClass = "class"
        case confidence
        case bbox
        case distanceM = "distance_m"
        case distanceConfidence = "distance_confidence"
        case panValue = "pan_value"
        case velocityMps = "velocity_mps"
        case priority
    }
}

public struct CameraHealthDTO: Codable, Equatable, Sendable {
    public var lensStatus: String
    public var lensLaplacianVar: Double
    public var lensAnnounce: String?

    enum CodingKeys: String, CodingKey {
        case lensStatus = "lens_status"
        case lensLaplacianVar = "lens_laplacian_var"
        case lensAnnounce = "lens_announce"
    }

    public init(lensStatus: String, lensLaplacianVar: Double, lensAnnounce: String?) {
        self.lensStatus = lensStatus
        self.lensLaplacianVar = lensLaplacianVar
        self.lensAnnounce = lensAnnounce
    }
}

public struct FramePayload: Codable, Equatable, Sendable {
    public var frameId: Int
    public var timestampMs: Int64
    public var visionDurationMs: Int
    public var objects: [DetectedObjectDTO]
    public var camera: CameraHealthDTO?

    enum CodingKeys: String, CodingKey {
        case frameId = "frame_id"
        case timestampMs = "timestamp_ms"
        case visionDurationMs = "vision_duration_ms"
        case objects
        case camera
    }

    public init(frameId: Int, timestampMs: Int64, visionDurationMs: Int, objects: [DetectedObjectDTO], camera: CameraHealthDTO? = nil) {
        self.frameId = frameId
        self.timestampMs = timestampMs
        self.visionDurationMs = visionDurationMs
        self.objects = objects
        self.camera = camera
    }
}

extension FramePayload {
    public func jsonData(prettyPrinted: Bool = false) throws -> Data {
        let enc = JSONEncoder()
        if prettyPrinted { enc.outputFormatting = [.sortedKeys, .prettyPrinted] }
        return try enc.encode(self)
    }

    public func jsonString(prettyPrinted: Bool = false) throws -> String {
        let data = try jsonData(prettyPrinted: prettyPrinted)
        return String(data: data, encoding: .utf8) ?? "{}"
    }
}



public struct ScannerConfiguration: Sendable {
    public var confidenceThreshold: Float = 0.4
    public var minEmitInterval: TimeInterval = 0.05
    public var highPriorityDistanceM: Double = 1.5
    public var allowedClasses: Set<String>? = nil
    
    public init() {}
    public static var defaultConfiguration: ScannerConfiguration {
        return ScannerConfiguration()
    }
}



public struct VisionGeometry {
    public static func mapToRect(xCenter: Double, yCenter: Double, width: Double, height: Double, targetRect: CGRect) -> CGRect {
        let x = (xCenter - width / 2) * Double(targetRect.width) + Double(targetRect.minX)
        let y = (yCenter - height / 2) * Double(targetRect.height) + Double(targetRect.minY)
        let w = width * Double(targetRect.width)
        let h = height * Double(targetRect.height)
        return CGRect(x: x, y: y, width: w, height: h)
    }
}

public class SpeechSynthesizer: NSObject, AVSpeechSynthesizerDelegate {
    private let synthesizer = AVSpeechSynthesizer()
    public var onDidFinishSpeaking: (() -> Void)?
    
    public override init() {
        super.init()
        synthesizer.delegate = self
    }
    
    public func speak(_ text: String, rate: Float = AVSpeechUtteranceDefaultSpeechRate) {
        let utterance = AVSpeechUtterance(string: text)
        utterance.rate = rate
        utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
        synthesizer.speak(utterance)
    }
    
    public func stop() {
        synthesizer.stopSpeaking(at: .immediate)
    }
    
    public func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        onDidFinishSpeaking?()
    }
}



extension CVPixelBuffer {
    // Reads a depth value from normalized coordinates (0.0-1.0). Returns nil if out of range.
    public func sampleDepth(at point: CGPoint) -> Float? {
        CVPixelBufferLockBaseAddress(self, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(self, .readOnly) }

        let width = CVPixelBufferGetWidth(self)
        let height = CVPixelBufferGetHeight(self)
        
        let x = Int(point.x * CGFloat(width))
        let y = Int(point.y * CGFloat(height))
        
        guard x >= 0 && x < width && y >= 0 && y < height else { return nil }
        
        guard let baseAddress = CVPixelBufferGetBaseAddress(self) else { return nil }
        let bytesPerRow = CVPixelBufferGetBytesPerRow(self)
        let pixelData = baseAddress.assumingMemoryBound(to: Float32.self)
        
        let stride = bytesPerRow / MemoryLayout<Float32>.stride
        let depth = pixelData[y * stride + x]
        
        // Return valid readings (usually between 0.1m and 10.0m for LiDAR)
        return (depth > 0.1 && depth < 20.0) ? depth : nil
    }
}
