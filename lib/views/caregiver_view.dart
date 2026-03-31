import 'package:flutter/material.dart';
import 'dart:ui';
import 'package:google_fonts/google_fonts.dart';
import '../services/caregiver_service.dart';

// ─────────────────────────────────────────────────────────────────
//  DESIGN TOKENS (Shared System)
// ─────────────────────────────────────────────────────────────────
const Color kObsidian = Color(0xFF030305);
const Color kDeepNavy = Color(0xFF0A0A14);
const Color kNeonCyan = Color(0xFF00FFD1);
const Color kCyberBlue = Color(0xFF2E6FF2);
const Color kEmergencyRed = Color(0xFFFF3131);
const Color kAmberAlert = Color(0xFFFFB800);

class CaregiverView extends StatefulWidget {
  final CaregiverService service;
  const CaregiverView({super.key, required this.service});

  @override
  State<CaregiverView> createState() => _CaregiverViewState();
}

class _CaregiverViewState extends State<CaregiverView> with SingleTickerProviderStateMixin {
  final TextEditingController _ipController = TextEditingController();
  List<Map<String, dynamic>> _alertHistory = [];
  bool _isConnected = false;
  late AnimationController _pulseCtrl;

  @override
  void initState() {
    super.initState();
    _pulseCtrl = AnimationController(vsync: this, duration: const Duration(seconds: 2))..repeat();
    
    widget.service.incomingAlerts.listen((alert) {
      if (mounted) {
        setState(() {
          _alertHistory.insert(0, alert);
          if (_alertHistory.length > 50) _alertHistory.removeLast(); 
        });
      }
    });
  }

  @override
  void dispose() {
    _pulseCtrl.dispose();
    _ipController.dispose();
    super.dispose();
  }

