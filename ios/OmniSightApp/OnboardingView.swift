

import OmniSightKit


import SwiftUI

struct OnboardingView: View {
    @Binding var firstTimeUsingApp: Bool
    @State private var currentPage = 0

    private let pages: [OnboardingPage] = [
        OnboardingPage(
            title: "Your Vision Assistant",
            description: "OmniSight helps you navigate the world by identifying objects and telling you where they are using audio.",
            icon: "person.fill"
        ),
        OnboardingPage(
            title: "Spatial Awareness",
            description: "The app scans for cars, people, and obstacles in front of you and warns you before you get too close.",
            icon: "eye.fill"
        ),
        OnboardingPage(
            title: "Safety Alerts",
            description: "We prioritize important alerts so you hear about the most dangerous things first.",
            icon: "exclamationmark.triangle.fill"
        ),
    ]

    var body: some View {
        VStack {
            TabView(selection: $currentPage) {
                ForEach(0..<pages.count, id: \.self) { i in
                    OnboardingContent(page: pages[i])
                        .tag(i)
                }
            }
            .tabViewStyle(.page)
            
            Button(action: {
                if currentPage < pages.count - 1 {
                    currentPage += 1
                } else {
                    firstTimeUsingApp = false
                }
            }) {
                Text(currentPage == pages.count - 1 ? "Get Started" : "Continue")
                    .bold()
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(Color.mint)
                    .foregroundColor(.black)
                    .cornerRadius(12)
            }
            .padding()
        }
        .background(Color.black.ignoresSafeArea())
    }
}

private struct OnboardingPage {
    let title: String
    let description: String
    let icon: String
}

private struct OnboardingContent: View {
    let page: OnboardingPage

    var body: some View {
        VStack(spacing: 20) {
            Image(systemName: page.icon)
                .font(.system(size: 80))
                .foregroundColor(.mint)
            
            Text(page.title)
                .font(.title)
                .bold()
            
            Text(page.description)
                .multilineTextAlignment(.center)
                .padding(.horizontal)
        }
        .foregroundColor(.white)
    }
}
