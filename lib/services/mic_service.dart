import 'dart:async';
import 'dart:typed_data';
import 'package:record/record.dart';

class MicService {
  final AudioRecorder _recorder = AudioRecorder();
  StreamSubscription<Uint8List>? _subscription;
  final _audioCtrl = StreamController<Float32List>.broadcast();

  Stream<Float32List> get audioStream => _audioCtrl.stream;

  Future<bool> hasPermission() async {
    return await _recorder.hasPermission();
  }

  Future<void> startRecording() async {
    if (await hasPermission()) {
      const config = RecordConfig(
        encoder: AudioEncoder.pcm16bits,
        sampleRate: 44100,
        numChannels: 1,
      );

      final stream = await _recorder.startStream(config);
      
      _subscription = stream.listen((Uint8List data) {
        // Convert PCM16 (Int16) bytes to Float32 samples (-1.0 to 1.0)
        final int16Data = Int16List.view(data.buffer);
        final floatData = Float32List(int16Data.length);
        
        for (int i = 0; i < int16Data.length; i++) {
          floatData[i] = int16Data[i] / 32768.0;
        }
        
        if (!_audioCtrl.isClosed) {
          _audioCtrl.add(floatData);
        }
      });
    }
  }

  Future<void> stopRecording() async {
    await _subscription?.cancel();
    await _recorder.stop();
  }

  void dispose() {
    stopRecording();
    _audioCtrl.close();
    _recorder.dispose();
  }
}
