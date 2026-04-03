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
  Future<EngineFrame> processFrame(int frameNumber, {Uint8List? bytes, int? width, int? height}) async {
    if (_nativeEngine == null || _nativeEngine!.isMockMode || bytes == null || width == null || height == null) {
      return EngineFrame(
        objects: const [],
        spatialMap: const [],
        audioAlert: null,
        frameNumber: frameNumber,
        timestamp: DateTime.now(),
      );
    }

    // Allocate memory for frame bytes
    final Pointer<Uint8> nativeBytes = calloc<Uint8>(bytes.length);
    // Allocate memory for output objects (max 20 objects)
    const int maxObjects = 20;
    final Pointer<ffi.DetectedObject> outObjects = calloc<ffi.DetectedObject>(maxObjects);

    try {
      nativeBytes.asTypedList(bytes.length).setAll(0, bytes);
      
      _nativeEngine!.processFrame(nativeBytes, width, height, outObjects, maxObjects);
      
      final List<DetectedObjectData> objects = [];
      for (int i = 0; i < maxObjects; i++) {
        final obj = outObjects[i];
        if (obj.classId == -1) break; // Engine uses -1 as end of results

        objects.add(DetectedObjectData(
          classId: obj.classId,
          x: obj.x,
          y: obj.y,
          width: obj.width,
          height: obj.height,
          distance: obj.estimatedDistance,
          threatLevel: obj.threatLevel,
          label: _getClassLabel(obj.classId),
        ));
      }

      return EngineFrame(
        objects: objects,
        spatialMap: const [], 
        audioAlert: null,
        frameNumber: frameNumber,
        timestamp: DateTime.now(),
      );
    } finally {
      calloc.free(nativeBytes);
      calloc.free(outObjects);
    }
  }

  String _getClassLabel(int id) {
    const labels = {0: 'Person', 1: 'Vehicle', 2: 'Obstacle', 15: 'Cat', 16: 'Dog'};
    return labels[id] ?? 'Entity';
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
          direction: freq < 1000 ? 'LEFT' : 'RIGHT', // Basic freq-based panning fallback
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
