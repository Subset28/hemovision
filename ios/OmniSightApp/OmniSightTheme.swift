// OmniSight - Visual Navigation System
// Personal Project - Humanized Codebase

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

/// A simple panel with a rounded rectangle background.
struct GlassPanel<Content: View>: View {
    var padding: CGFloat = 16
    var cornerRadius: CGFloat = OmniSightTheme.cornerM
    @ViewBuilder var content: () -> Content

    var body: some View {
        content()
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.white.opacity(0.1))
            .cornerRadius(cornerRadius)
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius)
                    .stroke(Color.white.opacity(0.2), lineWidth: 1)
            )
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
