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
// ─────────────────────────────────────────────────────────────────────────────

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
    IntPtr handle, Pointer<Float> audio, Int32 size, Pointer<Float> out);
typedef _ProcessAudioDart = int Function(
    int handle, Pointer<Float> audio, int size, Pointer<Float> out);

typedef _EstimateDistanceC = Float Function(Float w, Float h, Int32 classId);
typedef _EstimateDistanceDart = double Function(double w, double h, int classId);

// ─────────────────────────────────────────────────────────────────────────────
class OmniSightEngine implements Finalizable {
  DynamicLibrary? _lib;
  int _engineHandle = 0;
  bool _isMockMode = false;

  static NativeFinalizer? _finalizer;

  late _DestroyEngineDart _destroyEngine;
  late _ProcessVisionDart _processVisionFrame;
  late _ProcessAudioDart _processAudioFFT;
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
      _processAudioFFT =
          _lib!.lookupFunction<_ProcessAudioC, _ProcessAudioDart>('process_audio_fft');
      _estimateDistance =
          _lib!.lookupFunction<_EstimateDistanceC, _EstimateDistanceDart>('estimate_distance');

      _engineHandle = initEngine();

      final destroyFnPtr = _lib!
          .lookup<NativeFunction<_DestroyEngineC>>('destroy_omnisight_engine');

      _finalizer ??= NativeFinalizer(destroyFnPtr.cast());
      _finalizer!.attach(this, Pointer.fromAddress(_engineHandle),
          detach: this);

    } catch (e) {
      _isMockMode = true;
    }
  }

  @pragma('vm:entry-point')
  void processFrame(Pointer<Uint8> img, int w, int h, Pointer<DetectedObject> out, int max) {
    if (!_isMockMode) _processVisionFrame(_engineHandle, img, w, h, out, max);
  }

  @pragma('vm:entry-point')
  void processAudio(Pointer<Float> audio, int size, Pointer<Float> out) {
    if (!_isMockMode) _processAudioFFT(_engineHandle, audio, size, out);
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

  void destroy() {
    if (!_isMockMode && _engineHandle != 0) {
      _finalizer?.detach(this);
      _destroyEngine(_engineHandle);
      _engineHandle = 0;
    }
  }
}
