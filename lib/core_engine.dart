import 'dart:ffi';
import 'dart:io';

// ─────────────────────────────────────────────────────────────────────────────
//  C++ STRUCT MIRRORS  (must match core_engine.h byte-for-byte)
// ─────────────────────────────────────────────────────────────────────────────

final class DetectedObject extends Struct {
  @Int32()
  external int classId;
  @Float()
  external double x;
  @Float()
  external double y;
  @Float()
  external double width;
  @Float()
  external double height;
  @Float()
  external double estimatedDistance;
  @Float()
  external double threatLevel;
}

final class SpatialPoint extends Struct {
  @Float()
  external double x;
  @Float()
  external double y;
  @Float()
  external double z;
  @Int32()
  external int persistenceFrames;
}

// ─────────────────────────────────────────────────────────────────────────────
//  UPGRADE #1 — NativeFinalizer (Memory Safety)
//
//  Problem: If the Dart GC collects the OmniSightEngine object while the C++
//  engine is still in memory, we have a leak. In a screen-recording demo or
//  long session, this can cause OOM crashes.
//
//  Solution: NativeFinalizer registers a C++ destructor that is AUTOMATICALLY
//  called when the Dart object is garbage collected — even if dispose() is
//  never called by the UI. This bridges the gap between Dart's managed GC
//  and C++'s manual memory model.
//
//  Reference: https://api.dart.dev/dart-ffi/NativeFinalizer-class.html
// ─────────────────────────────────────────────────────────────────────────────

// FFI type definitions for C exports
typedef _InitEngineC = IntPtr Function();
typedef _InitEngineDart = int Function();

typedef _DestroyEngineC = Void Function(IntPtr handle);
typedef _DestroyEngineDart = void Function(int handle);

typedef _ProcessVisionC = Int32 Function(
    IntPtr handle, Pointer<Uint8> img, Int32 w, Int32 h,
    Pointer<DetectedObject> out, Int32 max);
typedef _ProcessVisionDart = int Function(
    int handle, Pointer<Uint8> img, int w, int h,
    Pointer<DetectedObject> out, int max);

typedef _ProcessAudioC = Int32 Function(
    IntPtr handle, Pointer<Float> buf, Int32 size, Pointer<Float> out);
typedef _ProcessAudioDart = int Function(
    int handle, Pointer<Float> buf, int size, Pointer<Float> out);

typedef _GetSpatialMapC = Int32 Function(
    IntPtr handle, Pointer<SpatialPoint> out, Int32 max);
typedef _GetSpatialMapDart = int Function(
    int handle, Pointer<SpatialPoint> out, int max);

typedef _EstimateDistanceC = Float Function(Float w, Float h, Int32 classId);
typedef _EstimateDistanceDart = double Function(double w, double h, int classId);

// ─────────────────────────────────────────────────────────────────────────────
class OmniSightEngine {
  DynamicLibrary? _lib;
  int _engineHandle = 0;
  bool _isMockMode = false;

  // NativeFinalizer — registered once per engine instance.
  // When Dart GC collects this object, _destroyEngineNative is called
  // automatically with the raw C++ pointer, freeing native memory.
  static NativeFinalizer? _finalizer;

  late _DestroyEngineDart _destroyEngine;
  late _ProcessVisionDart _processVisionFrame;
  late _ProcessAudioDart _processAudioFft;
  late _GetSpatialMapDart _getSpatialMap;
  late _EstimateDistanceDart _estimateDistance;

  OmniSightEngine() {
    try {
      _lib = _loadLibrary();

      final initEngine =
          _lib!.lookupFunction<_InitEngineC, _InitEngineDart>('init_omnisight_engine');
      _destroyEngine =
          _lib!.lookupFunction<_DestroyEngineC, _DestroyEngineDart>('destroy_omnisight_engine');
      _processVisionFrame =
          _lib!.lookupFunction<_ProcessVisionC, _ProcessVisionDart>('process_vision_frame');
      _processAudioFft =
          _lib!.lookupFunction<_ProcessAudioC, _ProcessAudioDart>('process_audio_fft');
      _getSpatialMap =
          _lib!.lookupFunction<_GetSpatialMapC, _GetSpatialMapDart>('get_spatial_map');
      _estimateDistance =
          _lib!.lookupFunction<_EstimateDistanceC, _EstimateDistanceDart>('estimate_distance');

      _engineHandle = initEngine();

      // ── NativeFinalizer registration ──────────────────────────────────────
      // Look up the raw C function pointer for destroy_omnisight_engine.
      // NativeFinalizer will call it directly (no Dart dispatch overhead)
      // using the raw engine handle as the token, even after this Dart
      // object is dead.
      final destroyFnPtr = _lib!
          .lookup<NativeFunction<_DestroyEngineC>>('destroy_omnisight_engine');

      _finalizer ??= NativeFinalizer(destroyFnPtr.cast());
      _finalizer!.attach(this, Pointer.fromAddress(_engineHandle),
          detach: this);

    } catch (e) {
      // Graceful degradation: Native library absent → mock mode
      // This is intentional and documented in BUG_LOG #07.
      _isMockMode = true;
    }
  }

  static DynamicLibrary _loadLibrary() {
    if (Platform.isWindows) return DynamicLibrary.open('core_engine.dll');
    if (Platform.isAndroid) return DynamicLibrary.open('libcore_engine.so');
    if (Platform.isIOS || Platform.isMacOS) return DynamicLibrary.process();
    throw UnsupportedError('Unsupported platform: ${Platform.operatingSystem}');
  }

  bool get isMockMode => _isMockMode;
  int get engineHandle => _engineHandle;

  double estimateDistance(double width, double height, int classId) {
    if (_isMockMode) return 5.0;
    return _estimateDistance(width, height, classId);
  }

  /// Explicit dispose — detaches the finalizer so it isn't double-freed.
  /// Called by MainController.dispose() in the normal lifecycle.
  void destroy() {
    if (!_isMockMode && _engineHandle != 0) {
      _finalizer?.detach(this);
      _destroyEngine(_engineHandle);
      _engineHandle = 0;
    }
  }
}
