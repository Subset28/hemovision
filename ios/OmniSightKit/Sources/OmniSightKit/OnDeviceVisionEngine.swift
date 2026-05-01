// OmniSight - Visual Navigation System
// Personal Project - Source Code



import CoreVideo
import Foundation
import ImageIO
import QuartzCore
import Vision

#if canImport(ARKit)
import ARKit
#endif

// OmniSight Vision Engine
// Primary logic for object detection and processing.. It uses YOLOv8 to see things.
public class OnDeviceVisionEngine {
    // SINGLETON FOR THE TEAM
    public static var shared: OnDeviceVisionEngine? 

    public var config: VisionConfiguration 
    private let detector: CoreMLDetector
    private var tracker: ObjectTracker
    private let workQueue: DispatchQueue
    
    private var frameId: Int = 0
    private var inFlight: Bool = false
    private var lastEmitTime: TimeInterval = 0
    
    public init(detector: CoreMLDetector) {
        self.detector = detector
        self.config = detector.config
        let tr = ObjectTracker(highPriorityDistanceM: detector.config.highPriorityDistanceM)
        self.tracker = tr
        self.workQueue = DispatchQueue(label: "com.OmniSight.vision", qos: .userInitiated)
    }


    public func process(
        pixelBuffer: CVPixelBuffer,
        orientation: CGImagePropertyOrientation,
        intrinsics: CameraIntrinsics? = nil,
        depthMap: CVPixelBuffer? = nil,
        completion: @escaping (FramePayload?) -> Void
    ) {
        workQueue.async { [weak self] in
            self?.processOnWorkQueue(
                pixelBuffer: pixelBuffer,
                orientation: orientation,
                intrinsics: intrinsics,
                depthMap: depthMap,
                completion: completion
            )
        }
    }

    private func processOnWorkQueue(
        pixelBuffer: CVPixelBuffer,
        orientation: CGImagePropertyOrientation,
        intrinsics: CameraIntrinsics?,
        depthMap: CVPixelBuffer?,
        completion: @escaping (FramePayload?) -> Void
    ) {
        let w = CVPixelBufferGetWidth(pixelBuffer)
        let h = CVPixelBufferGetHeight(pixelBuffer)

        if inFlight { return }
        
        let now = CACurrentMediaTime()
        if now - lastEmitTime < config.minEmitInterval * 0.9 { return }
        
        inFlight = true
        let t0 = CACurrentMediaTime()

        let request = detector.makeRequest { [weak self, depthMap] request, err in
            guard let self else { return }
            self.inFlight = false
            
            let dummyIntrinsics = CameraIntrinsics.evalOnlyFromFrameDimensions(width: w, height: h, horizontalFOVDeg: 63)
            
            let raw = self.detector.buildObservations(
                from: request,
                error: err,
                imageWidth: w,
                imageHeight: h,
                intrinsics: intrinsics ?? dummyIntrinsics
            ).filter { detection in
                guard let allowed = self.config.allowedClasses else { return true }
                return allowed.contains(detection.className.lowercased())
            }
            
            self.frameId += 1
            let t1 = CACurrentMediaTime()
            let mapped = self.tracker.update(detections: raw, now: t1, frameIndex: self.frameId)
            self.lastEmitTime = t1
            let visionMs = max(0, min(1_000_000, Int((t1 - t0) * 1000)))

            var dtos: [DetectedObjectDTO] = []

            for o in mapped {
                var distance = o.distanceM
                var confidence: DistanceConfidence = .estimated
                
                if depthMap != nil {
                    // FIXME: The LiDAR gets jumpy near glass windows. We need to find a better filter for Nationals..
                    let lidarDepth = depthMap!.sampleDepth(at: CGPoint(x: o.xCenterNorm, y: o.yCenterNorm)) ?? 999.0
                    
                    var useLidar = true
                    
                    if let allowed = config.allowedClasses, allowed.contains("tree") || allowed.contains("building") {
                        let isNature = o.className.lowercased() == "tree" || o.className.lowercased() == "building"
                        if isNature && lidarDepth < 2.0 && o.distanceM > 4.0 {
                            useLidar = false 
                        }
                    }

                    if useLidar {
                        distance = Double(lidarDepth)
                        confidence = .measured
                    }
                }

                dtos.append(
                    DetectedObjectDTO(
                        objectId: o.objectId,
                        objectClass: o.className,
                        confidence: (o.confidence * 100).rounded() / 100,
                        bbox: BBoxNorm(
                            xCenterNorm: o.xCenterNorm,
                            yCenterNorm: o.yCenterNorm,
                            widthNorm: o.widthNorm,
                            heightNorm: o.heightNorm
                        ),
                        distanceM: (distance * 100).rounded() / 100,
                        distanceConfidence: confidence,
                        panValue: o.panValue,
                        velocityMps: (o.velocityMps * 100).rounded() / 100,
                        priority: o.priority
                    )
                )
            }

            let payload = FramePayload(
                frameId: self.frameId,
                timestampMs: Int64(Date().timeIntervalSince1970 * 1000),
                visionDurationMs: visionMs,
                objects: dtos,
                camera: nil
            )
            DispatchQueue.main.async { completion(payload) }
        }

        do {
            let handler = VNImageRequestHandler(
                cvPixelBuffer: pixelBuffer,
                orientation: orientation,
                options: [:]
            )
            try handler.perform([request])
        } catch {
            inFlight = false
            // This is bad, the vision system crashed.
            print("ERROR: Vision system just died! Check the model file!")
        }
    }

    public func resetTracker() {
        workQueue.async { [self] in
            self.tracker = ObjectTracker(highPriorityDistanceM: self.config.highPriorityDistanceM)
        }
    }
}
