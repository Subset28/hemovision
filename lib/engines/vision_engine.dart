// ─────────────────────────────────────────────────────────────────────────────
//  VISION ENGINE — Abstract Interface
//
//  UPGRADE #2: Dependency Inversion Principle (SOLID — "D")
//
//  Instead of MainController depending directly on a concrete class,
//  it depends on this abstract VisionEngine interface. This allows:
//    • Production: swap in YoloVisionEngine (real camera + C++ FFI)
//    • Testing:    inject SimulatedVisionEngine (deterministic mock)
//    • Future:     ARCoreVisionEngine, LiDARVisionEngine, etc.
//
//  This pattern is called "Dependency Injection" and is a hallmark of
//  enterprise-grade, testable code architecture.
// ─────────────────────────────────────────────────────────────────────────────

import 'dart:typed_data';

abstract interface class VisionEngine {
  /// Process the current environment and return detected objects.
  /// In production, this consumes a live camera frame.
  /// In simulation, this returns deterministic animated data.
  Future<EngineFrame> processFrame(int frameNumber);

  /// Process raw audio samples and return detected alerts (e.g. sirens).
  Future<AudioAlertData?> processAudio(Float32List buffer);

  /// Whether this engine is running in simulated (mock) mode.
  bool get isMockMode;

  /// Release all native resources. Must be called before GC.
  void dispose();
}

// ─────────────────────────────────────────────────────────────────────────────
//  ENGINE FRAME — Immutable result type returned by processFrame()
//  Using an immutable value object ensures thread-safe data passing
//  between the Isolate and the main UI thread via compute().
// ─────────────────────────────────────────────────────────────────────────────

class EngineFrame {
  final List<DetectedObjectData> objects;
  final List<SpatialPointData> spatialMap;
  final AudioAlertData? audioAlert;
  final int frameNumber;
  final DateTime timestamp;

  const EngineFrame({
    required this.objects,
    required this.spatialMap,
    this.audioAlert,
    required this.frameNumber,
    required this.timestamp,
  });

  /// Converts to a plain Map for passing across Isolate boundaries.
  /// Isolates cannot share Dart objects — only primitives and collections.
  Map<String, dynamic> toMap() => {
        'objects': objects.map((o) => o.toMap()).toList(),
        'spatialMap': spatialMap.map((p) => p.toMap()).toList(),
        'alert': audioAlert?.toMap(),
        'frameNumber': frameNumber,
        'timestamp': timestamp.millisecondsSinceEpoch,
      };

  factory EngineFrame.fromMap(Map<String, dynamic> map) => EngineFrame(
        objects: (map['objects'] as List)
            .map((o) => DetectedObjectData.fromMap(o as Map<String, dynamic>))
            .toList(),
        spatialMap: (map['spatialMap'] as List)
            .map((p) => SpatialPointData.fromMap(p as Map<String, dynamic>))
            .toList(),
        audioAlert: map['alert'] != null
            ? AudioAlertData.fromMap(map['alert'] as Map<String, dynamic>)
            : null,
        frameNumber: map['frameNumber'] as int,
        timestamp: DateTime.fromMillisecondsSinceEpoch(map['timestamp'] as int),
      );
}

// ─────────────────────────────────────────────────────────────────────────────
//  VALUE OBJECTS — Strongly-typed, immutable data containers
// ─────────────────────────────────────────────────────────────────────────────

class DetectedObjectData {
  final int classId;
  final double x, y, width, height;
  final double distance;
  final double threatLevel;
  final String label;

  const DetectedObjectData({
    required this.classId,
    required this.x,
    required this.y,
    required this.width,
    required this.height,
    required this.distance,
    required this.threatLevel,
    required this.label,
  });

  Map<String, dynamic> toMap() => {
        'classId': classId, 'x': x, 'y': y,
        'width': width, 'height': height,
        'distance': distance, 'threatLevel': threatLevel,
        'label': label,
      };

  factory DetectedObjectData.fromMap(Map<String, dynamic> m) =>
      DetectedObjectData(
        classId: m['classId'] as int,
        x: (m['x'] as num).toDouble(),
        y: (m['y'] as num).toDouble(),
        width: (m['width'] as num).toDouble(),
        height: (m['height'] as num).toDouble(),
        distance: (m['distance'] as num).toDouble(),
        threatLevel: (m['threatLevel'] as num).toDouble(),
        label: m['label'] as String? ?? 'Object',
      );

  bool get isCritical => threatLevel > 75.0;
  bool get isLeft => x < 320.0;
  String get directionLabel => isLeft ? 'Left' : 'Right';
}

class SpatialPointData {
  final double x, y, z, alpha;

  const SpatialPointData({
    required this.x,
    required this.y,
    required this.z,
    required this.alpha,
  });

  Map<String, dynamic> toMap() => {'x': x, 'y': y, 'z': z, 'alpha': alpha};

  factory SpatialPointData.fromMap(Map<String, dynamic> m) => SpatialPointData(
        x: (m['x'] as num).toDouble(),
        y: (m['y'] as num).toDouble(),
        z: (m['z'] as num).toDouble(),
        alpha: (m['alpha'] as num).toDouble(),
      );
}

class AudioAlertData {
  final String type;
  final double frequency;
  final double confidence;
  final String direction;

  const AudioAlertData({
    required this.type,
    required this.frequency,
    required this.confidence,
    required this.direction,
  });

  Map<String, dynamic> toMap() => {
        'type': type,
        'frequency': frequency,
        'confidence': confidence,
        'direction': direction,
      };

  factory AudioAlertData.fromMap(Map<String, dynamic> m) => AudioAlertData(
        type: m['type'] as String,
        frequency: (m['frequency'] as num).toDouble(),
        confidence: (m['confidence'] as num).toDouble(),
        direction: m['direction'] as String? ?? 'Unknown',
      );
}
