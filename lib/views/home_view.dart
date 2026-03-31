import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'dart:async';
import 'dart:ui';
import 'package:google_fonts/google_fonts.dart';
import '../controllers/main_controller.dart';
import '../engines/vision_engine.dart';
import '../services/caregiver_service.dart';
import 'caregiver_view.dart';
import 'settings_view.dart';

// ─────────────────────────────────────────────────────────────────
//  DESIGN TOKENS (Cyber-Medical System)
// ─────────────────────────────────────────────────────────────────
const Color kObsidian = Color(0xFF030305);
const Color kDeepNavy = Color(0xFF0A0A14);
const Color kNeonCyan = Color(0xFF00FFD1);
const Color kCyberBlue = Color(0xFF2E6FF2);
const Color kEmergencyRed = Color(0xFFFF3131);
const Color kAmberAlert = Color(0xFFFFB800);
const double kGlassBlur = 20.0;
const double kThinBorder = 1.2;

class HomeView extends StatefulWidget {
  const HomeView({super.key});

  @override
  State<HomeView> createState() => _HomeViewState();
}

class _HomeViewState extends State<HomeView>
    with TickerProviderStateMixin {
  late MainController _controller;

  List<DetectedObjectData> _detectedObjects = [];
  List<SpatialPointData> _spatialMap = [];
  AudioAlertData? _currentAlert;
  Map<String, dynamic> _stats = {};
  CaregiverConnectionState _caregiverState = CaregiverConnectionState.disconnected;

  // Animations
  late AnimationController _pulseCtrl;
  late Animation<double> _pulseAnim;
  late AnimationController _alertCtrl;
  late Animation<double> _alertAnim;
  late AnimationController _glowCtrl;
  late Animation<double> _glowAnim;
  late AnimationController _scanningCtrl;
  late Animation<double> _scanningAnim;

  @override
  void initState() {
    super.initState();
    _controller = MainController();

    // Subscribe to streams
    _controller.detectedObjectsStream.listen((o) {
      if (mounted) setState(() => _detectedObjects = o);
    });
    _controller.spatialMapStream.listen((m) {
      if (mounted) setState(() => _spatialMap = m);
    });
    _controller.audioAlertStream.listen((a) {
      if (mounted) {
        setState(() => _currentAlert = a);
        HapticFeedback.heavyImpact();
        _alertCtrl.forward(from: 0);
        Future.delayed(const Duration(seconds: 4), () {
          if (mounted && _currentAlert == a) {
            setState(() => _currentAlert = null);
          }
        });
      }
    });

    _controller.caregiverService.stateStream.listen((state) {
      if (mounted) setState(() => _caregiverState = state);
    });

    _controller.statsStream.listen((s) {
      if (mounted) setState(() => _stats = s);
    });

    _controller.accessStream.listen((_) {
      if (mounted) setState(() {});
    });

    _controller.startProcessing();

    // Pulse animation (radar sweep)
    _pulseCtrl = AnimationController(
        vsync: this, duration: const Duration(milliseconds: 1200))
      ..repeat(reverse: true);
    _pulseAnim = Tween<double>(begin: 0.7, end: 1.3)
        .animate(CurvedAnimation(parent: _pulseCtrl, curve: Curves.easeInOut));

    // Alert flash animation
    _alertCtrl = AnimationController(
        vsync: this, duration: const Duration(milliseconds: 600));
    _alertAnim = Tween<double>(begin: 0.0, end: 1.0)
        .animate(CurvedAnimation(parent: _alertCtrl, curve: Curves.easeOut));

    // Ambient glow cycling
    _glowCtrl = AnimationController(
        vsync: this, duration: const Duration(seconds: 3))
      ..repeat(reverse: true);
    _glowAnim = Tween<double>(begin: 0.03, end: 0.12)
        .animate(CurvedAnimation(parent: _glowCtrl, curve: Curves.easeInOut));

    // Scanning line animation
    _scanningCtrl = AnimationController(
        vsync: this, duration: const Duration(seconds: 4))
      ..repeat();
    _scanningAnim = Tween<double>(begin: 0.0, end: 1.0)
        .animate(CurvedAnimation(parent: _scanningCtrl, curve: Curves.linear));
  }

  @override
  void dispose() {
    _controller.dispose();
    _pulseCtrl.dispose();
    _alertCtrl.dispose();
    _glowCtrl.dispose();
    _scanningCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, constraints) {
      final isDesktop = constraints.maxWidth > 800;
      return Scaffold(
        backgroundColor: kObsidian,
        body: isDesktop ? _buildDesktopLayout() : _buildMobileLayout(),
      );
    });
  }

  // ── LAYOUTS ──────────────────────────────────────────────────

  Widget _buildDesktopLayout() {
    return Row(
      children: [
        // ── Camera Feed + HUD (70%) ─────────────────────────
        Expanded(
          flex: 7,
          child: Stack(
            fit: StackFit.expand,
            children: [
              _buildCameraFeed(),
              _buildObjectOverlays(_detectedObjects),
              if (_currentAlert != null) _buildAlertHUD(),
              _buildTopBar(isDesktop: true),
              Positioned(
                bottom: 24,
                left: 24,
                child: _buildModeIndicator(),
              ),
            ],
          ),
        ),
        // ── Sidebar Dashboard (30%) ─────────────────────────
        SizedBox(
          width: 340,
          child: Container(
            decoration: const BoxDecoration(
              color: kDeepNavy,
              border: Border(
                  left: BorderSide(color: Color(0xFF1A1A2E), width: 1.5)),
            ),
            child: _buildSidebar(),
          ),
        ),
      ],
    );
  }

  Widget _buildMobileLayout() {
    return Stack(
      fit: StackFit.expand,
      children: [
        _buildCameraFeed(),
        _buildObjectOverlays(_detectedObjects),
        if (_currentAlert != null) _buildAlertHUD(),
        _buildTopBar(isDesktop: false),
        _buildMobileBottomPanel(),
        Positioned(
          bottom: 180,
          right: 20,
          child: _buildModeIndicator(),
        ),
      ],
    );
  }

  // ── CAMERA FEED ──────────────────────────────────────────────
  Widget _buildCameraFeed() {
    return AnimatedBuilder(
      animation: Listenable.merge([_glowCtrl, _scanningCtrl, _pulseCtrl]),
      builder: (context, _) => Stack(
        fit: StackFit.expand,
        children: [
          CustomPaint(
            painter: TacticalGridPainter(_pulseAnim.value),
          ),
          Container(
            decoration: BoxDecoration(
              gradient: RadialGradient(
                center: const Alignment(0, -0.8),
                radius: 1.2,
                colors: [
                  kNeonCyan.withValues(alpha: _glowAnim.value),
                  Colors.transparent,
                ],
              ),
            ),
            child: CustomPaint(
              painter: ScanningOverlayPainter(_scanningAnim.value),
              child: Center(
                child: Opacity(
                  opacity: 0.1,
                  child: Icon(Icons.remove_red_eye_outlined,
                      size: 90, color: kNeonCyan),
                ),
              ),
            ),
          ),
          Center(
            child: Padding(
              padding: const EdgeInsets.only(top: 140),
              child: _buildScanningStatus(),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildScanningStatus() {
    return ClipRRect(
      borderRadius: BorderRadius.circular(30),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 10, sigmaY: 10),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
          decoration: BoxDecoration(
            color: Colors.black.withValues(alpha: 0.4),
            borderRadius: BorderRadius.circular(30),
            border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              const SizedBox(
                width: 12,
                height: 12,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: kNeonCyan,
                ),
              ),
              const SizedBox(width: 14),
              Text(
                'ENVIRONMENT SCAN ACTIVE',
                style: GoogleFonts.inter(
                  color: kNeonCyan.withValues(alpha: 0.4),
                  fontSize: 10,
                  letterSpacing: 3.5,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  // ── TOP BAR ──────────────────────────────────────────────────
  Widget _buildTopBar({required bool isDesktop}) {
    return Positioned(
      top: isDesktop ? 24 : 48,
      left: 20,
      right: 20,
      child: Row(
        children: [
          if (!isDesktop) ...[
            _buildGlassChip(
              label: 'OmniSight',
              icon: Icons.remove_red_eye_outlined,
              color: kNeonCyan,
            ),
            const Spacer(),
          ],
          _buildGlassChip(
            label: 'Module A • 8D Audio',
            color: kCyberBlue,
          ),
          const SizedBox(width: 10),
          _buildGlassChip(
            label: 'Module B • AR Haptics',
            color: Colors.orangeAccent,
          ),
          _buildOfflineStatusChip(),
          const SizedBox(width: 10),
          _buildConnectionStatusChip(),
          if (isDesktop) const Spacer(),
        ],
      ),
    );
  }

  Widget _buildOfflineStatusChip() {
    return _buildGlassChip(
      label: 'Local-First Engine',
      color: kNeonCyan,
      icon: Icons.offline_bolt_rounded,
    );
  }

  Widget _buildConnectionStatusChip() {
    Color color;
    String label;
    IconData icon;

    switch (_caregiverState) {
      case CaregiverConnectionState.disconnected:
        color = Colors.white24;
        label = 'Caregiver Off';
        icon = Icons.cloud_off_rounded;
        break;
      case CaregiverConnectionState.listening:
        color = kCyberBlue;
        label = 'Waiting...';
        icon = Icons.sync_rounded;
        break;
      case CaregiverConnectionState.connected:
        color = Colors.greenAccent;
        label = 'Caregiver Linked';
        icon = Icons.verified_user_rounded;
        break;
      case CaregiverConnectionState.unstable:
        color = kAmberAlert;
        label = 'Signal Weak';
        icon = Icons.signal_cellular_connected_no_internet_4_bar_rounded;
        break;
      default:
        color = kEmergencyRed;
        label = 'Error';
        icon = Icons.error_outline_rounded;
    }

    return _buildGlassChip(label: label, color: color, icon: icon);
  }

  Widget _buildGlassChip({
    required String label,
    Color color = Colors.white,
    IconData? icon,
  }) {
    final bool hc = _controller.highContrast;
    final bool lt = _controller.largeText;
    final Color effectiveColor = hc ? Colors.white : color;

    return ClipRRect(
      borderRadius: BorderRadius.circular(30),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: kGlassBlur, sigmaY: kGlassBlur),
        child: Container(
          padding: EdgeInsets.symmetric(
              horizontal: lt ? 18 : 14, vertical: lt ? 10 : 8),
          decoration: BoxDecoration(
            color: hc ? Colors.black : Colors.black.withValues(alpha: 0.45),
            borderRadius: BorderRadius.circular(30),
            border: Border.all(
                color: effectiveColor.withValues(alpha: hc ? 0.8 : 0.3),
                width: hc ? 2.0 : kThinBorder),
            boxShadow: [
              BoxShadow(
                color: effectiveColor.withValues(alpha: hc ? 0.2 : 0.1),
                blurRadius: 10,
                spreadRadius: -2,
              ),
            ],
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (icon != null) ...[
                Icon(icon, size: lt ? 18 : 15, color: effectiveColor),
                SizedBox(width: lt ? 12 : 8),
              ] else ...[
                Container(
                  width: lt ? 10 : 8,
                  height: lt ? 10 : 8,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: effectiveColor,
                    boxShadow: [
                      BoxShadow(color: effectiveColor, blurRadius: 6)
                    ],
                  ),
                ),
                SizedBox(width: lt ? 12 : 10),
              ],
              Text(label,
                  style: GoogleFonts.inter(
                    color: Colors.white,
                    fontWeight: FontWeight.w900,
                    fontSize: lt ? 13 : 10,
                    letterSpacing: lt ? 1.5 : 1.2,
                  )),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildObjectOverlays(List<DetectedObjectData> objects) {
    return Stack(
      children: objects.map((obj) {
        final x = obj.x;
        final y = obj.y;
        final w = obj.width;
        final h = obj.height;
        final dist = obj.distance;
        final threat = obj.threatLevel;
        final int classId = obj.classId;
        final bool isCritical = obj.isCritical;

        final bool hc = _controller.highContrast;
        final bool lt = _controller.largeText;
        final Color effectiveBoxColor = hc
            ? Colors.white
            : (isCritical ? Colors.redAccent : Colors.greenAccent);

        final String label = obj.label;
        final IconData icon = _iconFor(classId);

        return Positioned(
          left: x - w / 2,
          top: y - h / 2,
          child: Semantics(
            label: 'Detected $label at $dist ${dist == 1.0 ? 'meter' : 'meters'}',
            hint: isCritical
                ? 'CRITICAL OBSTACLE — TAKE ACTION'
                : 'Environment object',
            value: 'Threat level ${threat.toInt()} percent',
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 80),
              width: w,
              height: h,
              decoration: BoxDecoration(
                border: Border.all(
                    color: effectiveBoxColor,
                    width: (hc || isCritical) ? 3.0 : 1.5),
                borderRadius: BorderRadius.circular(10),
                boxShadow: [
                  BoxShadow(
                      color:
                          effectiveBoxColor.withValues(alpha: isCritical ? 0.4 : 0.2),
                      blurRadius: 14,
                      spreadRadius: 2),
                ],
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    padding: EdgeInsets.symmetric(
                        horizontal: lt ? 12 : 8, vertical: lt ? 6 : 4),
                    decoration: BoxDecoration(
                      color: effectiveBoxColor.withValues(alpha: 0.95),
                      borderRadius: const BorderRadius.only(
                        topLeft: Radius.circular(8),
                        bottomRight: Radius.circular(8),
                      ),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(icon, size: lt ? 16 : 12, color: Colors.black87),
                        SizedBox(width: lt ? 8 : 5),
                        Text(
                          '$label  ${dist.toStringAsFixed(1)}m',
                          style: GoogleFonts.inter(
                            color: Colors.black87,
                            fontWeight: FontWeight.w900,
                            fontSize: lt ? 14 : 11,
                            letterSpacing: 0.4,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const Spacer(),
                  if (isCritical || hc)
                    Padding(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 6, vertical: 4),
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(4),
                        child: LinearProgressIndicator(
                          value: threat / 100.0,
                          backgroundColor: Colors.black45,
                          valueColor:
                              AlwaysStoppedAnimation<Color>(effectiveBoxColor),
                          minHeight: 3,
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ),
        );
      }).toList(),
    );
  }

  Widget _buildAlertHUD() {
    return Positioned.fill(
      child: IgnorePointer(
        child: AnimatedBuilder(
          animation: _pulseAnim,
          builder: (context, _) {
            final opacity =
                0.4 + 0.6 * ((_pulseAnim.value - 0.7) / 0.6).clamp(0.0, 1.0);
            return Stack(
              fit: StackFit.expand,
              children: [
                Container(
                  decoration: BoxDecoration(
                    border: Border.all(
                      color: Colors.redAccent.withValues(alpha: opacity * 0.7),
                      width: 20 * (_pulseAnim.value - 0.7),
                    ),
                  ),
                ),
                Center(
                  child: SlideTransition(
                    position: Tween<Offset>(
                            begin: const Offset(0, -0.3), end: Offset.zero)
                        .animate(CurvedAnimation(
                            parent: _alertCtrl, curve: Curves.easeOut)),
                    child: FadeTransition(
                      opacity: _alertAnim,
                      child: _buildAlertCard(),
                    ),
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }

  Widget _buildAlertCard() {
    final type = _currentAlert!.type;
    final direction = _currentAlert!.direction;

    return Semantics(
      label: 'URGENT HUD ALERT: $type from $direction',
      hint: 'Critical environmental threat detected',
      liveRegion: true,
      container: true,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(24),
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 20, sigmaY: 20),
          child: Container(
            padding: const EdgeInsets.symmetric(vertical: 32, horizontal: 48),
            decoration: BoxDecoration(
              color: Colors.redAccent.withValues(alpha: 0.75),
              borderRadius: BorderRadius.circular(24),
              border: Border.all(color: Colors.white.withValues(alpha: 0.3)),
              boxShadow: [
                BoxShadow(
                    color: Colors.redAccent.withValues(alpha: 0.5), blurRadius: 60),
              ],
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.warning_amber_rounded,
                    size: 70, color: Colors.white),
                const SizedBox(height: 16),
                Text(
                  type.toUpperCase(),
                  textAlign: TextAlign.center,
                  style: GoogleFonts.inter(
                    fontSize: 26,
                    fontWeight: FontWeight.w900,
                    color: Colors.white,
                    letterSpacing: 2.0,
                  ),
                ),
                const SizedBox(height: 10),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Text(
                    'DIRECTION: ${direction.toUpperCase()}',
                    style: GoogleFonts.inter(
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                      color: Colors.white,
                      letterSpacing: 1.5,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildModeIndicator() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: Colors.amber.withValues(alpha: 0.4)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 7,
            height: 7,
            decoration: const BoxDecoration(
                shape: BoxShape.circle, color: Colors.amberAccent),
          ),
          const SizedBox(width: 8),
          Text('MOCK MODE',
              style: GoogleFonts.inter(
                fontSize: 10,
                color: Colors.amberAccent,
                fontWeight: FontWeight.w700,
                letterSpacing: 1.5,
              )),
        ],
      ),
    );
  }

  Widget _buildSidebar() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: 36),
          Row(children: [
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: const Color(0xFF00E5FF).withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(14),
              ),
              child: const Icon(Icons.remove_red_eye_outlined,
                  color: Color(0xFF00E5FF), size: 24),
            ),
            const SizedBox(width: 14),
            Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('OmniSight',
                  style: GoogleFonts.inter(
                      color: Colors.white,
                      fontSize: 20,
                      fontWeight: FontWeight.w900,
                      letterSpacing: -0.5)),
              Text('Engine v1.0',
                  style: GoogleFonts.inter(
                      color: const Color(0xFF00E5FF),
                      fontSize: 11,
                      letterSpacing: 2.0)),
            ]),
          ]),
          const SizedBox(height: 32),
          _sectionLabel('LIVE TELEMETRY'),
          const SizedBox(height: 12),
          _buildStatsGrid(),
          const SizedBox(height: 28),
          _sectionLabel('SLAM TOPOGRAPHY'),
          const SizedBox(height: 12),
          _buildRadarWidget(),
          const SizedBox(height: 28),
          _sectionLabel('ACCESSIBILITY MODULES'),
          const SizedBox(height: 12),
          _buildModuleButton(
            icon: Icons.surround_sound_rounded,
            label: 'Spatial 8D Audio',
            sub: 'Distance → Direction mapping',
            color: Colors.blueAccent,
          ),
          const SizedBox(height: 12),
          _buildModuleButton(
            icon: Icons.vibration_rounded,
            label: 'AR Haptic Alerts',
            sub: 'Siren & obstacle vibration',
            color: Colors.orangeAccent,
          ),
          const SizedBox(height: 28),
          _sectionLabel('CAREGIVER NETWORK'),
          const SizedBox(height: 12),
          _buildToggleSyncButton(),
          const SizedBox(height: 12),
          _buildModuleButton(
            icon: Icons.admin_panel_settings_rounded,
            label: 'Caregiver Dashboard',
            sub: 'Local telemetry monitor',
            color: Colors.purpleAccent,
            onTap: _openCaregiver,
          ),
          const SizedBox(height: 12),
          _buildModuleButton(
            icon: Icons.settings_rounded,
            label: 'Settings',
            sub: 'Engine & audio calibration',
            color: Colors.white54,
            onTap: _openSettings,
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }

  Widget _sectionLabel(String text) {
    return Text(
      text,
      style: GoogleFonts.inter(
        color: Colors.white24,
        fontSize: 11,
        fontWeight: FontWeight.w800,
        letterSpacing: 2.0,
      ),
    );
  }

  Widget _buildStatsGrid() {
    final frames = _stats['frames']?.toString() ?? '0';
    final alerts = _stats['alerts']?.toString() ?? '0';
    final uptime = _stats['uptime']?.toString() ?? '00:00:00';
    final fps = _stats['fps']?.toString() ?? '0';

    return GridView.count(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      crossAxisCount: 2,
      crossAxisSpacing: 10,
      mainAxisSpacing: 10,
      childAspectRatio: 1.8,
      children: [
        _statCard('Frames', frames, Icons.photo_camera_front_outlined,
            Colors.cyanAccent),
        _statCard('Alerts', alerts, Icons.notifications_active_outlined,
            Colors.redAccent),
        _statCard('Uptime', uptime, Icons.timer_outlined, Colors.greenAccent),
        _statCard('Sim FPS', fps, Icons. speed_outlined, Colors.amberAccent),
      ],
    );
  }

  Widget _statCard(String label, String value, IconData icon, Color color) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.03),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: color.withValues(alpha: 0.12), width: 0.8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Icon(icon, size: 16, color: color.withValues(alpha: 0.5)),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(value,
                  style: GoogleFonts.orbitron(
                      color: Colors.white,
                      fontWeight: FontWeight.w700,
                      fontSize: 18,
                      letterSpacing: 1.0)),
              const SizedBox(height: 2),
              Text(label,
                  style: GoogleFonts.inter(
                      color: Colors.white24,
                      fontSize: 8,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 1.5)),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildRadarWidget() {
    return AnimatedBuilder(
      animation: _pulseCtrl,
      builder: (context, _) => Container(
        height: 190,
        width: double.infinity,
        decoration: BoxDecoration(
          color: Colors.black.withValues(alpha: 0.3),
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: kNeonCyan.withValues(alpha: 0.1), width: 1.0),
        ),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(20),
          child: CustomPaint(
            painter: RadarPainter(_spatialMap, _pulseAnim.value),
          ),
        ),
      ),
    );
  }

  Widget _buildModuleButton({
    required IconData icon,
    required String label,
    required String sub,
    required Color color,
    VoidCallback? onTap,
  }) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap ?? () {},
        borderRadius: BorderRadius.circular(18),
        splashColor: color.withValues(alpha: 0.15),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: 0.025),
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
          ),
          child: Row(
            children: [
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(icon, size: 20, color: color),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(label,
                        style: GoogleFonts.inter(
                            color: Colors.white,
                            fontSize: 14,
                            fontWeight: FontWeight.w700)),
                    const SizedBox(height: 2),
                    Text(sub,
                        style: GoogleFonts.inter(
                            color: Colors.white38, fontSize: 11)),
                  ],
                ),
              ),
              if (onTap != null)
                const Icon(Icons.chevron_right_rounded,
                    color: Colors.white24, size: 20),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildToggleSyncButton() {
    final bool syncing = _controller.caregiverService.isBroadcasting;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: () async {
          await _controller.toggleCaregiverSync();
          setState(() {});
        },
        borderRadius: BorderRadius.circular(18),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 300),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          decoration: BoxDecoration(
            color: syncing
                ? Colors.greenAccent.withValues(alpha: 0.08)
                : Colors.white.withValues(alpha: 0.025),
            borderRadius: BorderRadius.circular(18),
            border: Border.all(
              color: syncing
                  ? Colors.greenAccent.withValues(alpha: 0.4)
                  : Colors.white.withValues(alpha: 0.06),
              width: 1.5,
            ),
          ),
          child: Row(children: [
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: syncing
                    ? Colors.greenAccent.withValues(alpha: 0.15)
                    : Colors.white.withValues(alpha: 0.05),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Icon(
                syncing
                    ? Icons.cell_tower_rounded
                    : Icons.portable_wifi_off_rounded,
                size: 20,
                color: syncing ? Colors.greenAccent : Colors.white54,
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    syncing ? 'Local Network Active' : 'Start Local Link',
                    style: GoogleFonts.inter(
                        color: Colors.white,
                        fontWeight: FontWeight.w700,
                        fontSize: 14),
                  ),
                  Text(
                    syncing
                        ? 'AIR-GAPPED READY • NO INTERNET'
                        : 'OFFLINE-FIRST ARCHITECTURE',
                    style: GoogleFonts.inter(
                      color: syncing
                          ? Colors.greenAccent.withValues(alpha: 0.9)
                          : Colors.white38,
                      fontSize: 9,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 0.5,
                    ),
                  ),
                ],
              ),
            ),
            if (syncing)
              const Icon(Icons.check_circle_rounded,
                  color: Colors.greenAccent, size: 18),
          ]),
        ),
      ),
    );
  }

  Widget _buildMobileBottomPanel() {
    return Positioned(
      bottom: 0,
      left: 0,
      right: 0,
      child: ClipRRect(
        borderRadius: const BorderRadius.vertical(top: Radius.circular(32)),
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 20, sigmaY: 20),
          child: Container(
            padding: const EdgeInsets.fromLTRB(20, 20, 20, 40),
            decoration: BoxDecoration(
              color: const Color(0xFF0B0B10).withValues(alpha: 0.85),
              border: const Border(
                  top: BorderSide(color: Color(0xFF1A1A2E), width: 1)),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 40,
                  height: 4,
                  margin: const EdgeInsets.only(bottom: 16),
                  decoration: BoxDecoration(
                      color: Colors.white12,
                      borderRadius: BorderRadius.circular(2)),
                ),
                Row(children: [
                  Expanded(
                    child: _buildModuleButton(
                      icon: Icons.surround_sound_rounded,
                      label: '8D Audio',
                      sub: 'Navigation',
                      color: Colors.blueAccent,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: _buildModuleButton(
                      icon: Icons.vibration_rounded,
                      label: 'AR Haptics',
                      sub: 'Alerts',
                      color: Colors.orangeAccent,
                    ),
                  ),
                ]),
                const SizedBox(height: 12),
                Row(children: [
                  Expanded(child: _buildToggleSyncButton()),
                  const SizedBox(width: 12),
                  Expanded(
                    child: _buildModuleButton(
                      icon: Icons.admin_panel_settings_rounded,
                      label: 'Caregiver',
                      sub: 'Local sync',
                      color: Colors.purpleAccent,
                      onTap: _openCaregiver,
                    ),
                  ),
                ]),
              ],
            ),
          ),
        ),
      ),
    );
  }

  void _openCaregiver() {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => CaregiverView(service: _controller.caregiverService),
      ),
    );
  }

  void _openSettings() {
    Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => SettingsView(controller: _controller)),
    );
  }

  IconData _iconFor(int id) {
    switch (id) {
      case 0:
        return Icons.person_outline_rounded;
      case 1:
        return Icons.directions_car_outlined;
      case 2:
        return Icons.pedal_bike_rounded;
      case 3:
        return Icons.warning_amber_rounded;
      default:
        return Icons.help_outline_rounded;
    }
  }
}

