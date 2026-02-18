// OmniSight - Visual Navigation System
// Personal Project - Humanized Codebase



import CoreGraphics
import Foundation

#if os(iOS)
import AVFoundation
#endif

/// Basic camera intrinsic parameters.
public struct CameraIntrinsics: Sendable, Equatable {
    public var focalLengthPx: Double
    public var frameWidth: Int
    public var frameHeight: Int
    
    public init(focalLengthPx: Double, frameWidth: Int, frameHeight: Int) {
        self.focalLengthPx = focalLengthPx
        self.frameWidth = frameWidth
        self.frameHeight = frameHeight
    }
}

#if os(iOS)
public enum CameraIntrinsicsReader {
    public static func read(device: AVCaptureDevice, frameWidth: Int, frameHeight: Int, sampleBuffer: CMSampleBuffer?) -> CameraIntrinsics {
        let w = Double(frameWidth)
        let hFovRad = Double(device.activeFormat.videoFieldOfView) * .pi / 180.0
        let focalLength = (w / 2.0) / tan(hFovRad / 2.0)
        
        return CameraIntrinsics(focalLengthPx: focalLength, frameWidth: frameWidth, frameHeight: frameHeight)
    }
}
#endif

extension CameraIntrinsics {
    public static func evalOnlyFromFrameDimensions(width: Int, height: Int, horizontalFOVDeg: Double = 63) -> CameraIntrinsics {
        let w = Double(width)
        let hFovRad = horizontalFOVDeg * .pi / 180.0
        let focalLength = (w / 2.0) / tan(hFovRad / 2.0)
        
        return CameraIntrinsics(focalLengthPx: focalLength, frameWidth: width, frameHeight: height)
    }
}

#if os(iOS) && canImport(ARKit)
import ARKit
extension CameraIntrinsicsReader {
    public static func read(from arCamera: ARCamera) -> CameraIntrinsics {
        let w = Double(arCamera.imageResolution.width)
        let fx = Double(arCamera.intrinsics.columns.0.x)
        return CameraIntrinsics(focalLengthPx: fx, frameWidth: Int(arCamera.imageResolution.width), frameHeight: Int(arCamera.imageResolution.height))
    }
}
#endif
