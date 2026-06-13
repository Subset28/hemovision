

import OmniSightKit


import SwiftUI

struct ContentView: View {
    @AppStorage("firstTimeUsingApp") private var firstTimeUsingApp: Bool = true
    @ObservedObject var app = AppStateManager.shared
    @ObservedObject var hearing = AppStateManager.shared.speechEngine
    @Environment(\.scenePhase) private var scenePhase

    @State private var speechMutedBanner = false
    @State private var showingSettings = false

    var body: some View {
        Group {
            if firstTimeUsingApp {
                OnboardingView(firstTimeUsingApp: $firstTimeUsingApp)
                    .transition(.opacity.combined(with: .move(edge: .trailing)))
            } else {
                mainDashboard
                    .onAppear {
                        if app.engineAvailable && !app.isScanning {
                            app.setScanning(true)
                        }
                    }
                }
            }
            .onChange(of: scenePhase) { _, newPhase in
                if newPhase == .active && app.engineAvailable && !app.isScanning && !firstTimeUsingApp {
                    app.setScanning(true)
                } else if newPhase == .background {
                    app.setScanning(false)
                }
            }
            .sheet(isPresented: $showingSettings) {
                SettingsView()
            }
        }

    private var mainDashboard: some View {
        ZStack {
            OmniSightTheme.background.ignoresSafeArea()
            
            if app.isScanning {
                // big camera view
                #if os(iOS)
                if app.cameraPermissionDenied {
                    cameraPermissionDeniedView
                } else if let arSession = app.cameraManager?.arSession {
                    ZStack {
                        ARViewPreview(session: arSession)
                            .ignoresSafeArea()

                        BoundingBoxOverlayView(objects: app.session?.lastPayload?.objects ?? [])
                            .ignoresSafeArea()
                    }
                } else {
                    VStack {
                        ProgressView()
                        Text("Starting Camera...")
                            .foregroundStyle(.secondary)
                            .padding(.top, 8)
                    }
                }
                #endif
            } else {
                // when the camera is off
                VStack(spacing: 24) {
                    Spacer()
                    Image(systemName: "eye.circle")
                        .font(.system(size: 80))
                        .foregroundStyle(OmniSightTheme.accent)
                    
                    Text("OmniSight Ready")
                        .font(.title.bold())
                    
                    safetyDisclaimer
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 40)
                    
                    if !app.engineAvailable {
                        engineCallout
                            .padding(.horizontal, 20)
                    }
                    Spacer()
                }
            }
            
            // Mute Banner
            if speechMutedBanner {
                mutedBanner
                    .padding()
                    .frame(maxHeight: .infinity, alignment: .top)
            }

            // Settings Button
            VStack {
                HStack {
                    Spacer()
                    Button {
                        showingSettings = true
                    } label: {
                        Image(systemName: "gearshape.fill")
                            .font(.title2)
                            .padding()
                            .background(Circle().fill(.black.opacity(0.4)))
                    }
                    .accessibilityLabel("Settings")
                }
                Spacer()
            }
            .padding()

            // Bottom Scan Dock
            VStack {
                Spacer()
                scanDock
            }
        }
        .background {
            TwoFingerDoubleTapCapture {
                hearing.muteFor(seconds: 10)
                withAnimation(.easeInOut(duration: 0.2)) {
                    speechMutedBanner = true
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + 10) {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        speechMutedBanner = false
                    }
                }
            }
        }
        .tint(OmniSightTheme.accent)
        .preferredColorScheme(.dark)
    }

    // standard legal text
    private var safetyDisclaimer: some View {
        Text("Assistive only. Distances are estimated and this does not replace a cane, guide dog, or orientation training.")
            .font(.caption)
            .foregroundStyle(.secondary)
            .multilineTextAlignment(.center)
            .accessibilityLabel("Safety note. Assistive only. Distances are estimated and this does not replace cane or guide dog.")
    }

    private var mutedBanner: some View {
        HStack {
            Image(systemName: "speaker.slash.fill")
            Text("Speech muted for 10 seconds")
        }
        .font(.subheadline.bold())
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(Capsule().fill(.black.opacity(0.8)))
        .foregroundStyle(.white)
        .transition(.move(edge: .top).combined(with: .opacity))
    }

    private var cameraPermissionDeniedView: some View {
        VStack(spacing: 16) {
            Image(systemName: "camera.slash.fill")
                .font(.system(size: 60))
                .foregroundStyle(.orange)
            Text("Camera Access Required")
                .font(.title2.bold())
            Text("OmniSight needs camera access to detect obstacles. Go to Settings > Privacy > Camera to enable it.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)
            Button("Open Settings") {
                if let url = URL(string: UIApplication.openSettingsURLString) {
                    UIApplication.shared.open(url)
                }
            }
            .buttonStyle(.borderedProminent)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Camera access required. Open Settings to enable camera permission for OmniSight.")
    }

    private var engineCallout: some View {
        VStack(spacing: 12) {
            Image(systemName: "exclamationmark.triangle")
                .font(.title)
                .foregroundStyle(.orange)
            Text("Scanning Engine Offline")
                .font(.headline)
            Text("Wait, we can't find the detection files. Check the app bundle.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
        .padding()
        .background(RoundedRectangle(cornerRadius: 16).fill(.white.opacity(0.05)))
    }

    private var scanDock: some View {
        HStack {
            Button {
                app.setScanning(!app.isScanning)
            } label: {
                HStack(spacing: 12) {
                    Image(systemName: app.isScanning ? "stop.fill" : "play.fill")
                    Text(app.isScanning ? "STOP SCANNING" : "START SCANNING")
                }
                .font(.headline.bold())
                .foregroundStyle(app.isScanning ? .white : .black)
                .frame(maxWidth: .infinity)
                .frame(height: 60)
                .background(
                    RoundedRectangle(cornerRadius: 20)
                        .fill(app.isScanning ? Color.red.opacity(0.8) : OmniSightTheme.accent)
                )
            }
            .disabled(!app.engineAvailable)
            .padding(.horizontal, 24)
            .padding(.bottom, 40)
        }
    }
}

#Preview {
    ContentView()
}
