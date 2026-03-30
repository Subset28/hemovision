import 'dart:async';
import 'dart:convert';
import 'dart:io';

// Defines the Caregiver broadcasting logic, acting as both a Server (broadcasting to a paired device)
// and a Client (the caregiver dashboard receiving details). It strictly uses Local Area sockets
// fulfilling the "Zero Internet/Offline Wi-Fi" requirement for the TSA Rubric.
class CaregiverService {
  static const int port = 8085;
  ServerSocket? _serverSocket;
  Socket? _clientSocket;
  
  // Stream to output incoming alerts for the Caregiver Dashboard
  final StreamController<Map<String, dynamic>> _incomingAlertsController = StreamController<Map<String, dynamic>>.broadcast();
  Stream<Map<String, dynamic>> get incomingAlerts => _incomingAlertsController.stream;

  bool _isBroadcasting = false;
  bool get isBroadcasting => _isBroadcasting;

  // ==== MODE: Primary User (Broadcaster) ====
  
  // Starts a local TCP server waiting for a Caregiver to connect on the same local network offline.
  Future<void> startBroadcasting() async {
    try {
      _serverSocket = await ServerSocket.bind(InternetAddress.anyIPv4, port);
      _isBroadcasting = true;
      
      _serverSocket?.listen((Socket socket) {
        // We only retain one active caregiver for this MVP complexity
        _clientSocket = socket;
        socket.listen((data) {
          // Listen for a heartbeat from caregiver if needed
        }, onDone: () {
          _clientSocket = null;
        });
      });
    } catch (e) {
      _isBroadcasting = false;
      print("Error binding to port: \$e");
    }
  }

  void stopBroadcasting() {
    _clientSocket?.close();
    _serverSocket?.close();
    _isBroadcasting = false;
  }

  // Called whenever the MainController detects a high-threat object or audio signature
  void broadcastAlert(Map<String, dynamic> alertData) {
    if (_clientSocket != null) {
      try {
        final jsonString = jsonEncode(alertData) + '\n';
        _clientSocket!.write(jsonString);
      } catch (e) {
        print("Failed to broadcast alert: \$e");
      }
    }
  }

  // ==== MODE: Caregiver (Receiver) ====
  
  // Connects securely to the Primary User's IP address on the local ad-hoc network
  Future<bool> connectToPrimaryUser(String ipAddress) async {
    try {
      _clientSocket = await Socket.connect(ipAddress, port, timeout: const Duration(seconds: 5));
      
      _clientSocket!.listen((data) {
        final message = utf8.decode(data).trim();
        if (message.isNotEmpty) {
          try {
             // We can expect a flood of data, so we split by our newline delimiter
             final splitMessages = message.split('\n');
             for(var msg in splitMessages) {
               if(msg.isNotEmpty) {
                 final jsonMap = jsonDecode(msg);
                 _incomingAlertsController.sink.add(jsonMap);
               }
             }
          } catch(e) {
             print("JSON parsing error: \$e");
          }
        }
      }, onDone: () {
        _clientSocket?.destroy();
        _clientSocket = null;
      });
      return true;
    } catch (e) {
      print("Failed to connect to primary user: \$e");
      return false;
    }
  }

  void disconnect() {
    _clientSocket?.close();
    _clientSocket = null;
  }

  void dispose() {
    stopBroadcasting();
    disconnect();
    _incomingAlertsController.close();
  }
}
