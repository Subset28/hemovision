import 'package:audioplayers/audioplayers.dart';
import '../engines/vision_engine.dart';

class SpatialAudioService {
  final AudioPlayer _player = AudioPlayer();
  bool _isEnabled = true;
  DateTime? _lastPlayed;

  void setEnabled(bool value) => _isEnabled = value;

  Future<void> playThreatSound(DetectedObjectData obj) async {
    if (!_isEnabled) return;

    final now = DateTime.now();
    if (_lastPlayed != null && now.difference(_lastPlayed!).inMilliseconds < 800) return;
    _lastPlayed = now;

    // Map distance (0-10m) to volume (1.0-0.1)
    final volume = (1.0 - (obj.distance / 10.0)).clamp(0.1, 1.0);
    
    // Map X (0-640) to Pan (-1.0 to 1.0)
    final pan = ((obj.x / 320.0) - 1.0).clamp(-1.0, 1.0);

    await _player.setVolume(volume);
    await _player.setBalance(pan);

    // Play a distinct "ping" or "beep" sound
    try {
      await _player.play(AssetSource('sounds/threat_ping.wav'));
    } catch (e) {
      // Fallback: log for verification
      print('Spatial Audio Error: $e');
    }
  }

  void dispose() {
    _player.dispose();
  }
}
