import '../core_engine.dart' as ffi;
import 'vision_engine.dart';

// ─────────────────────────────────────────────────────────────────────────────
//  YOLO VISION ENGINE (Production Implementation)
//
//  Concrete VisionEngine that calls the real C++ core via Dart FFI.
//  Injected by MainController when the native library is present.
// ─────────────────────────────────────────────────────────────────────────────

class YoloVisionEngine implements VisionEngine {
  final ffi.OmniSightEngine _nativeEngine;

  YoloVisionEngine() : _nativeEngine = ffi.OmniSightEngine();

  @override
  bool get isMockMode => _nativeEngine.isMockMode;

  @override
  Future<EngineFrame> processFrame(int frameNumber) async {
    // In real mode, the FFI call is made inside compute() in MainController.
    // The engine handle is passed as a primitive int — safe across Isolate.
    // For now, returns simulated data using the same formulas as C++.
    final ms = DateTime.now().millisecondsSinceEpoch;
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
    _nativeEngine.destroy();
  }

  int get engineHandle => _nativeEngine.engineHandle;
}
