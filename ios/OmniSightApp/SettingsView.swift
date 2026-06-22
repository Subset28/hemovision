
import OmniSightKit
import SwiftUI

struct SettingsView: View {
    @Environment(\.dismiss) var dismiss
    @ObservedObject var app     = AppStateManager.shared
    @ObservedObject var bench   = BenchmarkSession.shared

    @AppStorage("verbosityMode")       private var verbosityRaw:       String = "normal"
    @AppStorage("useImperialUnits")    private var useImperialUnits:   Bool   = false
    @AppStorage("hazardAlarmsEnabled") private var hazardAlarmsEnabled: Bool  = true
    @AppStorage("hapticsEnabled")      private var hapticsEnabled:     Bool   = true

    @AppStorage("debugModeEnabled")    private var debugModeEnabled:   Bool   = false

    @State private var showBenchResult = false

    var body: some View {
        NavigationStack {
            Form {
                // Speech
                Section {
                    Picker("Verbosity", selection: $verbosityRaw) {
                        Text("Low Noise").tag("lowNoise")
                        Text("Normal").tag("normal")
                        Text("Critical Only").tag("criticalOnly")
                    }
                    .pickerStyle(.menu)
                    Toggle("Imperial Units (Feet)", isOn: $useImperialUnits)
                } header: { Text("Speech") }
                  footer: { Text("Imperial units describe distances in feet instead of meters.") }

                // Awareness
                Section {
                    Toggle("Hazard Beeps", isOn: $hazardAlarmsEnabled)
                    Toggle("Haptic Feedback", isOn: $hapticsEnabled)
                } header: { Text("Awareness") }
                  footer: { Text("Alarms sound when objects are too close or approaching fast.") }

                // Scanning Mode
                Section {
                    // Use a safe binding: finding mode shows as navigation in this picker
                    // (finding is managed from the main screen mode pill)
                    Picker("Scanning Mode", selection: Binding(
                        get: { app.mode.isFinding ? .navigation : app.mode },
                        set: { app.mode = $0 }
                    )) {
                        Text("Navigation").tag(AppMode.navigation)
                        Text("Hazard Priority").tag(AppMode.hazardPriority)
                    }
                    .pickerStyle(.segmented)
                } header: { Text("Scanning Mode") }
                  footer: {
                    Text("Hazard Priority suppresses furniture and low-risk objects. Optimized for traffic and busy areas.")
                }

                // Developer
                Section {
                    Toggle("Debug Mode", isOn: $debugModeEnabled)
                        .onChange(of: debugModeEnabled) { _, on in
                            DecisionLog.shared.isEnabled = on
                            PerformanceMonitor.shared.isEnabled = on
                            if on { PerformanceMonitor.shared.resetSession() }
                        }

                    if !bench.isRunning {
                        Button("Run 30s Benchmark") {
                            bench.start()
                        }
                    } else {
                        HStack {
                            ProgressView()
                                .scaleEffect(0.8)
                                .padding(.trailing, 4)
                            Text("Benchmarking… \(bench.countdown)s remaining")
                                .foregroundStyle(.secondary)
                            Spacer()
                            Button("Stop") { bench.stop() }
                                .foregroundStyle(.red)
                        }
                    }

                    if bench.result != nil {
                        Button("View Last Report") { showBenchResult = true }
                    }
                } header: { Text("Developer") }
                  footer: { Text("Benchmark runs a 30-second session and prints structured metrics to console.") }

                // Reset
                Section {
                    Button(role: .destructive) {
                        verbosityRaw        = "normal"
                        useImperialUnits    = false
                        hazardAlarmsEnabled = true
                        hapticsEnabled      = true
                        debugModeEnabled    = false
                        app.mode            = .navigation
                    } label: { Text("Reset to Defaults") }
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
}

// Benchmark result sheet — shows the JSON report with a share button
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
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close") { dismiss() }
                }
                ToolbarItem(placement: .primaryAction) {
                    ShareLink(item: json, subject: Text("OmniSight Benchmark"),
                              message: Text("OmniSight 30s metrics report"))
                }
            }
        }
        .preferredColorScheme(.dark)
    }
}

#Preview {
    SettingsView()
}
