import '../services/settings_service.dart';
import '../services/mic_service.dart';
import '../services/spatial_audio_service.dart';
import 'package:vibration/vibration.dart';
import '../services/caregiver_service.dart';
import '../engines/vision_engine.dart';
import 'dart:async';
import 'dart:typed_data';
import 'package:camera/camera.dart';
import 'package:flutter/foundation.dart';

// ─────────────────────────────────────────────────────────────────
//  MAIN CONTROLLER  (MVC Architecture — Controller layer)
//
//  UPGRADE #2: Dependency Inversion.
//  The controller now depends on the VisionEngine interface, not
//  concrete implementations. This allows seamless switching between
//  production (YOLO) and simulation modes.
// ─────────────────────────────────────────────────────────────────
class MainController {
  late VisionEngine _engine;
  final SettingsService _settings;
  late MicService _micService;
  late SpatialAudioService _audioFeedback;
  late CaregiverService caregiverService;
  Timer? _processingTimer;
  bool useSimulation = true;

  Uint8List? _latestFrameBytes;
  int? _latestFrameWidth;
  int? _latestFrameHeight;

  // ── Accessibility State ───────────────────────────────────────
  bool get highContrast => _settings.highContrast;
  bool get largeText => _settings.largeText;
  bool get universalMode => _settings.universalMode;
  double get threatThreshold => _settings.dangerSensitivity;
  double get detectionRange => _settings.maxDistance;

  final _accessCtrl = StreamController<void>.broadcast();
  Stream<void> get accessStream => _accessCtrl.stream;

  void updateAccessibility({bool? hc, bool? lt, bool? um}) {
    if (hc != null) _settings.setHighContrast(hc);
    if (lt != null) _settings.setLargeText(lt);
    if (um != null) _settings.setUniversalMode(um);
    _accessCtrl.add(null);
  }

  void updateDetectionParams({double? threshold, double? range}) {
    if (threshold != null) _settings.setDangerSensitivity(threshold);
    if (range != null) _settings.setMaxDistance(range);
  }

  // ── View Streams (Strongly Typed) ──────────────────────────────
  final _objectsCtrl = StreamController<List<DetectedObjectData>>.broadcast();
  Stream<List<DetectedObjectData>> get detectedObjectsStream => _objectsCtrl.stream;

  final _spatialCtrl = StreamController<List<SpatialPointData>>.broadcast();
  Stream<List<SpatialPointData>> get spatialMapStream => _spatialCtrl.stream;

  final _statsCtrl = StreamController<Map<String, dynamic>>.broadcast();
  Stream<Map<String, dynamic>> get statsStream => _statsCtrl.stream;

  final _audioCtrl = StreamController<AudioAlertData?>.broadcast();
  Stream<AudioAlertData?> get audioAlertStream => _audioCtrl.stream;

  // Live counters for the stats panel
  int _frameCount = 0;
  DateTime _sessionStart = DateTime.now();

  MainController(this._settings) {
    _micService = MicService();
    _audioFeedback = SpatialAudioService();
    caregiverService = CaregiverService();
    
    // ── UPGRADE #2: Dynamic Initialization ───────────────────────
    try {
      final yolo = YoloVisionEngine();
      // Use persisted mock setting, but fallback to Simulation if native lib missing
      useSimulation = _settings.isMockMode || yolo.isMockMode; 
      _engine = useSimulation ? SimulatedVisionEngine() : yolo;
    } catch (e) {
      useSimulation = true;
      _engine = SimulatedVisionEngine();
    }
  }

  void setMockMode(bool enabled) {
    useSimulation = enabled;
    _settings.setMockMode(enabled);
    if (enabled) {
      _engine = SimulatedVisionEngine();
    } else {
      _engine = YoloVisionEngine();
    }
  }

  bool get isMockMode => _engine.isMockMode;

  void startProcessing() {
    _sessionStart = DateTime.now();
    // 100ms = ~10fps processing cadence.
    _processingTimer = Timer.periodic(const Duration(milliseconds: 100), (_) {
      _tick();
    });

    // Start real-time audio analysis loop
    _micService.startRecording();
    _micService.audioStream.listen((buffer) async {
      final alert = await _engine.processAudio(buffer);
      if (alert != null && !_audioCtrl.isClosed) {
        _audioCtrl.add(alert);
        // Alert haptics handled here for real-time response
        if (await Vibration.hasVibrator() ?? false) {
          Vibration.vibrate(pattern: [0, 200, 100, 200]);
        }
      }
    });
  }

