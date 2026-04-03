import 'dart:math' as math;
import 'vision_engine.dart';

// ─────────────────────────────────────────────────────────────────────────────
//  SIMULATED VISION ENGINE
//
//  UPGRADE #2: Concrete implementation of VisionEngine for development/testing.
//
//  This is NOT a random simulation — it is a DETERMINISTIC test engine.
//  Given the same frameNumber input, it always produces the same output.
//  This makes it suitable for unit testing, reproducible bug reports,
//  and competition demonstrations where a live camera isn't available.
//
//  Design pattern: Strategy Pattern (interchangeable algorithm)
//  SOLID principle: Dependency Inversion (depends on abstraction, not concrete)
// ─────────────────────────────────────────────────────────────────────────────

class SimulatedVisionEngine implements VisionEngine {
  @override
  final bool isMockMode = true;

  bool mockEnabled = true; // Control simulated output

  // Deterministic sine wave seed — same frame = same output
  static double _sin(double x) {
    while (x > math.pi) x -= 2 * math.pi;
    while (x < -math.pi) x += 2 * math.pi;
    final x2 = x * x;
    return x * (1 - x2 / 6 * (1 - x2 / 20 * (1 - x2 / 42)));
  }

  /// Distance estimation formula — identical to C++ implementation.
  /// D = (W_real × focal_length) / W_pixel
  /// This ensures unit tests of the Dart formula match C++ behavior exactly.
  static double estimateDistance(double bboxWidth, int classId) {
    const focalLength = 800.0;
    final realWidths = {0: 0.50, 1: 1.80, 2: 0.60, 3: 0.40};
    final realWidth = realWidths[classId] ?? 1.0;
    if (bboxWidth < 1.0) return 999.0; // Guard: divide-by-zero protection
    return (realWidth * focalLength) / bboxWidth;
  }

  /// Threat level formula — identical to C++ implementation.
  /// threat = min(100 / (distance + 0.1) × multiplier, 100)
  static double calculateThreat(double distance, int classId) {
    final multipliers = {0: 1.5, 1: 3.0, 2: 1.0, 3: 1.2};
    final base = 100.0 / (distance + 0.1);
    return (base * (multipliers[classId] ?? 1.0)).clamp(0.0, 100.0);
  }

  @override
  Future<EngineFrame> processFrame(int frameNumber) async {
    final t = frameNumber * 0.03;
    final sinT = _sin(t);
    final ms = DateTime.now().millisecondsSinceEpoch;

    // ── Object 1: Car (animated left-right) ────────────────────────────────
    final carWidth = 130.0;
    final carDist = estimateDistance(carWidth, 1);
    final car = DetectedObjectData(
      classId: 1,
      x: 200.0 + sinT * 120,
      y: 220.0,
      width: carWidth,
      height: 90.0,
      distance: carDist,
      threatLevel: calculateThreat(carDist, 1),
      label: 'Car',
    );

    // ── Object 2: Person (animated right-left, counter-phase) ───────────────
    final personWidth = 75.0;
    final personDist = estimateDistance(personWidth, 0);
    final person = DetectedObjectData(
      classId: 0,
      x: 420.0 - sinT * 60,
      y: 310.0,
      width: personWidth,
      height: 170.0,
      distance: personDist,
      threatLevel: calculateThreat(personDist, 0),
      label: 'Person',
    );

    // ── Object 3: Chair (appears every other ~3s window) ────────────────────
    final showChair = (frameNumber ~/ 30) % 2 == 0;
    final chair = showChair
        ? DetectedObjectData(
            classId: 2,
            x: 310.0,
            y: 380.0,
            width: 90.0,
            height: 80.0,
            distance: estimateDistance(90.0, 2),
            threatLevel: calculateThreat(estimateDistance(90.0, 2), 2),
            label: 'Chair',
          )
        : null;

    final objects = [car, person, if (chair != null) chair];

    // ── SLAM Spatial Memory (decay trail) ──────────────────────────────────
    final spatialMap = List.generate(25, (i) {
      return SpatialPointData(
        x: 100.0 + i * 18.0 + sinT * 20,
        y: 380.0 - i * 4.0,
        z: 1.5 + i * 0.3,
        alpha: (1.0 - i / 25.0).clamp(0.0, 1.0),
      );
    });

    // ── Audio Alert (siren every 8 seconds) ────────────────────────────────
    AudioAlertData? alert;
    if ((ms ~/ 1000) % 8 == 0) {
      alert = const AudioAlertData(
        type: 'Siren Detection',
        frequency: 1200.0,
        confidence: 0.94,
        direction: 'FRONT LEFT',
      );
    }

    return EngineFrame(
      objects: objects,
      spatialMap: spatialMap,
      audioAlert: alert,
      frameNumber: frameNumber,
      timestamp: DateTime.now(),
    );
  }

  @override
  void dispose() {
    // No native resources to free in simulation mode
  }
}
