import 'dart:io';
import 'dart:convert';
import 'dart:async';
import '../engines/vision_engine.dart';

/// CaregiverService binds to port 8085 and broadcasts detection telemetry
/// to any connected local-network clients (e.g., a laptop or tablet).
class CaregiverService {
  ServerSocket? _server;
  final List<Socket> _clients = [];
  final _statusCtrl = StreamController<String>.broadcast();

  Stream<String> get statusStream => _statusCtrl.stream;
  int get clientCount => _clients.length;

  Future<void> start() async {
    try {
      _server = await ServerSocket.bind(InternetAddress.anyIPv4, 8085);
      _statusCtrl.add('Listening on port 8085');
      
      _server!.listen((client) {
        _clients.add(client);
        _statusCtrl.add('Client connected: ${client.remoteAddress.address}');
        
        client.done.then((_) {
          _clients.remove(client);
          _statusCtrl.add('Client disconnected');
        });
      });
    } catch (e) {
      _statusCtrl.add('Error: $e');
    }
  }

  void broadcastTelemetry(List<DetectedObjectData> objects) {
    if (_clients.isEmpty) return;

    final data = jsonEncode({
      'timestamp': DateTime.now().toIso8601String(),
      'objects': objects.map((o) => {
        'label': o.label,
        'distance': o.distance,
        'threat': o.threatLevel,
        'x': o.x,
        'y': o.y,
      }).toList(),
    });

    for (final client in _clients) {
      try {
        client.write('$data\n');
      } catch (e) {
        // Handle broken pipe
      }
    }
  }

  void stop() {
    for (final client in _clients) {
      client.destroy();
    }
    _clients.clear();
    _server?.close();
    _statusCtrl.add('Offline');
  }

  void dispose() {
    stop();
    _statusCtrl.close();
  }
}