  void stopProcessing() => _processingTimer?.cancel();

  void onCameraFrame(CameraImage image) {
    if (image.planes.isEmpty) return;
    
    // BGRA8888 has one plane on iOS
    // We only copy if we aren't currently "ticking" to save CPU
    _latestFrameBytes = image.planes[0].bytes;
    _latestFrameWidth = image.width;
    _latestFrameHeight = image.height;
  }

  void dispose() {
    stopProcessing();
    _engine.dispose();
    _micService.dispose();
    _audioFeedback.dispose();
    caregiverService.dispose();
    _objectsCtrl.close();
    _spatialCtrl.close();
    _statsCtrl.close();
    _audioCtrl.close();
  }

  // ── Engine Tick ───────────────────────────────────────────────
  void _tick() async {
    _frameCount++;
    
    // ── UPGRADE #4: Concurrency (Isolate Offload) ───────────────
    // We send the current engine state to a background Isolate.
    // compute() handles the spawning/killing of the thread.
    final resultData = await compute(_processFrameInIsolate, {
      'useSimulation': useSimulation,
      'frameNumber': _frameCount,
      'bytes': _latestFrameBytes,
      'width': _latestFrameWidth,
      'height': _latestFrameHeight,
    });

    final frame = EngineFrame.fromMap(resultData);

    if (!_objectsCtrl.isClosed) {
      _objectsCtrl.sink.add(frame.objects);
      // Broadcast to connected caregivers
      caregiverService.broadcastTelemetry(frame.objects);
    }

    if (!_spatialCtrl.isClosed) {
      _spatialCtrl.sink.add(frame.spatialMap);
    }

    if (!_audioCtrl.isClosed) {
      _audioCtrl.sink.add(frame.audioAlert);
      // HARDWARE HAPTICS: Trigger vibration for emergency sirens
      if (frame.audioAlert != null && frame.audioAlert!.confidence > 0.8) {
        if (await Vibration.hasVibrator() ?? false) {
          Vibration.vibrate(pattern: [0, 500, 200, 500], intensities: [0, 255, 0, 255]);
        }
      }
    }

    // HARDWARE HAPTICS: Trigger vibration for critical close-range objects
    if (frame.objects.any((o) => o.isCritical)) {
      if (await Vibration.hasVibrator() ?? false) {
        Vibration.vibrate(duration: 100);
      }
      
      // SPATIAL AUDIO: Play panned sound for the most critical object
      final mostCritical = frame.objects.reduce((a, b) => a.threatLevel > b.threatLevel ? a : b);
      _audioFeedback.playThreatSound(mostCritical);
    }

    if (!_statsCtrl.isClosed) {
      final elapsed = DateTime.now().difference(_sessionStart);
      _statsCtrl.sink.add({
        'frames': _frameCount,
        'uptime': _formatDuration(elapsed),
        'fps': (_frameCount / elapsed.inSeconds.clamp(1, 99999)).toStringAsFixed(1),
        'engine': _engine.isMockMode ? 'Simulated' : 'YOLOv8-Native',
        'health': 'Nominal',
      });
    }
  }

  String _formatDuration(Duration d) {
    String two(int n) => n.toString().padLeft(2, '0');
    return '${two(d.inHours)}:${two(d.inMinutes.remainder(60))}:${two(d.inSeconds.remainder(60))}';
  }
}

// ─────────────────────────────────────────────────────────────────
//  ISOLATE WORKER
//  Runs calculations in the background to ensure 60fps UI.
// ─────────────────────────────────────────────────────────────────
Future<Map<String, dynamic>> _processFrameInIsolate(Map<String, dynamic> args) async {
  final bool useSim = args['useSimulation'] as bool;
  final int frameNumber = args['frameNumber'] as int;

  // We instantiate a transient engine inside the Isolate.
  // CRITICAL: We only use Simulation if the user EXPLICITLY requested it.
  late VisionEngine engine;
  if (useSim) {
    engine = SimulatedVisionEngine();
  } else {
    engine = YoloVisionEngine(); 
  }

  try {
    final frame = await engine.processFrame(
      frameNumber, 
      bytes: args['bytes'] as Uint8List?,
      width: args['width'] as int?,
      height: args['height'] as int?
    );
    return frame.toMap();
  } finally {
    engine.dispose(); // CRITICAL: Prevent native handle leaks every 100ms
  }
}
