



import CoreML
import Foundation
import Vision

public enum ModelLoadError: Error {
    case fileNotFound(String)
    case modelLoadFailed(Error)
}



public final class CoreMLDetector {
    public let config: ScannerConfiguration
    private let visionModel: VNCoreMLModel

    // Typical upright heights (meters) for focal-length distance estimation.
    // distance = (realHeight × focalLengthPx) / (detectedHeightPx)
    // Classes absent from this table fall back to the area heuristic.
    private static let knownHeights: [String: Double] = [
        "person":       1.70,
        "bicycle":      1.10,
        "car":          1.50,
        "motorcycle":   1.20,
        "bus":          3.00,
        "truck":        2.80,
        "dog":          0.55,
        "cat":          0.35,
        "chair":        0.90,
        "dining table": 0.75,
        "table":        0.75,
        "door":         2.10,
        "stairs":       0.20,
        "fire hydrant": 0.60,
        "stop sign":    1.80,
        "backpack":     0.50,
        "suitcase":     0.65,
        "bottle":       0.28,
        "traffic light": 0.90,
    ]

    public init(modelURL: URL, config: ScannerConfiguration = .defaultConfiguration) throws {
        self.config = config
        let modelConfig = MLModelConfiguration()
        modelConfig.computeUnits = .all
        
        let model = try MLModel(contentsOf: modelURL, configuration: modelConfig)
        self.visionModel = try VNCoreMLModel(for: model)
    }

    public convenience init(modelResourceName: String, bundle: Bundle, config: ScannerConfiguration = .defaultConfiguration) throws {
        let url = bundle.url(forResource: modelResourceName, withExtension: "mlmodelc") ?? 
                  bundle.url(forResource: modelResourceName, withExtension: "mlpackage")
        
        guard let u = url else {
            throw ModelLoadError.fileNotFound(modelResourceName)
        }
        try self.init(modelURL: u, config: config)
    }

    public func makeRequest(handler: @escaping VNRequestCompletionHandler) -> VNCoreMLRequest {
        let request = VNCoreMLRequest(model: visionModel, completionHandler: handler)
        request.imageCropAndScaleOption = .scaleFill
        return request
    }

    func buildObservations(
        from request: VNRequest,
        error: Error?,
        imageWidth: Int,
        imageHeight: Int,
        intrinsics: CameraIntrinsics
    ) -> [RawDetection] {
        guard let results = request.results as? [VNRecognizedObjectObservation] else {
            return []
        }

        var finalDetections: [RawDetection] = []
        
        for observation in results {
            guard let topLabel = observation.labels.first else { continue }
            if topLabel.confidence < config.confidenceThreshold {
                continue
            }
            
            let rect = observation.boundingBox
            let xCenter = Double(rect.midX)
            let yCenter = Double(1.0 - rect.midY) // Vision is Y-up, we want Y-down
            let width = Double(rect.width)
            let height = Double(rect.height)
            
            // Distance estimate using focal-length geometry when a known height is available:
            //   distance_m = (realHeight_m × focalLength_px) / (heightNorm × frameHeight_px)
            // Falls back to the area heuristic for unlisted classes.
            let area = width * height
            let pan  = (xCenter - 0.5) * 2.0
            let focalPx = intrinsics.focalLengthPx
            let frameH  = Double(intrinsics.frameHeight)
            let distance: Double = {
                if let rh = CoreMLDetector.knownHeights[topLabel.identifier.lowercased()],
                   height > 0.02, focalPx > 10, frameH > 100 {
                    let detH = height * frameH
                    return max(0.3, (rh * focalPx) / detH)
                }
                return max(0.3, 0.35 / sqrt(area))
            }()
            
            let item = RawDetection(
                className: topLabel.identifier,
                confidence: Double(topLabel.confidence),
                xCenterNorm: xCenter,
                yCenterNorm: yCenter,
                widthNorm: width,
                heightNorm: height,
                distanceM: distance,
                panValue: pan
            )
            finalDetections.append(item)
        }
        
        return finalDetections
    }
}
