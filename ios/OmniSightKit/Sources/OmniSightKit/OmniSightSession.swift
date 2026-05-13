// OmniSight - Visual Navigation System
// Personal Project - Source Code



import Combine
import CoreVideo
import Foundation
import ImageIO

/// Orchestrates the scanning system by feeding frames to the engine.
public class OmniSightSession: ObservableObject {
    @Published public var lastPayload: FramePayload?
    public var engine: OpticalProcessor

    public init(engine: OpticalProcessor) {
        self.engine = engine
    }

    public func ingest(pixelBuffer: CVPixelBuffer, orientation: CGImagePropertyOrientation, intrinsics: CameraIntrinsics? = nil) {
        engine.process(pixelBuffer: pixelBuffer, orientation: orientation, intrinsics: intrinsics) { payload in
            DispatchQueue.main.async {
                self.lastPayload = payload
            }
        }
    }

    public func clearPayload() {
        lastPayload = nil
    }
}

#if os(iOS) && canImport(ARKit)
import ARKit

extension OmniSightSession {
    /// Ingests a frame from ARKit.
    public func ingest(arFrame: ARFrame) {
        let intrinsics = CameraIntrinsicsReader.read(from: arFrame.camera)
        let image = arFrame.capturedImage
        let depth = arFrame.sceneDepth?.depthMap
        
        // Pass only the buffers we need to avoid retaining the entire ARFrame
        engine.process(pixelBuffer: image, orientation: .right, intrinsics: intrinsics, depthMap: depth) { payload in
            DispatchQueue.main.async {
                self.lastPayload = payload
            }
        }
    }
}
#endif
