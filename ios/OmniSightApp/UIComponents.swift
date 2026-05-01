// OmniSight - Visual Navigation System
// Personal Project - Source Code


import OmniSightKit


import AVFoundation
import SwiftUI
import UIKit

import ARKit

#if os(iOS)
/// Renders the ARKit camera preview.
struct ARViewPreview: UIViewRepresentable {
    let session: ARSession

    func makeUIView(context: Context) -> ARSCNView {
        let v = ARSCNView()
        v.session = session
        v.automaticallyUpdatesLighting = true
        v.preferredFramesPerSecond = 60
        v.rendersCameraGrain = true
        return v
    }

    func updateUIView(_ uiView: ARSCNView, context: Context) {
        if uiView.session !== session {
            uiView.session = session
        }
    }
}
#endif

/// Renders bounding boxes over the camera feed.
struct BoundingBoxOverlayView: View {
    var objects: [DetectedObjectDTO]
    
    var body: some View {
        GeometryReader { geo in
            ForEach(objects, id: \.objectId) { obj in
                let w = CGFloat(obj.bbox.widthNorm) * geo.size.width
                let h = CGFloat(obj.bbox.heightNorm) * geo.size.height
                let cx = CGFloat(obj.bbox.xCenterNorm) * geo.size.width
                let cy = CGFloat(obj.bbox.yCenterNorm) * geo.size.height
                
                let isHigh = obj.priority.uppercased() == "HIGH"
                let color: Color = isHigh ? OmniSightTheme.warmAlert : OmniSightTheme.accent
                
                ZStack(alignment: .topLeading) {
                    Rectangle()
                        .stroke(color, lineWidth: 2)
                        .frame(width: w, height: h)
                    
                    Text("\(obj.objectClass.capitalized) \(String(format: "%.1fm", obj.distanceM))")
                        .font(.caption.bold())
                        .foregroundColor(Color.black)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 3)
                        .background(color)
                        .cornerRadius(4)
                        .offset(y: -24)
                }
                .frame(width: w, height: h)
                .position(x: cx, y: cy)
                .shadow(color: Color.black.opacity(0.6), radius: 2, x: 0, y: 1)
            }
        }
    }
}

/// A simple UIViewRepresentable to catch two-finger double-taps.
struct TwoFingerDoubleTapCapture: UIViewRepresentable {
    var onDetected: () -> Void

    func makeUIView(context: Context) -> UIView {
        let view = UIView()
        view.backgroundColor = .clear
        
        let gesture = UITapGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.handleTap))
        gesture.numberOfTapsRequired = 2
        gesture.numberOfTouchesRequired = 2
        view.addGestureRecognizer(gesture)
        
        return view
    }

    func updateUIView(_ uiView: UIView, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator(onDetected: onDetected)
    }

    class Coordinator: NSObject {
        var onDetected: () -> Void
        init(onDetected: @escaping () -> Void) {
            self.onDetected = onDetected
        }
        @objc func handleTap() {
            onDetected()
        }
    }
}
