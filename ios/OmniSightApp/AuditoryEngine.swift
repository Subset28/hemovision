import Foundation
import SoundAnalysis
import Speech
import AVFoundation

class AuditoryEngine: NSObject, SNResultsObserving {
    private let audioEngine = AVAudioEngine()
    private var streamAnalyzer: SNAudioStreamAnalyzer?
    private let speechRecognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    
    private let soundQueue = DispatchQueue(label: "com.omnisight.auditory")
    
    // The sounds we want to detect
    private let soundNames = ["siren", "knock", "doorbell", "dog_bark", "shout", "emergency_vehicle"]
    
    override init() {
        super.init()
    }
    
    func start() {
        requestPermissions { [weak self] granted in
            guard granted else { return }
            self?.setupAudioEngine()
        }
    }
    
    func stop() {
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        recognitionTask?.cancel()
        recognitionTask = nil
    }
    
    private func requestPermissions(completion: @escaping (Bool) -> Void) {
        SFSpeechRecognizer.requestAuthorization { authStatus in
            AVAudioSession.sharedInstance().requestRecordPermission { granted in
                DispatchQueue.main.async {
                    completion(granted && authStatus == .authorized)
                }
            }
        }
    }
    
    private func setupAudioEngine() {
        let inputNode = audioEngine.inputNode
        let recordingFormat = inputNode.outputFormat(forBus: 0)
        
        streamAnalyzer = SNAudioStreamAnalyzer(format: recordingFormat)
        
        // Setup Sound Analysis
        setupSoundAnalysis()
        
        // Setup Speech to Text
        setupSTT(format: recordingFormat)
        
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) { [weak self] buffer, time in
            self?.soundQueue.async {
                self?.streamAnalyzer?.analyze(buffer, atAudioFramePosition: time.sampleTime)
                self?.recognitionRequest?.append(buffer)
            }
        }
        
        do {
            try audioEngine.start()
        } catch {
            print("AuditoryEngine: Could not start audio engine: \(error)")
        }
    }
    
    private func setupSoundAnalysis() {
        do {
            // Using the built-in system sound classifier
            let config = MLModelConfiguration()
            let soundClassifier = try SNClassifySoundRequest(classifierIdentifier: .version1)
            try streamAnalyzer?.add(soundClassifier, withObserver: self)
        } catch {
            print("AuditoryEngine: Could not setup sound analysis: \(error)")
        }
    }
    
    private func setupSTT(format: AVAudioFormat) {
        recognitionRequest = SFSpeechAudioBufferRecognitionRequest()
        guard let recognitionRequest = recognitionRequest else { return }
        recognitionRequest.shouldReportPartialResults = true
        
        recognitionTask = speechRecognizer?.recognitionTask(with: recognitionRequest) { [weak self] result, error in
            if let result = result {
                DispatchQueue.main.async {
                    let text = result.bestTranscription.formattedString
                    AppStateManager.shared.liveCaptions = text
                }
            }
            if error != nil {
                self?.restartSTT(format: format)
            }
        }
    }
    
    private func restartSTT(format: AVAudioFormat) {
        recognitionTask?.cancel()
        setupSTT(format: format)
    }
    
    // SNResultsObserving
    func request(_ request: SNRequest, didProduce result: SNResult) {
        guard let classificationResult = result as? SNClassificationResult,
              let topResult = classificationResult.classifications.first else { return }
        
        if topResult.confidence > 0.7 {
            let label = topResult.identifier
            // Check if it's one of our target sounds
            if soundNames.contains(where: { label.contains($0) }) {
                handleDetectedSound(label)
            }
        }
    }
    
    private func handleDetectedSound(_ sound: String) {
        DispatchQueue.main.async {
            let readable = self.formatSoundName(sound)
            if AppStateManager.shared.detectedSound != readable {
                AppStateManager.shared.detectedSound = readable
                HapticManager.shared.warningVibration()
                
                // Clear after 3 seconds
                DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) {
                    if AppStateManager.shared.detectedSound == readable {
                        AppStateManager.shared.detectedSound = ""
                    }
                }
            }
        }
    }
    
    private func formatSoundName(_ sound: String) -> String {
        switch sound {
        case let s where s.contains("siren"): return "🚨 Siren Detected"
        case let s where s.contains("knock"): return "✊ Knocking Detected"
        case let s where s.contains("doorbell"): return "🔔 Doorbell Detected"
        case let s where s.contains("dog"): return "🐕 Dog Barking"
        case let s where s.contains("shout"): return "🗣️ Someone Shouting"
        default: return "🔊 \(sound.capitalized) Detected"
        }
    }
}
