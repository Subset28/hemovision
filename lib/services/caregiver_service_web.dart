import 'dart:async';

// ─────────────────────────────────────────────────────────────────────────────
//  WEB MOCK IMPLEMENTATION — CaregiverService
// ─────────────────────────────────────────────────────────────────────────────

enum CaregiverConnectionState {
  disconnected,
  listening,
  connecting,
  connected,
  unstable,
  reconnecting,
}

class CaregiverService {
  CaregiverConnectionState _state = CaregiverConnectionState.disconnected;
  CaregiverConnectionState get connectionState => _state;
  bool get isBroadcasting => _state != CaregiverConnectionState.disconnected;
  bool get isConnected => _state == CaregiverConnectionState.connected || _state == CaregiverConnectionState.unstable;

  final _stateController = StreamController<CaregiverConnectionState>.broadcast();
  Stream<CaregiverConnectionState> get connectionStateStream => _stateController.stream;
  Stream<CaregiverConnectionState> get stateStream => _stateController.stream;

  final _alertController = StreamController<Map<String, dynamic>>.broadcast();
  Stream<Map<String, dynamic>> get incomingAlerts => _alertController.stream;

  Future<void> startBroadcasting() async {
    _setState(CaregiverConnectionState.listening);
    // Mock a client connection after 2 seconds
    Future.delayed(const Duration(seconds: 2), () {
      if (_state == CaregiverConnectionState.listening) {
        _setState(CaregiverConnectionState.connected);
      }
    });
  }

  bool broadcastAlert(Map<String, dynamic> alertData) => true;
  void stopBroadcasting() => _setState(CaregiverConnectionState.disconnected);
  void disconnect() => _setState(CaregiverConnectionState.disconnected);

  Future<({bool connected, String? error})> connectToPrimaryUser(String ipAddress) async {
    _setState(CaregiverConnectionState.connecting);
    await Future.delayed(const Duration(seconds: 1));
    _setState(CaregiverConnectionState.connected);
    return (connected: true, error: null);
  }

  void _setState(CaregiverConnectionState next) {
    if (_state == next) return;
    _state = next;
    if (!_stateController.isClosed) _stateController.add(next);
  }

  void dispose() {
    _alertController.close();
    _stateController.close();
  }
}
