

import OmniSightKit

import Combine
import SwiftUI

struct ContentView: View {
    @AppStorage("firstTimeUsingApp") private var firstTimeUsingApp: Bool = true
    @ObservedObject var app = AppStateManager.shared
    @ObservedObject var hearing = AppStateManager.shared.speechEngine
    @Environment(\.scenePhase) private var scenePhase

    @AppStorage("debugModeEnabled") private var debugModeEnabled = false

    @State private var speechMutedBanner = false
    @State private var showingSettings   = false
    @State private var showingFindPicker = false
    @State private var debugLines: [String] = []
    @State private var debugLatency = ""
    private let debugRefreshTimer = Timer.publish(every: 0.5, on: .main, in: .common).autoconnect()

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
            
            // Debug overlay — shown when debugModeEnabled, lists recent decisions + latency
            if debugModeEnabled {
                debugOverlay
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                    .padding(.top, 60)
                    .padding(.horizontal, 12)
                    .allowsHitTesting(false)
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

            // Scan Status HUD — above the dock
            VStack {
                Spacer()
                if app.isScanning {
                    scanStatusPill
                        .padding(.bottom, 4)
                }
                modePill
                    .padding(.bottom, 4)
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
        .sheet(isPresented: $showingFindPicker) { findPickerSheet }
        .onReceive(debugRefreshTimer) { _ in refreshDebugOverlay() }
    }

    private func refreshDebugOverlay() {
        guard debugModeEnabled else { return }
        let entries = DecisionLog.shared.entries
        debugLines = entries.suffix(5).reversed().map { $0.formatted }
        let report = PerformanceMonitor.shared.report()
        debugLatency = String(format: "p50 %.0fms  p95 %.0fms  suppress %.0f%%",
            report.latencyP50Ms, report.latencyP95Ms, report.ttsSuppressedRatio * 100)
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

    // Debug overlay — decision log + live latency. Non-interactive, updates at 2fps.
    private var debugOverlay: some View {
        VStack(alignment: .leading, spacing: 2) {
            if !debugLatency.isEmpty {
                Text(debugLatency)
                    .font(.system(size: 9, weight: .bold, design: .monospaced))
                    .foregroundStyle(.green)
                    .padding(.horizontal, 6).padding(.vertical, 2)
                    .background(Color.black.opacity(0.7))
                    .cornerRadius(4)
            }
            ForEach(Array(debugLines.enumerated()), id: \.offset) { _, line in
                Text(line)
                    .font(.system(size: 9, design: .monospaced))
                    .foregroundStyle(.white.opacity(0.85))
                    .lineLimit(1)
                    .truncationMode(.tail)
                    .padding(.horizontal, 6).padding(.vertical, 1)
                    .background(Color.black.opacity(0.6))
                    .cornerRadius(3)
            }
        }
    }

    // Mode pill — shows current mode, tap to switch or cancel finding
    private var modePill: some View {
        Button {
            if app.mode.isFinding {
                app.mode = .navigation
            } else {
                showingFindPicker = true
            }
        } label: {
            HStack(spacing: 6) {
                Image(systemName: app.mode.isFinding ? "magnifyingglass.circle.fill" : "scope")
                    .font(.caption.bold())
                Text(app.mode.isFinding ? app.mode.displayName : "Find Object")
                    .font(.caption.bold())
                if app.mode.isFinding {
                    Image(systemName: "xmark.circle.fill")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .foregroundStyle(app.mode.isFinding ? .yellow : .white)
            .padding(.horizontal, 14)
            .padding(.vertical, 7)
            .background(
                Capsule().fill(app.mode.isFinding ? Color.yellow.opacity(0.2) : Color.white.opacity(0.12))
            )
        }
        .accessibilityLabel(app.mode.isFinding ? "Cancel finding \(app.mode.findingTarget ?? ""). Tap to return to navigation mode." : "Find a specific object. Tap to choose.")
    }

    // Sheet: pick which object to search for
    private var findPickerSheet: some View {
        NavigationStack {
            List(findableObjects, id: \.self) { obj in
                Button {
                    app.mode = .finding(target: obj)
                    showingFindPicker = false
                } label: {
                    Label(obj.replacingOccurrences(of: "_", with: " ").capitalized,
                          systemImage: iconForObject(obj))
                }
                .foregroundStyle(.primary)
            }
            .navigationTitle("Find Object")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { showingFindPicker = false }
                }
            }
        }
        .preferredColorScheme(.dark)
    }

    private func iconForObject(_ obj: String) -> String {
        switch obj {
        case "person":    return "person.fill"
        case "chair":     return "chair.lounge.fill"
        case "car", "truck", "bus": return "car.fill"
        case "bicycle", "motorcycle": return "bicycle"
        case "door":      return "door.left.hand.open"
        case "stairs":    return "staircase"
        case "dog", "cat": return "pawprint.fill"
        default:          return "viewfinder"
        }
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

    private var scanStatusPill: some View {
        let objects  = app.session?.lastPayload?.objects ?? []
        let count    = hearing.objectCount
        let closest  = objects.min(by: { $0.distanceM < $1.distanceM })

        let label: String = {
            guard count > 0, let obj = closest else { return "Scanning..." }
            let dist = String(format: "%.1fm", obj.distanceM)
            let name = obj.objectClass.capitalized
            if count == 1 { return "\(name)  \(dist)" }
            return "\(count) objects  •  \(name) \(dist)"
        }()

        return Text(label)
            .font(.caption.bold())
            .foregroundStyle(.white)
            .padding(.horizontal, 14)
            .padding(.vertical, 7)
            .background(Capsule().fill(.black.opacity(0.6)))
            .accessibilityLabel(count > 0 ? "\(count) objects detected. Closest: \(label)" : "Scanning")
            .animation(.easeInOut(duration: 0.2), value: label)
    }
}

#Preview {
    ContentView()
}
