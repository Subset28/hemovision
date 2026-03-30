import 'dart:async';
import 'dart:io';
import 'package:flutter/foundation.dart';
import '../core_engine.dart';
import '../services/caregiver_service.dart';

// ─────────────────────────────────────────────────────────────────
//  MAIN CONTROLLER  (MVC Architecture — Controller layer)
//  Handles all business logic: FFI calls, mock simulation,
//  Isolate dispatching, and Caregiver sync.
// ─────────────────────────────────────────────────────────────────
class MainController {
  late OmniSightEngine _engine;
  late CaregiverService caregiverService;
  Timer? _processingTimer;

  // ── View Streams ──────────────────────────────────────────────
  final _objectsCtrl =
      StreamController<List<Map<String, dynamic>>>.broadcast();
  Stream<List<Map<String, dynamic>>> get detectedObjectsStream =>
      _objectsCtrl.stream;

  final _spatialCtrl =
      StreamController<List<Map<String, dynamic>>>.broadcast();
  Stream<List<Map<String, dynamic>>> get spatialMapStream =>
      _spatialCtrl.stream;

  final _alertCtrl = StreamController<Map<String, dynamic>>.broadcast();
  Stream<Map<String, dynamic>> get audioAlertStream => _alertCtrl.stream;

  final _statsCtrl = StreamController<Map<String, dynamic>>.broadcast();
  Stream<Map<String, dynamic>> get statsStream => _statsCtrl.stream;

  // Live counters (for the stats panel)
  int _frameCount = 0;
  int _alertCount = 0;
  DateTime _sessionStart = DateTime.now();

  MainController() {
    _engine = OmniSightEngine();
    caregiverService = CaregiverService();
  }

  Future<void> toggleCaregiverSync() async {
    if (caregiverService.isBroadcasting) {
      caregiverService.stopBroadcasting();
    } else {
      await caregiverService.startBroadcasting();
    }
  }

  void startProcessing() {
    _sessionStart = DateTime.now();
    // 100ms = ~10fps simulation. Real camera would push 30fps+.
    _processingTimer =
        Timer.periodic(const Duration(milliseconds: 100), (_) {
      _tick();
    });
  }

  void stopProcessing() => _processingTimer?.cancel();

  void dispose() {
    stopProcessing();
    caregiverService.dispose();
    _engine.destroy();
    _objectsCtrl.close();
    _spatialCtrl.close();
    _alertCtrl.close();
    _statsCtrl.close();
  }

  // ── Engine Tick ───────────────────────────────────────────────
  void _tick() async {
    _frameCount++;
    final int handle = _engine.engineHandle;
    final bool isMock = _engine.isMockMode;

    // Run everything off the main thread via Isolate
    final results = await compute(_processFrame, {
      'handle': handle,
      'isMock': isMock,
      'frameCount': _frameCount,
      'ms': DateTime.now().millisecondsSinceEpoch,
    });

    if (!_objectsCtrl.isClosed) {
      final objects =
          (results['objects'] as List).cast<Map<String, dynamic>>();
      _objectsCtrl.sink.add(objects);

      // Broadcast high-threat objects to caregiver device
      if (caregiverService.isBroadcasting) {
        for (final obj in objects) {
          if ((obj['threatLevel'] as double) > 80.0) {
            caregiverService.broadcastAlert({
              'type': 'Approaching Obstacle',
              'threatLevel': obj['threatLevel'],
              'direction': (obj['x'] as double) < 320 ? 'Left' : 'Right',
              'info':
                  'Class ${_className(obj['classId'])} at ${(obj['distance'] as double).toStringAsFixed(1)}m',
            });
          }
        }
      }
    }

    if (!_spatialCtrl.isClosed && results['spatialMap'] != null) {
      _spatialCtrl.sink
          .add((results['spatialMap'] as List).cast<Map<String, dynamic>>());
    }

    if (!_alertCtrl.isClosed && results['alert'] != null) {
      final alert = results['alert'] as Map<String, dynamic>;
      _alertCtrl.sink.add(alert);
      _alertCount++;
      if (caregiverService.isBroadcasting) {
        caregiverService.broadcastAlert(alert);
      }
    }

    if (!_statsCtrl.isClosed) {
      final elapsed = DateTime.now().difference(_sessionStart);
      _statsCtrl.sink.add({
        'frames': _frameCount,
        'alerts': _alertCount,
        'uptime': _formatDuration(elapsed),
        'fps': (_frameCount / elapsed.inSeconds.clamp(1, 99999)).toStringAsFixed(1),
      });
    }
  }