class ScanningOverlayPainter extends CustomPainter {
  final double progress;
  ScanningOverlayPainter(this.progress);

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..shader = LinearGradient(
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
        colors: [
          Colors.transparent,
          kNeonCyan.withValues(alpha: 0.05),
          kNeonCyan.withValues(alpha: 0.35),
          kNeonCyan.withValues(alpha: 0.05),
          Colors.transparent,
        ],
        stops: const [0.0, 0.48, 0.5, 0.52, 1.0],
      ).createShader(
          Rect.fromLTWH(0, (progress * size.height) - 40, size.width, 80));

    canvas.drawRect(
        Rect.fromLTWH(0, (progress * size.height) - 40, size.width, 80), paint);

    final linePaint = Paint()
      ..color = kNeonCyan.withValues(alpha: 0.8)
      ..strokeWidth = 0.8;
    canvas.drawLine(
      Offset(0, progress * size.height),
      Offset(size.width, progress * size.height),
      linePaint,
    );

    final cornerPaint = Paint()
      ..color = kNeonCyan.withValues(alpha: 0.2)
      ..strokeWidth = 1.2
      ..style = PaintingStyle.stroke;

    const double cs = 24.0;
    const double pad = 30.0;

    canvas.drawPath(
        Path()
          ..moveTo(pad, pad + cs)
          ..lineTo(pad, pad)
          ..lineTo(pad + cs, pad),
        cornerPaint);
    canvas.drawPath(
        Path()
          ..moveTo(size.width - pad - cs, pad)
          ..lineTo(size.width - pad, pad)
          ..lineTo(size.width - pad, pad + cs),
        cornerPaint);
    canvas.drawPath(
        Path()
          ..moveTo(pad, size.height - pad - cs)
          ..lineTo(pad, size.height - pad)
          ..lineTo(pad + cs, size.height - pad),
        cornerPaint);
    canvas.drawPath(
        Path()
          ..moveTo(size.width - pad - cs, size.height - pad)
          ..lineTo(size.width - pad, size.height - pad)
          ..lineTo(size.width - pad, size.height - pad - cs),
        cornerPaint);
  }

  @override
  bool shouldRepaint(ScanningOverlayPainter oldDelegate) =>
      oldDelegate.progress != progress;
}