  Future<void> _connect() async {
    final result = await widget.service.connectToPrimaryUser(_ipController.text);
    setState(() { _isConnected = result.connected; });
    if (!result.connected && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('LINK ESTABLISHMENT FAILED', style: GoogleFonts.orbitron(color: Colors.white, fontSize: 12)),
          backgroundColor: kEmergencyRed.withValues(alpha: 0.9),
          behavior: SnackBarBehavior.floating,
        ),
      );
    }
  }

  void _disconnect() {
    widget.service.disconnect();
    setState(() {
      _isConnected = false;
      _alertHistory.clear();
    });
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, constraints) {
      final isDesktop = constraints.maxWidth > 800;
      return Scaffold(
        backgroundColor: kObsidian,
        extendBodyBehindAppBar: true,
        appBar: _buildAppBar(),
        body: Stack(
          children: [
            // Ambient Background Pulse
            Positioned.fill(
              child: Opacity(
                opacity: 0.05,
                child: CustomPaint(painter: PulseWaveformPainter(
                  value: _pulseCtrl.value, 
                  devicePixelRatio: View.of(context).devicePixelRatio,
                )),
              ),
            ),
            Padding(
              padding: EdgeInsets.fromLTRB(isDesktop ? 60 : 20, 120, isDesktop ? 60 : 20, 20),
              child: isDesktop ? _buildDesktopLayout() : _buildMobileLayout(),
            ),
          ],
        ),
      );
    });
  }

  PreferredSizeWidget _buildAppBar() {
    return AppBar(
      title: Text('TELEMETRY DASHBOARD', 
        style: GoogleFonts.orbitron(fontWeight: FontWeight.w900, fontSize: 14, letterSpacing: 4.0, color: kNeonCyan)),
      backgroundColor: Colors.black.withValues(alpha: 0.4),
      elevation: 0,
      centerTitle: true,
      flexibleSpace: ClipRect(
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 15, sigmaY: 15),
          child: Container(color: Colors.transparent),
        ),
      ),
      actions: [
        _buildStatusIndicator(),
        const SizedBox(width: 20),
      ],
    );
  }

  Widget _buildStatusIndicator() {
    final color = _isConnected ? Colors.greenAccent : kEmergencyRed;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(30),
        border: Border.all(color: color.withValues(alpha: 0.3), width: 1.0),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 8, height: 8,
            decoration: BoxDecoration(shape: BoxShape.circle, color: color, boxShadow: [BoxShadow(color: color, blurRadius: 4)]),
          ),
          const SizedBox(width: 10),
          Text(_isConnected ? "AIR-GAPPED CHANNEL" : "OFFLINE", 
            style: GoogleFonts.inter(color: color, fontWeight: FontWeight.w900, fontSize: 10, letterSpacing: 1.5)),
        ],
      ),
    );
  }

  Widget _buildDesktopLayout() {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(flex: 4, child: _buildConnectionPanel()),
        const SizedBox(width: 40),
        Expanded(flex: 6, child: _buildAlertStream()),
      ],
    );
  }

  Widget _buildMobileLayout() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _buildConnectionPanel(),
        const SizedBox(height: 24),
        _buildAnalyticsSummary(),
        const SizedBox(height: 32),
        Expanded(child: _buildAlertStream()),
      ],
    );
  }

  Widget _buildConnectionPanel() {
    return ClipRRect(
      borderRadius: BorderRadius.circular(24),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 20, sigmaY: 20),
        child: Container(
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: 0.03),
            borderRadius: BorderRadius.circular(24),
            border: Border.all(color: Colors.white.withValues(alpha: 0.1), width: 1.2),
          ),
          padding: const EdgeInsets.all(32.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                children: [
                  Icon(Icons.terminal_rounded, color: kNeonCyan, size: 20),
                  const SizedBox(width: 12),
                  Text('NETWORK UPLINK', 
                    style: GoogleFonts.orbitron(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.white, letterSpacing: 1.2)),
                ],
              ),
              const SizedBox(height: 32),
              if (!_isConnected) ...[
                TextField(
                  controller: _ipController,
                  style: GoogleFonts.jetBrainsMono(color: Colors.white, fontSize: 16),
                  decoration: InputDecoration(
                    labelText: 'PRIMARY IPv4 ADDRESS',
                    labelStyle: GoogleFonts.inter(color: Colors.white38, letterSpacing: 1.5, fontSize: 10, fontWeight: FontWeight.w700),
                    filled: true,
                    fillColor: Colors.black.withValues(alpha: 0.4),
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: BorderSide.none),
                    prefixIcon: const Icon(Icons.lan_outlined, color: Colors.white54, size: 20),
                    hintText: '192.168.X.X',
                    hintStyle: const TextStyle(color: Colors.white10),
                  ),
                ),
                const SizedBox(height: 24),
                ElevatedButton(
                  onPressed: _connect,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: kCyberBlue,
                    foregroundColor: Colors.white,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                    minimumSize: const Size.fromHeight(60),
                  ),
                  child: Text('INITIALIZE CARE-LINK', 
                    style: GoogleFonts.orbitron(fontWeight: FontWeight.w800, fontSize: 14, letterSpacing: 1.5)),
                )
              ] else ...[
                _buildActiveLinkInfo(),
                TextButton(
                  onPressed: _disconnect,
                  child: Text('TERMINATE SECURE LINK', 
                    style: GoogleFonts.inter(color: kEmergencyRed.withValues(alpha: 0.7), fontWeight: FontWeight.w900, fontSize: 11, letterSpacing: 2.0)),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildActiveLinkInfo() {
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: kNeonCyan.withValues(alpha: 0.04),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: kNeonCyan.withValues(alpha: 0.2)),
      ),
      child: Column(
        children: [
          Icon(Icons.verified_user_rounded, color: kNeonCyan, size: 40),
          const SizedBox(height: 16),
          Text('ENCRYPTED TELEMETRY ACTIVE', 
            textAlign: TextAlign.center,
            style: GoogleFonts.orbitron(color: kNeonCyan, fontSize: 12, fontWeight: FontWeight.w800, letterSpacing: 1.2)),
          const SizedBox(height: 12),
          Text('TCP Node: 8085 / Listening', 
            style: GoogleFonts.jetBrainsMono(color: kNeonCyan.withValues(alpha: 0.5), fontSize: 10)),
        ],
      ),
    );
  }

  Widget _buildAnalyticsSummary() {
    return Row(
      children: [
        _metricTile('SIGNAL', '98%', kNeonCyan),
        const SizedBox(width: 20),
        _metricTile('LATENCY', '14ms', kCyberBlue),
      ],
    );
  }

  Widget _metricTile(String label, String value, Color color) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.04),
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: color.withValues(alpha: 0.12)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
             Text(label, style: GoogleFonts.inter(color: Colors.white24, fontSize: 9, fontWeight: FontWeight.w800, letterSpacing: 2.0)),
             const SizedBox(height: 8),
             Text(value, style: GoogleFonts.orbitron(color: color, fontSize: 22, fontWeight: FontWeight.bold)),
          ],
        ),
      ),
    );
  }

  Widget _buildAlertStream() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _sectionHeader('LIVE THREAT FEED', Icons.sensors_rounded),
        const SizedBox(height: 20),
        Expanded(
          child: _alertHistory.isEmpty ? _buildEmptyState() : _buildHistoryList(),
        ),
      ],
    );
  }

  Widget _sectionHeader(String title, IconData icon) {
    return Row(
      children: [
        Icon(icon, color: Colors.white38, size: 16),
        const SizedBox(width: 12),
        Text(title, style: GoogleFonts.orbitron(fontSize: 12, fontWeight: FontWeight.w900, color: Colors.white54, letterSpacing: 2.5)),
      ],
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.radar_rounded, size: 60, color: Colors.white.withValues(alpha: 0.03)),
          const SizedBox(height: 20),
          Text("AWAITING TELEMETRY BURST...", 
            style: GoogleFonts.orbitron(color: Colors.white.withValues(alpha: 0.15), fontSize: 10, letterSpacing: 2.0)),
        ],
      ),
    );
  }

  Widget _buildHistoryList() {
    return ListView.builder(
      padding: EdgeInsets.zero,
      itemCount: _alertHistory.length,
      itemBuilder: (context, index) {
        final alert = _alertHistory[index];
        final isCritical = alert['threatLevel'] != null && alert['threatLevel'] > 80;
        final color = isCritical ? kEmergencyRed : kAmberAlert;
        
        return Container(
          margin: const EdgeInsets.only(bottom: 12),
          decoration: BoxDecoration(
             color: color.withValues(alpha: 0.04),
             borderRadius: BorderRadius.circular(16),
             border: Border.all(color: color.withValues(alpha: 0.15), width: isCritical ? 1.5 : 0.8),
          ),
          child: ListTile(
            contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
            leading: _alertIcon(alert['type'], color),
            title: Text(alert['type']?.toString().toUpperCase() ?? 'EVENT', 
              style: GoogleFonts.orbitron(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 13, letterSpacing: 1.0)),
            subtitle: Text(
              '${alert['direction']} | ${alert['info']}'.toUpperCase(),
              style: GoogleFonts.inter(
                color: Colors.white30,
                fontSize: 9,
                fontWeight: FontWeight.w700,
                letterSpacing: 0.5,
              ),
            ),
            trailing: Text(
              '${DateTime.now().hour}:${DateTime.now().minute.toString().padLeft(2, '0')}',
              style: GoogleFonts.jetBrainsMono(
                color: color.withValues(alpha: 0.5),
                fontSize: 12,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _alertIcon(dynamic type, Color color) {
    IconData icon = type == 'Siren Detection' ? Icons.campaign_rounded : Icons.warning_amber_rounded;
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.1), shape: BoxShape.circle),
      child: Icon(icon, color: color, size: 20),
    );
  }
}

// ─────────────────────────────────────────────────────────────────
//  PULSE WAVEFORM PAINTER
// ─────────────────────────────────────────────────────────────────
class PulseWaveformPainter extends CustomPainter {
  final double value;
  final double devicePixelRatio;
  PulseWaveformPainter({required this.value, required this.devicePixelRatio});

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = kNeonCyan.withValues(alpha: 0.3)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5;

    final path = Path();
    for (double i = 0; i < size.width; i++) {
       double y = (size.height / 2) + (size.height / 4) * 
          (devicePixelRatio * (i / 100 + value * 5).sin());
       if (i == 0) path.moveTo(i, y); else path.lineTo(i, y);
    }
    canvas.drawPath(path, paint);
  }

  @override
  bool shouldRepaint(PulseWaveformPainter old) => true;
}

extension on double {
  double sin() => (this * 3.14159 * 2); 
}
