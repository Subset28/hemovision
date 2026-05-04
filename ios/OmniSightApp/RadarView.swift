// OmniSight - Visual Navigation System
// Personal Project - Source Code

import SwiftUI
import OmniSightKit

/// A tactical top-down radar view that maps 3D object positions to a 2D interface.
struct RadarView: View {
    let objects: [DetectedObjectDTO]
    @State private var sonarPulse: CGFloat = 0.0
    
    var body: some View {
        ZStack {
            // Radar Background Rings
            Circle()
                .stroke(Color.white.opacity(0.1), lineWidth: 1)
                .scaleEffect(0.33)
            Circle()
                .stroke(Color.white.opacity(0.1), lineWidth: 1)
                .scaleEffect(0.66)
            Circle()
                .stroke(OmniSightTheme.accent.opacity(0.2), lineWidth: 2)
                .scaleEffect(1.0)
            
            // Sonar Pulse
            Circle()
                .stroke(OmniSightTheme.accent.opacity(0.3), lineWidth: 2)
                .scaleEffect(sonarPulse)
                .opacity(1.0 - sonarPulse)
            
            // Crosshair
            Rectangle()
                .fill(Color.white.opacity(0.1))
                .frame(width: 1, height: 10)
                .offset(y: -100)
            Rectangle()
                .fill(Color.white.opacity(0.1))
                .frame(width: 1, height: 10)
                .offset(y: 100)
            Rectangle()
                .fill(Color.white.opacity(0.1))
                .frame(width: 10, height: 1)
                .offset(x: -100)
            Rectangle()
                .fill(Color.white.opacity(0.1))
                .frame(width: 10, height: 1)
                .offset(x: 100)
            
            // Center (User Position)
            Image(systemName: "location.north.fill")
                .font(.system(size: 14))
                .foregroundColor(OmniSightTheme.accent)
            
            // Objects
            GeometryReader { geo in
                let center = CGPoint(x: geo.size.width / 2, y: geo.size.height / 2)
                let radius = min(geo.size.width, geo.size.height) / 2
                
                ForEach(objects, id: \.objectId) { obj in
                    RadarBlip(obj: obj, center: center, maxRadius: radius)
                }
            }
        }
        .aspectRatio(1, contentMode: .fit)
        .onAppear {
            withAnimation(.linear(duration: 2.0).repeatForever(autoreverses: false)) {
                sonarPulse = 1.0
            }
        }
    }
}

private struct RadarBlip: View {
    let obj: DetectedObjectDTO
    let center: CGPoint
    let maxRadius: CGFloat
    
    // Convert polar (pan/dist) to cartesian (x/y)
    // panValue is -1.0 to 1.0 (approx -60 to 60 degrees)
    // distM is 0.0 to 12.0+
    var blipPosition: CGPoint {
        let angle = CGFloat(obj.panValue) * 0.7 // Map to approx 40 degrees
        let dist = min(CGFloat(obj.distanceM), 10.0) // Cap at 10m for radar
        let normalizedDist = dist / 10.0
        
        let x = center.x + normalizedDist * maxRadius * sin(angle)
        let y = center.y - normalizedDist * maxRadius * cos(angle)
        
        return CGPoint(x: x, y: y)
    }
    
    var body: some View {
        let isHigh = obj.priority.uppercased() == "HIGH"
        
        ZStack {
            Circle()
                .fill(isHigh ? OmniSightTheme.warmAlert : OmniSightTheme.accent)
                .frame(width: 8, height: 8)
                .shadow(color: (isHigh ? OmniSightTheme.warmAlert : OmniSightTheme.accent).opacity(0.6), radius: 4)
            
            // Velocity Trail (Static preview of movement)
            if abs(obj.velocityMps) > 0.5 {
                Rectangle()
                    .fill(Gradient(colors: [(isHigh ? OmniSightTheme.warmAlert : OmniSightTheme.accent), .clear]))
                    .frame(width: 2, height: 15)
                    .rotationEffect(.radians(Double(obj.panValue) * 0.7)) // Simplify for trail
                    .offset(y: obj.velocityMps > 0 ? 10 : -10)
            }
        }
        .position(blipPosition)
        .animation(.spring(response: 0.3, dampingFraction: 0.6), value: blipPosition)
    }
}

#Preview {
    RadarView(objects: [])
        .frame(width: 300, height: 300)
        .background(Color.black)
}
