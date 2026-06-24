
import OmniSightKit
import SwiftUI

struct SettingsView: View {
    @Environment(\.dismiss) var dismiss
    @ObservedObject var app   = AppStateManager.shared
    @ObservedObject var bench = BenchmarkSession.shared

    // Speech
    @AppStorage("verbosityMode")       private var verbosityRaw:       String = "normal"
    @AppStorage("speechRate")          private var speechRate:         Double = 0.52
    @AppStorage("useImperialUnits")    private var useImperialUnits:   Bool   = false
    @AppStorage("sceneCooldown")       private var sceneCooldown:      Double = 6.0

    // Awareness
    @AppStorage("hazardAlarmsEnabled") private var hazardAlarmsEnabled: Bool   = true
    @AppStorage("hapticsEnabled")      private var hapticsEnabled:      Bool   = true
    @AppStorage("stepDetectionEnabled") private var stepDetectionEnabled: Bool = true
    @AppStorage("emergencyDistanceM")  private var emergencyDistanceM:  Double = 1.2
    @AppStorage("rangeMultiplier")     private var rangeMultiplier:     Double = 1.0

    // Developer
    @AppStorage("debugModeEnabled")    private var debugModeEnabled:   Bool   = false

    @State private var showBenchResult = false

    private let classes: [(String, String)] = [
        ("person",     "person.fill"),
        ("car",        "car.fill"),
        ("truck",      "truck.box.fill"),
        ("bus",        "bus.fill"),
        ("bicycle",    "bicycle"),
        ("motorcycle", "figure.outdoor.cycle"),
        ("dog",        "pawprint.fill"),
        ("cat",        "pawprint.fill"),
        ("chair",      "chair.lounge.fill"),
        ("table",      "table.furniture.fill"),
        ("door",       "door.left.hand.open"),
        ("stairs",     "staircase"),
    ]

