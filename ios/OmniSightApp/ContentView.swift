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

            // Controls Overlay
            VStack {
                HStack {
                    // New Accessibility Mode Picker
                    Picker("Mode", selection: Binding(
                        get: { app.mode },
                        set: { app.setMode($0) }
                    )) {
                        ForEach(AccessibilityMode.allCases, id: \.self) { mode in
                            Text(mode.rawValue).tag(mode)
                        }
                    }
                    .pickerStyle(.segmented)
                    .background(.ultraThinMaterial)
                    .cornerRadius(8)
                    
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
                
                if app.mode == .deaf || app.mode == .both {
                    VStack {
                        if !app.currentRoom.isEmpty {
                            Text(app.currentRoom.capitalized)
                                .font(.headline)
                                .padding(12)
                                .background(.black.opacity(0.6))
                                .cornerRadius(12)
                                .padding(.top, 20)
                        }
                        
                        Spacer()
                        
                        Text(app.lastDetection)
                            .font(.system(size: 44, weight: .black))
                            .multilineTextAlignment(.center)
                            .padding()
                            .background(.black.opacity(0.8))
                            .cornerRadius(20)
                            .padding(.bottom, 140)
                            .foregroundColor(.white)
                    }
                }
                
                Spacer()
            }
            .padding()

            // Bottom Scan Dock
            VStack {
                Spacer()
                scanDock
            }
            
            // SOS Overlay
            if app.isSOSActive {
                ZStack {
                    Color.red.ignoresSafeArea()
                    
                    VStack(spacing: 40) {
                        Image(systemName: "exclamationmark.shield.fill")
                            .font(.system(size: 100))
                            .foregroundColor(.white)
                        
                        Text("EMERGENCY SOS")
                            .font(.system(size: 40, weight: .black))
                            .foregroundColor(.white)
                        
                        Text("\(app.sosCountdown)")
                            .font(.system(size: 120, weight: .bold))
                            .foregroundColor(.white)
                        
                        Button {
                            app.cancelSOS()
                        } label: {
                            Text("CANCEL")
                                .font(.title.bold())
                                .foregroundColor(.red)
                                .padding(.horizontal, 40)
                                .padding(.vertical, 20)
                                .background(Capsule().fill(.white))
                        }
                    }
                }
                .transition(.opacity)
                .zIndex(100)
            }
        }
        .background {
            OmniGestureCapture(onDoubleTap: {
                hearing.muteFor(seconds: 10)
                withAnimation(.easeInOut(duration: 0.2)) {
                    speechMutedBanner = true
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + 10) {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        speechMutedBanner = false
                    }
                }
            }, onTripleTap: {
                app.triggerSOS()
            })
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
            .disabled(!app.modelAvailable)
            .padding(.horizontal, 24)
            .padding(.bottom, 40)
        }
    }
}

#Preview {
    ContentView()
}
