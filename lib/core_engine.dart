import 'dart:ffi';
import 'dart:io';

// Representation of the C struct in Dart
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

// Function types
typedef _InitEngineC = IntPtr Function();
typedef _InitEngineDart = int Function();

typedef _DestroyEngineC = Void Function(IntPtr engineHandle);
typedef _DestroyEngineDart = void Function(int engineHandle);

typedef _ProcessVisionC = Int32 Function(IntPtr engineHandle, Pointer<Uint8> imageData, Int32 width, Int32 height, Pointer<DetectedObject> outObjects, Int32 maxObjects);
typedef _ProcessVisionDart = int Function(int engineHandle, Pointer<Uint8> imageData, int width, int height, Pointer<DetectedObject> outObjects, int maxObjects);

typedef _GetSpatialMapC = Int32 Function(IntPtr engineHandle, Pointer<SpatialPoint> outPoints, Int32 maxPoints);
typedef _GetSpatialMapDart = int Function(int engineHandle, Pointer<SpatialPoint> outPoints, int maxPoints);

typedef _EstimateDistanceC = Float Function(Float width, Float height, Int32 classId);
typedef _EstimateDistanceDart = double Function(double width, double height, int classId);

class OmniSightEngine {
  DynamicLibrary? _lib;
  int _engineHandle = 0;
  bool _isMockMode = false;
  
  late _InitEngineDart _initEngine;
  late _DestroyEngineDart _destroyEngine;
  late _ProcessVisionDart _processVisionFrame;
  late _GetSpatialMapDart _getSpatialMap;
  late _EstimateDistanceDart _estimateDistance;

  OmniSightEngine() {
    try {
      if (Platform.isWindows) {
        _lib = DynamicLibrary.open('core_engine.dll');
      } else if (Platform.isAndroid) {
        _lib = DynamicLibrary.open('libcore_engine.so');
      } else if (Platform.isIOS || Platform.isMacOS) {
        _lib = DynamicLibrary.process();
      } else {
        throw UnsupportedError('Unsupported platform');
      }

      _initEngine = _lib!.lookupFunction<_InitEngineC, _InitEngineDart>('init_omnisight_engine');
      _destroyEngine = _lib!.lookupFunction<_DestroyEngineC, _DestroyEngineDart>('destroy_omnisight_engine');
      _processVisionFrame = _lib!.lookupFunction<_ProcessVisionC, _ProcessVisionDart>('process_vision_frame');
      _getSpatialMap = _lib!.lookupFunction<_GetSpatialMapC, _GetSpatialMapDart>('get_spatial_map');
      _estimateDistance = _lib!.lookupFunction<_EstimateDistanceC, _EstimateDistanceDart>('estimate_distance');
      
      _engineHandle = _initEngine();
    } catch (e) {
      print("TSA DEV NOTE: Native C++ library not found. Falling back to Mock UI Mode for seamless preview.");
      _isMockMode = true;
    }
  }
  
  bool get isMockMode => _isMockMode;
  int get engineHandle => _engineHandle;
  
  void destroy() {
    if (!_isMockMode) {
      _destroyEngine(_engineHandle);
    }
  }

  double estimateDistance(double width, double height, int classId) {
    if (_isMockMode) return 5.0; // Mock fallback
    return _estimateDistance(width, height, classId);
  }
}
