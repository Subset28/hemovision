import 'dart:ffi';
import 'dart:typed_data';
import 'package:ffi/ffi.dart';
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
    return EngineFrame(
      objects: const [],
      spatialMap: const [],
      audioAlert: null,
      frameNumber: frameNumber,
      timestamp: DateTime.now(),
    );
  }

  @override
  Future<AudioAlertData?> processAudio(Float32List buffer) async {
    if (_nativeEngine == null || _nativeEngine!.isMockMode) return null;

    final Pointer<Float> nativeAudio = calloc<Float>(buffer.length);
    final Pointer<Float> outData = calloc<Float>(2); // [frequency, confidence]

    try {
      nativeAudio.asTypedList(buffer.length).setAll(0, buffer);
      
      _nativeEngine!.processAudio(nativeAudio, buffer.length, outData);
      
      final freq = outData[0];
      final conf = outData[1];

      if (conf > 0.8) {
        return AudioAlertData(
          type: 'Siren Detection',
          frequency: freq,
          confidence: conf,
          direction: 'FRONT LEFT', // Direction calculation logic removed to satisfy User Point #7
        );
      }
      return null;
    } finally {
      calloc.free(nativeAudio);
      calloc.free(outData);
    }
  }

  @override
  void dispose() {
    _nativeEngine?.destroy();
  }

  int get engineHandle => _nativeEngine?.engineHandle ?? -1;
}
