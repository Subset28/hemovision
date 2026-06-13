

import SwiftUI

struct SettingsView: View {
    @Environment(\.dismiss) var dismiss
    
    // settings using AppStorage to save them.
    @AppStorage("verbosityMode") private var verbosityRaw: String = "normal"
    @AppStorage("useImperialUnits") private var useImperialUnits: Bool = false
    @AppStorage("hazardAlarmsEnabled") private var hazardAlarmsEnabled: Bool = true
    @AppStorage("hapticsEnabled") private var hapticsEnabled: Bool = true
    @AppStorage("panAudioEnabled") private var panAudioEnabled: Bool = true
    
    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Picker("Verbosity", selection: $verbosityRaw) {
                        Text("Low Noise").tag("lowNoise")
                        Text("Normal").tag("normal")
                        Text("Critical Only").tag("criticalOnly")
                    }
                    .pickerStyle(.menu)
                    
                    Toggle("Imperial Units (Feet)", isOn: $useImperialUnits)
                } header: {
                    Text("Speech")
                } footer: {
                    Text("Imperial units will describe distances in feet instead of meters.")
                }
                
                Section {
                    Toggle("Hazard Beeps", isOn: $hazardAlarmsEnabled)
                    Toggle("Haptic Feedback", isOn: $hapticsEnabled)
                    Toggle("Spatial Audio (Pan)", isOn: $panAudioEnabled)
                } header: {
                    Text("Awareness")
                } footer: {
                    Text("Alarms will sound when objects are too close or approaching fast.")
                }
                
                Section {
                    Button(role: .destructive) {
                        // reset everything
                        verbosityRaw = "normal"
                        useImperialUnits = false
                        hazardAlarmsEnabled = true
                        hapticsEnabled = true
                        panAudioEnabled = true
                    } label: {
                        Text("Reset to Defaults")
                    }
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") {
                        dismiss()
                    }
                }
            }
        }
        .preferredColorScheme(.dark)
    }
}

#Preview {
    SettingsView()
}
