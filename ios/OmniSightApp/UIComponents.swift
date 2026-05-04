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
                    // Corner-style bounding box (more technical than a full rectangle)
                    BoundingBoxCorners(color: color)
                        .frame(width: w, height: h)
                    
                    // Velocity Vector Arrow
                    if abs(obj.velocityMps) > 0.4 {
                        VelocityArrow(velocity: obj.velocityMps, color: color)
                            .offset(x: w/2, y: h/2)
                    }

                    VStack(alignment: .leading, spacing: 2) {
                        HStack(spacing: 4) {
                            Image(systemName: iconForClass(obj.objectClass))
                            Text(obj.objectClass.capitalized)
                        }
                        .font(.caption.bold())
                        .foregroundColor(.black)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 3)
                        .background(color)
                        .cornerRadius(4)
                        
                        Text(String(format: "%.1fm", obj.distanceM))
                            .font(.caption2.bold())
                            .foregroundColor(.white)
                            .padding(.horizontal, 4)
                            .background(Color.black.opacity(0.6))
                            .cornerRadius(2)
                    }
                    .offset(y: -35)
                }
                .frame(width: w, height: h)
                .position(x: cx, y: cy)
                .shadow(color: Color.black.opacity(0.6), radius: 2, x: 0, y: 1)
                .animation(.easeInOut(duration: 0.2), value: obj.bbox)
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

// MARK: - Advanced Visuals

struct BoundingBoxCorners: View {
    let color: Color
    var body: some View {
        ZStack {
            VStack {
                HStack {
                    corner.rotationEffect(.degrees(0)); Spacer(); corner.rotationEffect(.degrees(90))
                }
                Spacer()
                HStack {
                    corner.rotationEffect(.degrees(-90)); Spacer(); corner.rotationEffect(.degrees(180))
                }
            }
        }
    }
    
    private var corner: some View {
        Path { path in
            path.move(to: CGPoint(x: 0, y: 10))
            path.addLine(to: .zero)
            path.addLine(to: CGPoint(x: 10, y: 0))
        }
        .stroke(color, lineWidth: 2)
        .frame(width: 10, height: 10)
    }
}

struct VelocityArrow: View {
    let velocity: Double
    let color: Color
    
    var body: some View {
        let isApproaching = velocity < 0
        Image(systemName: isApproaching ? "chevron.down.circle.fill" : "chevron.up.circle.fill")
            .font(.system(size: 24))
            .foregroundColor(color)
            .opacity(0.8)
            .scaleEffect(isApproaching ? 1.2 : 0.8)
            .animation(.easeInOut(duration: 0.5).repeatForever(), value: velocity)
    }
}

private func iconForClass(_ cls: String) -> String {
    switch cls.lowercased() {
    case "person": return "person.fill"
    case "car", "truck", "bus": return "car.fill"
    case "bicycle", "motorcycle": return "bicycle"
    case "dog", "cat": return "pawprint.fill"
    case "chair", "table": return "chair.lounge.fill"
    case "door": return "door.right.hand.closed"
    case "stairs": return "stair.fill"
    default: return "questionmark.circle.fill"
    }
}