class TacticalGridPainter extends CustomPainter {
  final double pulse;
  TacticalGridPainter(this.pulse);

  @override
  void paint(Canvas canvas, Size size) {
    final gridPaint = Paint()
      ..color = kNeonCyan.withValues(alpha: 0.03)
      ..strokeWidth = 0.5;

    const double step = 45.0;
    for (double x = 0; x < size.width; x += step) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), gridPaint);
    }
    for (double y = 0; y < size.height; y += step) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), gridPaint);
    }

    final center = Offset(size.width / 2, size.height * 0.4);
    final pulsePaint = Paint()
      ..shader = RadialGradient(
        colors: [
          kNeonCyan.withValues(alpha: 0.12 * (1.3 - pulse)),
          Colors.transparent,
        ],
      ).createShader(
          Rect.fromCircle(center: center, radius: size.width * 0.8 * pulse));

    canvas.drawRect(Rect.fromLTWH(0, 0, size.width, size.height), pulsePaint);
  }

  @override
  bool shouldRepaint(TacticalGridPainter oldDelegate) =>
      oldDelegate.pulse != pulse;
}

class RadarPainter extends CustomPainter {
  final List<SpatialPointData> points;
  final double pulse;

  RadarPainter(this.points, this.pulse);

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height * 0.9);
    final double maxR = size.height * 0.8;

    final gridPaint = Paint()
      ..color = kNeonCyan.withValues(alpha: 0.08)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 0.5;
    for (int i = 1; i <= 3; i++) {
      canvas.drawCircle(center, (maxR / 3.0) * i, gridPaint);
    }

    final double pr = maxR * (pulse - 0.7) / 0.6;
    final pulsePaint = Paint()
      ..color = kNeonCyan.withValues(alpha: 0.05)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2;
    canvas.drawCircle(center, pr.clamp(0, maxR), pulsePaint);

    for (final pt in points) {
      final double alpha = pt.alpha.clamp(0.0, 1.0);
      if (alpha <= 0.05) continue;

      final double nx = ((pt.x - 320) / 320.0).clamp(-1.0, 1.0);
      final double radarX = center.dx + nx * size.width * 0.45;
      final double radarY = center.dy - (pt.z / 10.0).clamp(0.0, 1.0) * maxR;

      final bool isClose = pt.z < 3.0;
      final Color ptColor = isClose ? kEmergencyRed : kNeonCyan;

      canvas.drawCircle(
        Offset(radarX, radarY),
        1.8,
        Paint()..color = ptColor.withValues(alpha: alpha),
      );
    }
  }

  @override
  bool shouldRepaint(RadarPainter old) => true;
}
