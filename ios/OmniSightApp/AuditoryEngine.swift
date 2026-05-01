import Foundation
import SoundAnalysis
import AVFoundation

// AuditoryEngine — Sound awareness for Deaf Mode
// Detects environmental sounds (sirens, knocks, doorbells, etc.) and
// fires haptic + visual alerts. STT/live captions removed.

class AuditoryEngine: NSObject, SNResultsObserving {
    private let audioEngine = AVAudioEngine()
    private var streamAnalyzer: SNAudioStreamAnalyzer?
    
    private let soundQueue = DispatchQueue(label: "com.omnisight.auditory")
    private var isStarted = false
    
    // Sounds to detect via Apple's built-in classifier
    private let targetSounds = ["siren", "knock", "doorbell", "dog_bark", "shout", "emergency_vehicle"]
    
    override init() {
        super.init()
    }
    
    func start() {
        guard !isStarted else { return }
        isStarted = true
        AVAudioSession.sharedInstance().requestRecordPermission { [weak self] granted in
            guard granted else { return }
            DispatchQueue.main.async {
                self?.configureAudioSession()
                self?.setupAudioEngine()
            }
        }
    }
    
    func stop() {
        guard isStarted else { return }
        isStarted = false
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        streamAnalyzer = nil
    }
    
    private func configureAudioSession() {
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .measurement, options: [.duckOthers, .defaultToSpeaker])
            try session.setActive(true, options: .notifyOthersOnDeactivation)
        } catch {
            print("AuditoryEngine: Audio session error: \(error)")
        }
    }
    
    private func setupAudioEngine() {
        let inputNode = audioEngine.inputNode
        let format = inputNode.outputFormat(forBus: 0)
        
        guard format.sampleRate > 0, format.channelCount > 0 else {
            print("AuditoryEngine: Invalid format, retrying in 1s...")
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in
                self?.setupAudioEngine()
            }
            return
        }
        
        streamAnalyzer = SNAudioStreamAnalyzer(format: format)
        
        do {
            let request = try SNClassifySoundRequest(classifierIdentifier: .version1)
            try streamAnalyzer?.add(request, withObserver: self)
        } catch {
            print("AuditoryEngine: Sound classifier setup failed: \(error)")
            return
        }
        
        inputNode.removeTap(onBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, time in
            self?.soundQueue.async {
                self?.streamAnalyzer?.analyze(buffer, atAudioFramePosition: time.sampleTime)
            }
        }
        
        do {
            try audioEngine.start()
        } catch {
            print("AuditoryEngine: Audio engine start failed: \(error)")
        }
    }
    
    // MARK: - SNResultsObserving
    
    func request(_ request: SNRequest, didProduce result: SNResult) {
        guard let classificationResult = result as? SNClassificationResult,
              let top = classificationResult.classifications.first else { return }
        
        let label = top.identifier
        let threshold: Double = (label.contains("siren") || label.contains("shout")) ? 0.85 : 0.70
        
        guard top.confidence > threshold,
              targetSounds.contains(where: { label.contains($0) }) else { return }
        
        DispatchQueue.main.async { [weak self] in
            self?.showSoundAlert(label)
        }
    }
    
    func request(_ request: SNRequest, didFailWithError error: Error) {
        print("AuditoryEngine: Classification error: \(error)")
    }
    
    private func showSoundAlert(_ sound: String) {
        let readable = formatSoundName(sound)
        guard AppStateManager.shared.detectedSound != readable else { return }
        
        AppStateManager.shared.detectedSound = readable
        HapticManager.shared.warningVibration()
        
        DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) {
            if AppStateManager.shared.detectedSound == readable {
                AppStateManager.shared.detectedSound = ""
            }
        }
    }
    
    private func formatSoundName(_ sound: String) -> String {
        switch sound {
        case let s where s.contains("siren"):       return "🚨 Siren Detected"
        case let s where s.contains("knock"):       return "✊ Knocking Detected"
        case let s where s.contains("doorbell"):    return "🔔 Doorbell Detected"
        case let s where s.contains("dog"):         return "🐕 Dog Barking"
        case let s where s.contains("shout"):       return "🗣️ Someone Shouting"
        case let s where s.contains("emergency"):   return "🚑 Emergency Vehicle"
        default: return "🔊 \(sound.capitalized.replacingOccurrences(of: "_", with: " ")) Detected"
        }
    }
}
