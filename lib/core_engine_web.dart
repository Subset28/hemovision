// Web mock implementation of OmniSightEngine

// ─────────────────────────────────────────────────────────────────────────────
//  WEB MOCK STYLES
// ─────────────────────────────────────────────────────────────────────────────

// We mirror the signatures of FFI structs so the compiler remains happy,
// but we don't actually use Pointer<T> on web.
class DetectedObject {
  int classId = 0;
  double x = 0;
  double y = 0;
  double width = 0;
  double height = 0;
  double estimatedDistance = 0;
  double threatLevel = 0;
}

class SpatialPoint {
  double x = 0;
  double y = 0;
  double z = 0;
  int persistenceFrames = 0;
}

// ─────────────────────────────────────────────────────────────────────────────
//  OmniSightEngine Web Stub
// ─────────────────────────────────────────────────────────────────────────────

class OmniSightEngine {
  final bool _isMockMode = true;
  final int _engineHandle = 0;

  OmniSightEngine() {
    // No-op on web — always mock
  }

  // Web-safe version of frame processing
  void processFrame(dynamic img, int w, int h, dynamic out, int max) {
    // No-op
  }

  bool get isMockMode => _isMockMode;
  int get engineHandle => _engineHandle;

  double estimateDistance(double width, double height, int classId) {
    return 5.0; // Simulated distance
  }

  void destroy() {
    // No-op
  }
}
