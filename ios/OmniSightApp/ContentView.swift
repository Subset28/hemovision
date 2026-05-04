// OmniSight - Visual Navigation System
// Personal Project - Source Code


import OmniSightKit


import SwiftUI

struct ContentView: View {
    @AppStorage("firstTimeUsingApp") private var firstTimeUsingApp: Bool = true
    @ObservedObject var app = AppStateManager.shared
    @ObservedObject var hearing = AppStateManager.shared.speechEngine

    @State private var speechMutedBanner = false
    @State private var showingSettings = false
    @State private var showTacticalRadar = true

    var body: some View {
        Group {
            if firstTimeUsingApp {
                OnboardingView(firstTimeUsingApp: $firstTimeUsingApp)
                    .transition(.opacity.combined(with: .move(edge: .trailing)))
            } else {
                mainDashboard
                    .onAppear {
                        // Start scanning automatically if the model is loaded to make it easier to use.
                        if app.modelAvailable && !app.isScanning {
                            app.setScanning(true)
                        }
                    }
                }
            }
            .onDisappear {
                app.setScanning(false)
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
                if let arSession = app.cameraManager?.arSession {
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
                    
                    if !app.modelAvailable {
                        modelCallout
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

            // Settings & Tactical Toggle
            VStack {
                HStack(alignment: .top) {
                    Button {
                        withAnimation(.spring()) {
                            showTacticalRadar.toggle()
                        }
                        HapticManager.shared.smallVibration()
                    } label: {
                        Image(systemName: showTacticalRadar ? "dot.radiowaves.left.and.right" : "dot.radiowaves.right")
                            .font(.title3)
                            .padding(12)
                            .background(.ultraThinMaterial)
                            .clipShape(Circle())
                    }
                    .accessibilityLabel("Toggle Radar")
                    
                    Spacer()
                    
                    Button {
                        showingSettings = true
                        HapticManager.shared.smallVibration()
                    } label: {
                        Image(systemName: "gearshape.fill")
                            .font(.title3)
                            .padding(12)
                            .background(.ultraThinMaterial)
                            .clipShape(Circle())
                    }
                    .accessibilityLabel("Settings")
                }
                
                if showTacticalRadar && app.isScanning {
                    PremiumGlassPanel {
                        RadarView(objects: app.session?.lastPayload?.objects ?? [])
                            .frame(width: 140, height: 140)
                    }
                    .transition(.move(edge: .trailing).combined(with: .opacity))
                    .frame(maxWidth: .infinity, alignment: .trailing)
                    .padding(.top, 10)
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

    private var modelCallout: some View {
        VStack(spacing: 12) {
            Image(systemName: "exclamationmark.triangle")
                .font(.title)
                .foregroundStyle(.orange)
            Text("Vision Model Missing")
                .font(.headline)
            Text("The detection model is being downloaded or was not found in the app bundle.")
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
                HapticManager.shared.mediumVibration()
            } label: {
                HStack(spacing: 12) {
                    Image(systemName: app.isScanning ? "stop.fill" : "play.fill")
                    Text(app.isScanning ? "STOP SCANNING" : "START SCANNING")
                }
                .font(.headline.bold())
                .foregroundStyle(app.isScanning ? .white : .black)
                .frame(maxWidth: .infinity)
                .frame(height: 64)
                .background(
                    ZStack {
                        if app.isScanning {
                            Color.red.opacity(0.8)
                        } else {
                            OmniSightTheme.accent
                        }
                    }
                )
                .clipShape(RoundedRectangle(cornerRadius: 24))
                .shadow(color: (app.isScanning ? Color.red : OmniSightTheme.accent).opacity(0.3), radius: 15, y: 8)
            }
            .disabled(!app.modelAvailable)
            .padding(.horizontal, 24)
            .padding(.bottom, 40)
        }
    }
}

#Preview {
    ContentView()
}
