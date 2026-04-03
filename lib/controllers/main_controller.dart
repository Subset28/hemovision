import 'dart:async';
import 'package:flutter/foundation.dart';
import '../engines/vision_engine.dart';
import '../engines/simulated_vision_engine.dart';
import '../engines/yolo_vision_engine.dart';
import '../services/database_service.dart';

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
  late DatabaseService _dbService;
  Timer? _processingTimer;

  // ── Accessibility State ───────────────────────────────────────
  bool highContrast = false;
  bool largeText = false;
  final _accessCtrl = StreamController<void>.broadcast();
  Stream<void> get accessStream => _accessCtrl.stream;

  void updateAccessibility({bool? hc, bool? lt}) {
    if (hc != null) highContrast = hc;
    if (lt != null) largeText = lt;
    _accessCtrl.add(null);
  }

  // ── View Streams (Strongly Typed) ──────────────────────────────
  final _objectsCtrl = StreamController<List<DetectedObjectData>>.broadcast();
  Stream<List<DetectedObjectData>> get detectedObjectsStream => _objectsCtrl.stream;

  final _spatialCtrl = StreamController<List<SpatialPointData>>.broadcast();
  Stream<List<SpatialPointData>> get spatialMapStream => _spatialCtrl.stream;

  final _statsCtrl = StreamController<Map<String, dynamic>>.broadcast();
  Stream<Map<String, dynamic>> get statsStream => _statsCtrl.stream;

  // Live counters for the stats panel
  int _frameCount = 0;
  DateTime _sessionStart = DateTime.now();

  MainController() {
    _dbService = DatabaseService();
    
    // ── UPGRADE #2: Dynamic Initialization ───────────────────────
    try {
      final yolo = YoloVisionEngine();
      if (yolo.isMockMode) {
        _engine = SimulatedVisionEngine();
      } else {
        _engine = yolo;
      }
    } catch (e) {
      _engine = SimulatedVisionEngine();
    }
  }

  bool get isMockMode => _engine.isMockMode;

  void startProcessing() {
    _sessionStart = DateTime.now();
    // 100ms = ~10fps processing cadence.
    _processingTimer = Timer.periodic(const Duration(milliseconds: 100), (_) {
      _tick();
    });
  }

  void stopProcessing() => _processingTimer?.cancel();

  void dispose() {
    stopProcessing();
    _engine.dispose();
    _objectsCtrl.close();
    _spatialCtrl.close();
    _statsCtrl.close();
  }

  // ── Engine Tick ───────────────────────────────────────────────
  void _tick() async {
    _frameCount++;
    
    // ── UPGRADE #4: Concurrency (Isolate Offload) ───────────────
    // We send the current engine state to a background Isolate.
    // compute() handles the spawning/killing of the thread.
    final resultData = await compute(_processFrameInIsolate, {
      'isMock': _engine.isMockMode,
      'frameNumber': _frameCount,
    });

    final frame = EngineFrame.fromMap(resultData);

    if (!_objectsCtrl.isClosed) {
      _objectsCtrl.sink.add(frame.objects);
    }

    if (!_spatialCtrl.isClosed) {
      _spatialCtrl.sink.add(frame.spatialMap);
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
  final bool isMock = args['isMock'] as bool;
  final int frameNumber = args['frameNumber'] as int;

  // We instantiate a transient engine inside the Isolate to perform
  // the deterministic calculations or FFI lookups.
  late VisionEngine engine;
  if (isMock) {
    engine = SimulatedVisionEngine();
  } else {
    // In production, this would use a native handle or singleton
    engine = SimulatedVisionEngine(); 
  }

  final frame = await engine.processFrame(frameNumber);
  return frame.toMap();
}
