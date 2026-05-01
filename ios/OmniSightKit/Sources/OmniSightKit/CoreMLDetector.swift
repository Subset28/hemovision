// OmniSight - Visual Navigation System
// Personal Project - Source Code




import CoreML
import Foundation
import Vision

public enum ModelLoadError: Error {
    case fileNotFound(String)
    case modelLoadFailed(Error)
}



public final class CoreMLDetector {
    public let config: VisionConfiguration
    private let visionModel: VNCoreMLModel

    public init(modelURL: URL, config: VisionConfiguration = .defaultConfiguration) throws {
        self.config = config
        let modelConfig = MLModelConfiguration()
        modelConfig.computeUnits = .all
        
        let model = try MLModel(contentsOf: modelURL, configuration: modelConfig)
        self.visionModel = try VNCoreMLModel(for: model)
    }

    public convenience init(modelResourceName: String, bundle: Bundle, config: VisionConfiguration = .defaultConfiguration) throws {
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
            
            // Distance estimation using bounding box area (more robust than height alone)
            let area = width * height
            let distance = max(0.3, 0.35 / sqrt(area))
            let pan = (xCenter - 0.5) * 2.0
            
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
