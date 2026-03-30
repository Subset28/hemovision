import 'package:flutter/material.dart';
import 'dart:ui';
import '../services/caregiver_service.dart';

class CaregiverView extends StatefulWidget {
  final CaregiverService service;
  
  const CaregiverView({super.key, required this.service});

  @override
  State<CaregiverView> createState() => _CaregiverViewState();
}

class _CaregiverViewState extends State<CaregiverView> {
  final TextEditingController _ipController = TextEditingController();
  List<Map<String, dynamic>> _alertHistory = [];
  bool _isConnected = false;

  @override
  void initState() {
    super.initState();
    widget.service.incomingAlerts.listen((alert) {
      if (mounted) {
        setState(() {
          _alertHistory.insert(0, alert);
          if (_alertHistory.length > 50) _alertHistory.removeLast(); 
        });
      }
    });
  }

  Future<void> _connect() async {
    final success = await widget.service.connectToPrimaryUser(_ipController.text);
    setState(() {
      _isConnected = success;
    });
    if (!success && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: const Text('Failed to connect. Ensure devices are on the same local offline hotspot.', style: TextStyle(color: Colors.white)),
          backgroundColor: Colors.redAccent.shade700,
          behavior: SnackBarBehavior.floating,
        ),
      );
    }
  }

  void _disconnect() {
    widget.service.disconnect();
    setState(() {
      _isConnected = false;
      _alertHistory.clear(); // Clear history on disconnect
    });
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        bool isDesktop = constraints.maxWidth > 800;
        
        return Scaffold(
          backgroundColor: const Color(0xFF07070A),
          extendBodyBehindAppBar: true,
          appBar: AppBar(
            title: const Text('CAREGIVER TELEMETRY DASHBOARD', style: TextStyle(fontWeight: FontWeight.w900, fontSize: 16, letterSpacing: 2.0)),
            backgroundColor: Colors.black.withOpacity(0.5),
            elevation: 0,
            centerTitle: true,
            flexibleSpace: ClipRect(
              child: BackdropFilter(
                filter: ImageFilter.blur(sigmaX: 10, sigmaY: 10),
                child: Container(color: Colors.transparent),
              ),
            ),
            actions: [
              Container(
                margin: const EdgeInsets.only(right: 20),
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                decoration: BoxDecoration(
                   color: _isConnected ? Colors.greenAccent.withOpacity(0.15) : Colors.redAccent.withOpacity(0.15),
                   borderRadius: BorderRadius.circular(30),
                   border: Border.all(color: _isConnected ? Colors.greenAccent.withOpacity(0.5) : Colors.redAccent.withOpacity(0.5))
                ),
                child: Row(
                  children: [
                    Icon(
                      _isConnected ? Icons.wifi_tethering : Icons.wifi_tethering_off,
                      color: _isConnected ? Colors.greenAccent : Colors.redAccent,
                      size: 16,
                    ),
                    const SizedBox(width: 8),
                    Text(_isConnected ? "LINKED" : "OFFLINE", style: TextStyle(color: _isConnected ? Colors.greenAccent : Colors.redAccent, fontWeight: FontWeight.bold, fontSize: 12, letterSpacing: 1.0)),
                  ],
                ),
              ),
            ],
          ),
          body: Padding(
            padding: EdgeInsets.fromLTRB(isDesktop ? 60 : 20, 100, isDesktop ? 60 : 20, 20),
            child: isDesktop ? _buildDesktopLayout() : _buildMobileLayout(),
          ),
        );
      }
    );
  }

  Widget _buildDesktopLayout() {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
         Expanded(
           flex: 4,
           child: _buildConnectionPanel(),
         ),
         const SizedBox(width: 40),
         Expanded(
           flex: 6,
           child: _buildAlertStream(),
         )
      ],
    );
  }

  Widget _buildMobileLayout() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _buildConnectionPanel(),
        const SizedBox(height: 24),
        _buildAnalyticsGraph(),
        const SizedBox(height: 24),
        Expanded(child: _buildAlertStream()),
      ],
    );
  }

  Widget _buildConnectionPanel() {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.03),
        borderRadius: BorderRadius.circular(32),
        border: Border.all(color: Colors.white.withOpacity(0.08), width: 1.5),
        boxShadow: [
          BoxShadow(color: Colors.black.withOpacity(0.5), blurRadius: 30, offset: const Offset(0, 15))
        ]
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(32),
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 20, sigmaY: 20),
          child: Padding(
            padding: const EdgeInsets.all(32.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(color: Colors.purpleAccent.withOpacity(0.15), borderRadius: BorderRadius.circular(16)),
                      child: Icon(Icons.hub_rounded, color: Colors.purpleAccent.shade100, size: 28),
                    ),
                    const SizedBox(width: 16),
                    const Text('Primary Socket Link', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.white)),
                  ],
                ),
                const SizedBox(height: 32),
                if (!_isConnected) ...[
                  TextField(
                    controller: _ipController,
                    style: const TextStyle(color: Colors.white, fontSize: 18),
                    decoration: InputDecoration(
                      labelText: 'TARGET LOCAL IPv4',
                      labelStyle: const TextStyle(color: Colors.white54, letterSpacing: 1.5, fontSize: 12),
                      filled: true,
                      fillColor: Colors.black.withOpacity(0.3),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(20),
                        borderSide: BorderSide.none,
                      ),
                      prefixIcon: const Icon(Icons.computer, color: Colors.white54),
                      hintText: 'e.g., 192.168.0.100',
                      hintStyle: const TextStyle(color: Colors.white24),
                    ),
                  ),
                  const SizedBox(height: 24),
                  ElevatedButton(
                    onPressed: _connect,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.purpleAccent.shade700,
                      foregroundColor: Colors.white,
                      elevation: 10,
                      shadowColor: Colors.purpleAccent.withOpacity(0.5),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
                      minimumSize: const Size.fromHeight(64),
                    ),
                    child: const Text('INITIALIZE CARE-LINK', style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16, letterSpacing: 1.5)),
                  )
                ] else ...[
                  Container(
                    padding: const EdgeInsets.all(24),
                    decoration: BoxDecoration(
                       color: Colors.greenAccent.withOpacity(0.05),
                       borderRadius: BorderRadius.circular(24),
                       border: Border.all(color: Colors.greenAccent.withOpacity(0.3), width: 2)
                    ),
                    child: Column(
                      children: [
                        const Icon(Icons.security, color: Colors.greenAccent, size: 48),
                        const SizedBox(height: 16),
                        const Text('SECURE LOCAL TELEMETRY BOUND', textAlign: TextAlign.center, style: TextStyle(color: Colors.greenAccent, fontSize: 14, fontWeight: FontWeight.bold, letterSpacing: 1.5)),
                        const SizedBox(height: 8),
                        Text('Listening for threats on Port 8085...', style: TextStyle(color: Colors.greenAccent.withOpacity(0.7), fontSize: 12)),
                      ],
                    ),
                  ),
                  const SizedBox(height: 24),
                  ElevatedButton(
                    onPressed: _disconnect,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.redAccent.withOpacity(0.1),
                      foregroundColor: Colors.redAccent,
                      elevation: 0,
                      side: BorderSide(color: Colors.redAccent.withOpacity(0.3), width: 1.5),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
                      minimumSize: const Size.fromHeight(64),
                    ),
                    child: const Text('TERMINATE LINK', style: TextStyle(fontWeight: FontWeight.bold, letterSpacing: 1.5)),
                  )
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildAnalyticsGraph() {
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.02),
        borderRadius: BorderRadius.circular(24),
        border: Border.all(color: Colors.white.withOpacity(0.05)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
               Icon(Icons.analytics_outlined, color: Colors.blueAccent.shade100, size: 20),
               const SizedBox(width: 12),
               const Text("THREAT DENSITY TOPOLOGY", style: TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.bold, letterSpacing: 1.5)),
            ],
          ),
          const SizedBox(height: 24),
          SizedBox(
            height: 120,
            width: double.infinity,
            child: CustomPaint(
              painter: TelemetryGraphPainter(_alertHistory),
            ),
          )
        ],
      ),
    );
  }

  Widget _buildAlertStream() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
           padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
           child: Row(
             mainAxisAlignment: MainAxisAlignment.spaceBetween,
             children: [
               const Text('LIVE THREAT FEED', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w900, color: Colors.white, letterSpacing: 2.0)),
               Container(
                 padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                 decoration: BoxDecoration(color: Colors.white10, borderRadius: BorderRadius.circular(20)),
                 child: Text('\${_alertHistory.length} Events Logged', style: const TextStyle(color: Colors.white70, fontSize: 12, fontWeight: FontWeight.bold)),
               )
             ],
           ),
        ),
        const SizedBox(height: 16),
        Expanded(
          child: _alertHistory.isEmpty
              ? Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.radar, size: 80, color: Colors.white.withOpacity(0.05)),
                      const SizedBox(height: 24),
                      Text("AWAITING INCOMING TELEMETRY...", style: TextStyle(color: Colors.white.withOpacity(0.2), letterSpacing: 2.0, fontWeight: FontWeight.bold)),
                    ],
                  ),
                )
              : ListView.builder(
                  itemCount: _alertHistory.length,
                  itemBuilder: (context, index) {
                    final alert = _alertHistory[index];
                    final isCritical = alert['threatLevel'] != null && alert['threatLevel'] > 80;
                    
                    String direction = alert['direction'] ?? 'Unknown';
                    String info = alert['info'] ?? '';
                    String nowStr = "${DateTime.now().hour}:${DateTime.now().minute.toString().padLeft(2, '0')}:${DateTime.now().second.toString().padLeft(2, '0')}";

                    return Container(
                      margin: const EdgeInsets.only(bottom: 16),
                      decoration: BoxDecoration(
                         color: isCritical ? Colors.redAccent.withOpacity(0.1) : Colors.white.withOpacity(0.02),
                         borderRadius: BorderRadius.circular(20),
                         border: Border.all(color: isCritical ? Colors.redAccent.withOpacity(0.5) : Colors.white.withOpacity(0.05), width: isCritical ? 2 : 1),
                      ),
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(20),
                        child: BackdropFilter(
                          filter: ImageFilter.blur(sigmaX: 10, sigmaY: 10),
                          child: Padding(
                            padding: const EdgeInsets.all(20.0),
                            child: Row(
                              children: [
                                Container(
                                   padding: const EdgeInsets.all(16),
                                   decoration: BoxDecoration(
                                      color: isCritical ? Colors.redAccent.withOpacity(0.2) : Colors.orangeAccent.withOpacity(0.15),
                                      shape: BoxShape.circle,
                                   ),
                                   child: Icon(
                                     alert['type'] == 'Siren Detection' ? Icons.campaign_rounded : Icons.warning_amber_rounded,
                                     color: isCritical ? Colors.redAccent : Colors.orangeAccent,
                                     size: 28,
                                   ),
                                ),
                                const SizedBox(width: 20),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text(alert['type']?.toString().toUpperCase() ?? 'UNKNOWN EVENT', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.black, fontSize: 16, letterSpacing: 1.0)),
                                      const SizedBox(height: 6),
                                      Text('DIRECTION: \${direction.toUpperCase()}  |  INFO: \${info.toUpperCase()}', style: TextStyle(color: Colors.white.withOpacity(0.6), fontSize: 12, fontWeight: FontWeight.bold, letterSpacing: 0.5)),
                                    ],
                                  ),
                                ),
                                Column(
                                  mainAxisAlignment: MainAxisAlignment.center,
                                  crossAxisAlignment: CrossAxisAlignment.end,
                                  children: [
                                    const Text("TIMESTAMP", style: TextStyle(color: Colors.white30, fontSize: 10, fontWeight: FontWeight.bold, letterSpacing: 1.0)),
                                    const SizedBox(height: 4),
                                    Text(nowStr, style: const TextStyle(color: Colors.white70, fontWeight: FontWeight.bold, fontSize: 14)),
                                  ],
                                )
                              ],
                            ),
                          ),
                        ),
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }
}

