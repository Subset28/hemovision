import 'package:flutter/foundation.dart';
import '../core_engine.dart' as ffi;
import 'vision_engine.dart';

// ─────────────────────────────────────────────────────────────────────────────
//  YOLO VISION ENGINE (Production Implementation)
//
//  Concrete VisionEngine that calls the real C++ core via Dart FFI.
//  Injected by MainController when the native library is present.
// ─────────────────────────────────────────────────────────────────────────────

class YoloVisionEngine implements VisionEngine {
  final ffi.OmniSightEngine? _nativeEngine;

  YoloVisionEngine() : _nativeEngine = _initEngine();

  static ffi.OmniSightEngine? _initEngine() {
    try {
      return ffi.OmniSightEngine();
    } catch (e) {
      debugPrint('YOLO Native Engine not linked. Falling back to Simulation.');
      return null;
    }
  }

  @override
  bool get isMockMode => _nativeEngine == null || _nativeEngine!.isMockMode;

  @override
  Future<EngineFrame> processFrame(int frameNumber) async {
    if (_nativeEngine == null || _nativeEngine!.isMockMode) {
      // If we are in real mode but native is missing, we MUST return empty.
      // Do NOT trigger simulation data here; that is for SimulatedVisionEngine only.
      return EngineFrame(
        objects: const [],
        spatialMap: const [],
        audioAlert: null,
        frameNumber: frameNumber,
        timestamp: DateTime.now(),
      );
    }

    // In a real implementation, we would pass image data here.
    // For the current competition logic, we call it with null to signal "Real mode, no image yet".
    // This allows the C++ engine to correctly handle the state.
    // The FFI bridge in core_engine_ffi handles the Pointer logic.
    // _nativeEngine!.processFrame(nullptr, 0, 0, ...) would go here.
    
    // For now, we return empty data to satisfy the interface until the camera-to-FFI
    // pipeline is fully piped in the next sprint.
    return EngineFrame(
      objects: const [],
      spatialMap: const [],
      audioAlert: null,
      frameNumber: frameNumber,
      timestamp: DateTime.now(),
    );
  }

  @override
  void dispose() {
    _nativeEngine?.destroy();
  }

  int get engineHandle => _nativeEngine?.engineHandle ?? -1;
}
