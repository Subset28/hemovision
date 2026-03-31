import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:isolate';

// ─────────────────────────────────────────────────────────────────────────────
//  NATIVE IMPLEMENTATION — CaregiverService
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
  static const int _port = 8085;
  static const Duration _heartbeatInterval = Duration(seconds: 5);
  static const int _maxMissedHeartbeats = 2;
  static const Duration _reconnectDelay = Duration(seconds: 3);

  ServerSocket? _serverSocket;
  Socket? _activeSocket;
  CaregiverConnectionState _state = CaregiverConnectionState.disconnected;
  
  CaregiverConnectionState get connectionState => _state;
  bool get isBroadcasting => _state != CaregiverConnectionState.disconnected;
  bool get isConnected => _state == CaregiverConnectionState.connected || _state == CaregiverConnectionState.unstable;

  final _stateController = StreamController<CaregiverConnectionState>.broadcast();
  Stream<CaregiverConnectionState> get connectionStateStream => _stateController.stream;
  Stream<CaregiverConnectionState> get stateStream => _stateController.stream;

  final _alertController = StreamController<Map<String, dynamic>>.broadcast();
  Stream<Map<String, dynamic>> get incomingAlerts => _alertController.stream;

  Timer? _heartbeatTimer;
  Timer? _heartbeatWatchdog;
  DateTime? _lastHeartbeatReceived;

  Isolate? _listenerIsolate;
  ReceivePort? _fromIsolatePort;

  Future<void> startBroadcasting() async {
    if (_state != CaregiverConnectionState.disconnected) return;
    try {
      _serverSocket = await ServerSocket.bind(InternetAddress.anyIPv4, _port);
      _setState(CaregiverConnectionState.listening);
      _serverSocket!.listen(_onClientConnected, onError: (e) => _handleError('Server error: $e'));
    } on SocketException catch (e) {
      _handleError('Cannot bind to port $_port: $e');
    }
  }

  void _onClientConnected(Socket socket) {
    _activeSocket = socket;
    _setState(CaregiverConnectionState.connected);
    _startHeartbeat();
    _startListenerIsolate(socket);
    socket.done.then((_) => _onClientDisconnected());
  }

  void _onClientDisconnected() {
    _stopHeartbeat();
    _activeSocket = null;
    if (_state != CaregiverConnectionState.disconnected) {
      _setState(CaregiverConnectionState.reconnecting);
      Future.delayed(_reconnectDelay, () {
        if (_state == CaregiverConnectionState.reconnecting) _setState(CaregiverConnectionState.listening);
      });
    }
  }

  bool broadcastAlert(Map<String, dynamic> alertData) {
    if (_activeSocket == null || !isConnected) return false;
    try {
      _activeSocket!.write(jsonEncode(alertData) + '\n');
      return true;
    } on SocketException catch (e) {
      _handleError('Broadcast failed: $e');
      return false;
    }
  }

  void stopBroadcasting() {
    _stopHeartbeat();
    _listenerIsolate?.kill(priority: Isolate.immediate);
    _listenerIsolate = null;
    _fromIsolatePort?.close();
    _activeSocket?.destroy();
    _serverSocket?.close();
    _activeSocket = null;
    _serverSocket = null;
    _setState(CaregiverConnectionState.disconnected);
  }

  void _startHeartbeat() {
    _heartbeatTimer?.cancel();
    _heartbeatWatchdog?.cancel();
    _heartbeatTimer = Timer.periodic(_heartbeatInterval, (_) {
      if (!broadcastAlert({'type': 'hb', 'ts': DateTime.now().millisecondsSinceEpoch})) _stopHeartbeat();
    });
    _heartbeatWatchdog = Timer.periodic(_heartbeatInterval + const Duration(seconds: 2), (_) {
      if (_lastHeartbeatReceived != null) {
        final elapsed = DateTime.now().difference(_lastHeartbeatReceived!);
        if (elapsed.inSeconds > _heartbeatInterval.inSeconds * _maxMissedHeartbeats) {
          if (_state == CaregiverConnectionState.connected) _setState(CaregiverConnectionState.unstable);
        } else if (_state == CaregiverConnectionState.unstable) {
          _setState(CaregiverConnectionState.connected);
        }
      }
    });
  }

  void _stopHeartbeat() {
    _heartbeatTimer?.cancel();
    _heartbeatWatchdog?.cancel();
    _heartbeatTimer = null;
    _heartbeatWatchdog = null;
  }

  Future<void> _startListenerIsolate(Socket socket) async {
    _fromIsolatePort?.close();
    _fromIsolatePort = ReceivePort();
    final isolateArgs = _IsolateArgs(
      sendPort: _fromIsolatePort!.sendPort,
      socketPort: socket.port,
      remoteAddress: socket.remoteAddress.address,
    );
    _listenerIsolate = await Isolate.spawn(_isolateListenerLoop, isolateArgs, debugName: 'CaregiverTcpListener');
    _fromIsolatePort!.listen((message) {
      if (message is Map<String, dynamic>) {
        if (message['type'] == 'hb') {
          _lastHeartbeatReceived = DateTime.now();
        } else {
          _alertController.sink.add(message);
        }
      } else if (message is String && message == '_disconnected') {
        _onClientDisconnected();
      }
    });
  }

  static void _isolateListenerLoop(_IsolateArgs args) {
    args.sendPort.send({'type': 'isolate_ready'});
  }

  Future<({bool connected, String? error})> connectToPrimaryUser(String ipAddress) async {
    _setState(CaregiverConnectionState.connecting);
    try {
      _activeSocket = await Socket.connect(ipAddress, _port, timeout: const Duration(seconds: 5));
      _setState(CaregiverConnectionState.connected);
      _lastHeartbeatReceived = DateTime.now();
      _listenOnSocket(_activeSocket!);
      _activeSocket!.done.then((_) {
        if (_state != CaregiverConnectionState.disconnected) {
          _setState(CaregiverConnectionState.reconnecting);
          _scheduleReconnect(ipAddress);
        }
      });
      return (connected: true, error: null);
    } on SocketException catch (e) {
      _setState(CaregiverConnectionState.disconnected);
      return (connected: false, error: 'Cannot reach $ipAddress:$_port — ${e.message}');
    } on TimeoutException {
      _setState(CaregiverConnectionState.disconnected);
      return (connected: false, error: 'Connection timed out after 5s');
    }
  }

  void _listenOnSocket(Socket socket) {
    final StringBuffer buffer = StringBuffer();
    socket.cast<List<int>>().transform(utf8.decoder).listen((data) {
      buffer.write(data);
      final raw = buffer.toString();
      final lines = raw.split('\n');
      buffer.clear();
      for (var i = 0; i < lines.length; i++) {
        final line = lines[i].trim();
        if (line.isEmpty) continue;
        if (i == lines.length - 1 && !raw.endsWith('\n')) buffer.write(line);
        else _parseAndDispatch(line);
      }
    }, onError: (e) => _handleError('Socket read error: $e'), onDone: () => _onClientDisconnected());
  }

  void _parseAndDispatch(String line) {
    try {
      final map = jsonDecode(line) as Map<String, dynamic>;
      if (map['type'] == 'hb') {
        _lastHeartbeatReceived = DateTime.now();
        if (_state == CaregiverConnectionState.unstable) _setState(CaregiverConnectionState.connected);
      } else {
        _alertController.sink.add(map);
      }
    } catch (_) {}
  }

  void _scheduleReconnect(String ipAddress) {
    Future.delayed(_reconnectDelay, () async {
      if (_state == CaregiverConnectionState.reconnecting) await connectToPrimaryUser(ipAddress);
    });
  }

  void disconnect() {
    _stopHeartbeat();
    _listenerIsolate?.kill(priority: Isolate.immediate);
    _activeSocket?.destroy();
    _activeSocket = null;
    _setState(CaregiverConnectionState.disconnected);
  }

  void _setState(CaregiverConnectionState next) {
    if (_state == next) return;
    _state = next;
    if (!_stateController.isClosed) _stateController.add(next);
  }

  void _handleError(String message) {}

  void dispose() {
    stopBroadcasting();
    disconnect();
    _alertController.close();
    _stateController.close();
    _fromIsolatePort?.close();
  }
}

class _IsolateArgs {
  final SendPort sendPort;
  final int socketPort;
  final String remoteAddress;
  const _IsolateArgs({required this.sendPort, required this.socketPort, required this.remoteAddress});
}