    var body: some View {
        NavigationStack {
            Form {

                // MARK: Speech
                Section {
                    Picker("Verbosity", selection: $verbosityRaw) {
                        Text("Low Noise").tag("lowNoise")
                        Text("Normal").tag("normal")
                        Text("Critical Only").tag("criticalOnly")
                    }
                    .pickerStyle(.menu)

                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            Text("Speech Rate")
                            Spacer()
                            Text(speechRateLabel)
                                .foregroundStyle(.secondary)
                                .font(.subheadline)
                        }
                        Slider(value: $speechRate, in: 0.30...0.65, step: 0.05)
                            .tint(OmniSightTheme.accent)
                    }
                    .padding(.vertical, 4)

                    Picker("Scene Updates", selection: $sceneCooldown) {
                        Text("Frequent (every 3s)").tag(3.0)
                        Text("Normal (every 6s)").tag(6.0)
                        Text("Minimal (every 12s)").tag(12.0)
                    }
                    .pickerStyle(.menu)

                    Toggle("Imperial Units (Feet)", isOn: $useImperialUnits)

                } header: { Text("Speech") }
                  footer: { Text("Speech Rate affects how fast warnings and descriptions are read aloud.") }

                // MARK: Awareness
                Section {
                    Toggle("Hazard Alarms", isOn: $hazardAlarmsEnabled)
                    Toggle("Haptic Feedback", isOn: $hapticsEnabled)

                    Picker("Emergency Warning Distance", selection: $emergencyDistanceM) {
                        Text("Extra Cautious (2.0 m)").tag(2.0)
                        Text("Cautious (1.5 m)").tag(1.5)
                        Text("Normal (1.2 m)").tag(1.2)
                        Text("Minimal (0.8 m)").tag(0.8)
                    }
                    .pickerStyle(.menu)

                    Picker("Announcement Range", selection: $rangeMultiplier) {
                        Text("Near only (0.5×)").tag(0.5)
                        Text("Normal (1×)").tag(1.0)
                        Text("Extended (1.5×)").tag(1.5)
                    }
                    .pickerStyle(.menu)

                    if OmniPipeline.isSupported {
                        Toggle("Detect stairs & curbs", isOn: $stepDetectionEnabled)
                    } else {
                        HStack {
                            Text("Detect stairs & curbs")
                            Spacer()
                            Text("Requires iPhone Pro (LiDAR)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }

                } header: { Text("Awareness") }
                  footer: {
                    Text("Emergency Warning Distance sets how close an object must be before a collision alarm fires. Announcement Range scales how far away objects start being described.")
                }

                // MARK: Object Classes
                Section {
                    ForEach(classes, id: \.0) { cls, icon in
                        ClassToggleRow(className: cls, icon: icon)
                    }
                } header: { Text("Announce Object Classes") }
                  footer: { Text("Disable classes you don't need to hear about. Hazard warnings still fire for vehicles and people regardless of this setting.") }

                // MARK: Scanning Mode
                Section {
                    Picker("Scanning Mode", selection: Binding(
                        get: { app.mode.isFinding ? .navigation : app.mode },
                        set: { app.mode = $0 }
                    )) {
                        Text("Navigation").tag(AppMode.navigation)
                        Text("Hazard Priority").tag(AppMode.hazardPriority)
                    }
                    .pickerStyle(.segmented)
                } header: { Text("Scanning Mode") }
                  footer: { Text("Hazard Priority suppresses furniture and low-risk objects. Optimized for traffic and busy areas.") }

                // MARK: Developer
                Section {
                    Toggle("Debug Mode", isOn: $debugModeEnabled)
                        .onChange(of: debugModeEnabled) { _, on in
                            DecisionLog.shared.isEnabled = on
                            PerformanceMonitor.shared.isEnabled = on
                            if on { PerformanceMonitor.shared.resetSession() }
                        }

                    if !bench.isRunning {
                        Button("Run 30s Benchmark") { bench.start() }
                    } else {
                        HStack {
                            ProgressView().scaleEffect(0.8).padding(.trailing, 4)
                            Text("Benchmarking… \(bench.countdown)s remaining")
                                .foregroundStyle(.secondary)
                            Spacer()
                            Button("Stop") { bench.stop() }.foregroundStyle(.red)
                        }
                    }

                    if bench.result != nil {
                        Button("View Last Report") { showBenchResult = true }
                    }
                } header: { Text("Developer") }
                  footer: { Text("Benchmark runs a 30-second session and prints structured metrics to console.") }

                // MARK: Reset
                Section {
                    Button(role: .destructive) { resetDefaults() } label: {
                        Text("Reset to Defaults")
                    }
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
            .sheet(isPresented: $showBenchResult) {
                BenchmarkResultView(json: bench.result ?? "")
            }
        }
        .preferredColorScheme(.dark)
    }

    private var speechRateLabel: String {
        switch speechRate {
        case ..<0.35: return "Slow"
        case ..<0.50: return "Moderate"
        case ..<0.58: return "Normal"
        default:      return "Fast"
        }
    }

    private func resetDefaults() {
        verbosityRaw        = "normal"
        speechRate          = 0.52
        useImperialUnits    = false
        sceneCooldown       = 6.0
        hazardAlarmsEnabled = true
        hapticsEnabled      = true
        stepDetectionEnabled = true
        emergencyDistanceM  = 1.2
        rangeMultiplier     = 1.0
        debugModeEnabled    = false
        app.mode            = .navigation
        for (cls, _) in classes {
            UserDefaults.standard.set(true, forKey: "classEnabled_\(cls)")
        }
        NotificationCenter.default.post(name: .classSettingsReset, object: nil)
    }
}

// Separate view so each row can hold its own state for the dynamic UserDefaults key.
// Listens for classSettingsReset to refresh when the user taps "Reset to Defaults".
private struct ClassToggleRow: View {
    let className: String
    let icon: String

    @State private var enabled: Bool

    init(className: String, icon: String) {
        self.className = className
        self.icon = icon
        _enabled = State(initialValue:
            UserDefaults.standard.object(forKey: "classEnabled_\(className)") as? Bool ?? true
        )
    }

    var body: some View {
        Toggle(isOn: $enabled) {
            Label(className.capitalized, systemImage: icon)
        }
        .onChange(of: enabled) { _, val in
            UserDefaults.standard.set(val, forKey: "classEnabled_\(className)")
        }
        .onReceive(NotificationCenter.default.publisher(for: .classSettingsReset)) { _ in
            enabled = UserDefaults.standard.object(forKey: "classEnabled_\(className)") as? Bool ?? true
        }
    }
}

extension Notification.Name {
    static let classSettingsReset = Notification.Name("OmniSightClassSettingsReset")
}

// Benchmark result sheet
struct BenchmarkResultView: View {
    let json: String
    @Environment(\.dismiss) var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                Text(json)
                    .font(.system(.caption, design: .monospaced))
                    .padding()
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .navigationTitle("Benchmark Report")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } }
                ToolbarItem(placement: .primaryAction) {
                    ShareLink(item: json, subject: Text("OmniSight Benchmark"),
                              message: Text("OmniSight 30s metrics report"))
                }
            }
        }
        .preferredColorScheme(.dark)
    }
}

#Preview { SettingsView() }
