import 'package:flutter_test/flutter_test.dart';
import 'package:hemovision/engines/yolo_vision_engine.dart';
import 'package:hemovision/controllers/main_controller.dart';

void main() {
  group('Hardware Guard & Native Fallback Unit Tests', () {
    
    test('MainController defaults to Mock Mode if Native Library is missing (No-Crash Prop)', () {
      // 1. Initialization
      final controller = MainController();

      // 2. Verification
      // In a test environment (CI or Local Mac without dylib), 
      // the controller must automatically fall back to mock mode.
      expect(controller.isMockMode, isTrue, 
        reason: 'Native libraries are usually missing in test environments. '
                'MainController must transparently switch to SimulatedVisionEngine.');
      
      // 3. Safety check: startProcessing should not crash even in mock mode
      expect(() => controller.startProcessing(), returnsNormally);
      controller.stopProcessing();
    });

    test('YoloVisionEngine detects non-native environment gracefully', () {
      final yolo = YoloVisionEngine();
      
      // If we are running on a machine without the compiled YOLO .dylib,
      // isMockMode should be true.
      expect(yolo.isMockMode, isTrue);
    });

    test('EngineFrame can handle null alerts (No-Crash Property)', () {
      final frame = EngineFrame(
        frameNumber: 1, 
        objects: [], 
        spatialMap: [],
        audioAlert: null, // Test null audio alert (which usually fails if not handled)
      );
      
      expect(frame.audioAlert, isNull);
      expect(() => frame.toMap(), returnsNormally);
    });
  });
}
