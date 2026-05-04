// OmniSight - Visual Navigation System
// Personal Project - Source Code

import SwiftUI
import UIKit

/// Shared theme constants for the application.
enum OmniSightTheme {
    static let accent = Color.mint
    static let warmAlert = Color.orange
    static let info = Color.blue
    static let background = Color(white: 0.05)
    
    static let cornerL: CGFloat = 20
    static let cornerM: CGFloat = 12
    static let cornerS: CGFloat = 8
}

/// A premium glass panel with background blurring (UltraThinMaterial).
struct PremiumGlassPanel<Content: View>: View {
    var cornerRadius: CGFloat = OmniSightTheme.cornerM
    @ViewBuilder var content: () -> Content

    var body: some View {
        content()
            .padding(16)
            .background(.ultraThinMaterial)
            .cornerRadius(cornerRadius)
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius)
                    .stroke(.white.opacity(0.15), lineWidth: 0.5)
            )
            .shadow(color: .black.opacity(0.2), radius: 10, x: 0, y: 5)
    }
}

/// A simple wrapper for sharing items.
struct ActivityViewController: UIViewControllerRepresentable {
    let activityItems: [Any]

    func makeUIViewController(context _: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: activityItems, applicationActivities: nil)
    }

    func updateUIViewController(_: UIActivityViewController, context _: Context) {}
}