class TelemetryGraphPainter extends CustomPainter {
  final List<Map<String, dynamic>> history;
  
  TelemetryGraphPainter(this.history);

  @override
  void paint(Canvas canvas, Size size) {
    if (history.isEmpty) return;

    final paintLine = Paint()
      ..color = Colors.blueAccent
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3.0
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;

    final paintFill = Paint()
      ..style = PaintingStyle.fill
      ..shader = LinearGradient(
        colors: [Colors.blueAccent.withOpacity(0.5), Colors.blueAccent.withOpacity(0.0)],
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
      ).createShader(Rect.fromLTWH(0, 0, size.width, size.height));

    final path = Path();
    final fillPath = Path();

    // Map history to points (max 20 points for graph)
    int maxPts = 20;
    List<double> values = [];
    for (int i = 0; i < maxPts; i++) {
      if (i < history.length) {
        values.add(history[i]['threatLevel'] ?? 0.0);
      } else {
        values.add(0.0); // fill remaining with 0 or repeat
      }
    }
    // Reverse so newest is on right
    values = values.reversed.toList();

    double dx = size.width / (maxPts - 1);
    
    path.moveTo(0, size.height - (values[0] / 100.0 * size.height));
    fillPath.moveTo(0, size.height);
    fillPath.lineTo(0, size.height - (values[0] / 100.0 * size.height));

    for (int i = 1; i < values.length; i++) {
      double x = i * dx;
      double y = size.height - ((values[i] / 100.0).clamp(0.0, 1.0) * size.height);
      
      // Bezier curve smoothing
      double prevX = (i - 1) * dx;
      double prevY = size.height - ((values[i - 1] / 100.0).clamp(0.0, 1.0) * size.height);
      
      path.quadraticBezierTo(
        prevX + dx / 2, prevY, 
        prevX + dx / 2, y, 
      );
      path.lineTo(x, y);

      fillPath.lineTo(x, y);
    }

    fillPath.lineTo(size.width, size.height);
    fillPath.close();

    canvas.drawPath(fillPath, paintFill);
    canvas.drawPath(path, paintLine);
    
    // Draw Grid Lines
    final gridPaint = Paint()..color = Colors.white10..strokeWidth = 1;
    canvas.drawLine(Offset(0, size.height/2), Offset(size.width, size.height/2), gridPaint);
    canvas.drawLine(Offset(0, size.height), Offset(size.width, size.height), gridPaint);
  }

  @override
  bool shouldRepaint(covariant TelemetryGraphPainter oldDelegate) => true;
}