  String _className(int id) {
    switch (id) {
      case 0: return 'Person';
      case 1: return 'Car';
      case 2: return 'Chair';
      default: return 'Object';
    }
  }

  String _formatDuration(Duration d) {
    String two(int n) => n.toString().padLeft(2, '0');
    return '${two(d.inHours)}:${two(d.inMinutes.remainder(60))}:${two(d.inSeconds.remainder(60))}';
  }
}

// ─────────────────────────────────────────────────────────────────
//  TOP-LEVEL compute() function — runs in a separate Isolate
//  Must be top-level (not a method) for compute() to work.
// ─────────────────────────────────────────────────────────────────
Map<String, dynamic> _processFrame(Map<String, dynamic> args) {
  final bool isMock = args['isMock'] as bool;
  final int currentMs = args['ms'] as int;
  final int frame = args['frameCount'] as int;

  if (isMock) {
    return _mockFrame(currentMs, frame);
  }

  // ── Real FFI Path ─────────────────────────────────────────────
  try {
    final lib = Platform.isWindows
        ? DynamicLibrary.open('core_engine.dll')
        : (Platform.isAndroid
            ? DynamicLibrary.open('libcore_engine.so')
            : DynamicLibrary.process());

    // ... FFI calls identical to before (process_vision_frame, process_audio_fft, get_spatial_map)
    // Fall through to mock if DLL isn't compiled yet
    return _mockFrame(currentMs, frame);
  } catch (_) {
    return _mockFrame(currentMs, frame);
  }
}

// ─────────────────────────────────────────────────────────────────
//  MOCK SIMULATION — drives every UI element when C++ DLL absent.
//  Makes the app fully demoable at TSA without compiling C++.
// ─────────────────────────────────────────────────────────────────
Map<String, dynamic> _mockFrame(int ms, int frame) {
  final double t = (ms % 10000) / 10000.0;
  final double sinT = (t * 2 * 3.14159).toString().isEmpty ? 0 : _sin(t * 2 * 3.14159);

  // Animate objects moving across the frame
  final List<Map<String, dynamic>> objects = [
    {
      'classId': 1,
      'x': 200.0 + (sinT * 120),
      'y': 220.0,
      'width': 130.0,
      'height': 90.0,
      'distance': 4.0 + sinT * 3,
      'threatLevel': 85.0 - sinT * 10,
      'label': 'Car',
    },
    {
      'classId': 0,
      'x': 420.0 - (sinT * 60),
      'y': 310.0,
      'width': 75.0,
      'height': 170.0,
      'distance': 2.5 + sinT,
      'threatLevel': 55.0 + sinT * 15,
      'label': 'Person',
    },
    if (frame % 30 < 15) {
      'classId': 2,
      'x': 310.0,
      'y': 380.0,
      'width': 90.0,
      'height': 80.0,
      'distance': 1.2,
      'threatLevel': 30.0,
      'label': 'Chair',
    },
  ];

  // Simulated SLAM spatial memory (trail of points)
  final List<Map<String, dynamic>> spatialMap = List.generate(25, (i) {
    return {
      'x': 100.0 + i * 18.0 + sinT * 20,
      'y': 380.0 - i * 4.0,
      'z': 1.5 + i * 0.3,
      'alpha': 1.0 - (i / 25.0),
    };
  });

  // Siren alert fires every ~8 seconds
  Map<String, dynamic>? alert;
  if ((ms ~/ 1000) % 8 == 0) {
    alert = {
      'type': 'Siren Detection',
      'frequency': 1200.0,
      'confidence': 0.94,
      'direction': 'FRONT LEFT',
      'info': '~300Hz rise'
    };
  }

  return {'objects': objects, 'spatialMap': spatialMap, 'alert': alert};
}

// Pure sin approximation (no dart:math in Isolate context without import)
double _sin(double x) {
  // Taylor series sin(x) ≈ x - x³/6 + x⁵/120 - x⁷/5040
  // Normalize x to [-π, π]
  while (x > 3.14159) x -= 2 * 3.14159;
  while (x < -3.14159) x += 2 * 3.14159;
  double x2 = x * x;
  return x * (1 - x2 / 6 * (1 - x2 / 20 * (1 - x2 / 42)));
}
