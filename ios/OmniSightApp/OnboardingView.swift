

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
        GeometryReader { geo in
            VStack(spacing: 0) {
                TabView(selection: $currentPage) {
                    ForEach(0..<pages.count, id: \.self) { i in
                        OnboardingContent(page: pages[i], availableHeight: geo.size.height)
                            .tag(i)
                    }
                }
                .tabViewStyle(.page)
                .frame(height: geo.size.height - buttonAreaHeight(geo))

                Button(action: {
                    if currentPage < pages.count - 1 {
                        withAnimation { currentPage += 1 }
                    } else {
                        firstTimeUsingApp = false
                    }
                }) {
                    Text(currentPage == pages.count - 1 ? "Get Started" : "Continue")
                        .bold()
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, geo.size.height < 600 ? 12 : 16)
                        .background(Color.mint)
                        .foregroundColor(.black)
                        .cornerRadius(12)
                }
                .padding(.horizontal)
                .padding(.bottom, geo.safeAreaInsets.bottom > 0 ? geo.safeAreaInsets.bottom : 16)
                .padding(.top, 8)
            }
        }
        .background(Color.black.ignoresSafeArea())
    }

    private func buttonAreaHeight(_ geo: GeometryProxy) -> CGFloat {
        let bottomPad = geo.safeAreaInsets.bottom > 0 ? geo.safeAreaInsets.bottom : 16
        let btnHeight: CGFloat = geo.size.height < 600 ? 46 : 54
        return btnHeight + 8 + 16 + bottomPad
    }
}

private struct OnboardingPage {
    let title: String
    let description: String
    let icon: String
}

private struct OnboardingContent: View {
    let page: OnboardingPage
    let availableHeight: CGFloat

    // Scale the icon down on small screens so nothing overflows
    private var iconSize: CGFloat {
        availableHeight < 600 ? 56 : 80
    }

    var body: some View {
        ScrollView {
            VStack(spacing: availableHeight < 600 ? 12 : 20) {
                Spacer(minLength: availableHeight < 600 ? 24 : 40)

                Image(systemName: page.icon)
                    .font(.system(size: iconSize))
                    .foregroundColor(.mint)

                Text(page.title)
                    .font(availableHeight < 600 ? .title2 : .title)
                    .bold()
                    .minimumScaleFactor(0.8)

                Text(page.description)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal)
                    .minimumScaleFactor(0.85)

                Spacer(minLength: availableHeight < 600 ? 16 : 40)
            }
        }
        .scrollDisabled(availableHeight >= 600)
        .foregroundColor(.white)
    }
}
