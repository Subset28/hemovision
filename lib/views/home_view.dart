import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'dart:ui';
import 'dart:math' as math;
import 'package:google_fonts/google_fonts.dart';
import '../controllers/main_controller.dart';
import 'caregiver_view.dart';
import 'settings_view.dart';

// ─────────────────────────────────────────────────────────────────
//  HOME VIEW  (Primary UI — MVC View layer)
//  Displays the live environment scan, AR bounding box overlays,
//  audio-alert HUD, SLAM radar, and system controls.
// ─────────────────────────────────────────────────────────────────
class HomeView extends StatefulWidget {
  const HomeView({super.key});

  @override
  State<HomeView> createState() => _HomeViewState();
}

class _HomeViewState extends State<HomeView>
    with TickerProviderStateMixin {
  late MainController _controller;

  List<Map<String, dynamic>> _detectedObjects = [];
  List<Map<String, dynamic>> _spatialMap = [];
  Map<String, dynamic>? _currentAlert;
  Map<String, dynamic> _stats = {};
  bool _isExpanded = false;   // sidebar toggle on desktop

  // Animations
  late AnimationController _pulseCtrl;
  late Animation<double> _pulseAnim;
  late AnimationController _alertCtrl;
  late Animation<double> _alertAnim;
  late AnimationController _glowCtrl;
  late Animation<double> _glowAnim;

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
    _controller.statsStream.listen((s) {
      if (mounted) setState(() => _stats = s);
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
  }

  @override
  void dispose() {
    _controller.dispose();
    _pulseCtrl.dispose();
    _alertCtrl.dispose();
    _glowCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, constraints) {
      final isDesktop = constraints.maxWidth > 800;
      return Scaffold(
        backgroundColor: const Color(0xFF07070A),
        body: isDesktop
            ? _buildDesktopLayout()
            : _buildMobileLayout(),
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
              ..._buildObjectOverlays(canvasWidth: 700, canvasHeight: 600),
              if (_currentAlert != null) _buildAlertHUD(),
              _buildTopBar(isDesktop: true),
              Positioned(
                bottom: 24, left: 24,
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
              color: Color(0xFF0B0B10),
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
        ..._buildObjectOverlays(),
        if (_currentAlert != null) _buildAlertHUD(),
        _buildTopBar(isDesktop: false),
        _buildMobileBottomPanel(),
        Positioned(
          bottom: 180, right: 20,
          child: _buildModeIndicator(),
        ),
      ],
    );
  }

  // ── CAMERA FEED ──────────────────────────────────────────────
  Widget _buildCameraFeed() {
    return AnimatedBuilder(
      animation: _glowCtrl,
      builder: (context, _) => Container(
        decoration: BoxDecoration(
          color: const Color(0xFF050508),
          // Animated ambient glow at top
          gradient: RadialGradient(
            center: const Alignment(0, -0.8),
            radius: 1.2,
            colors: [
              const Color(0xFF00E5FF).withOpacity(_glowAnim.value),
              Colors.transparent,
            ],
          ),
        ),
        child: CustomPaint(
          painter: ScanGridPainter(),
          child: Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.remove_red_eye_outlined,
                    size: 90,
                    color: const Color(0xFF00E5FF).withOpacity(0.06)),
                const SizedBox(height: 20),
                _buildScanningStatus(),
              ],
            ),
          ),
        ),
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
            color: Colors.black.withOpacity(0.4),
            borderRadius: BorderRadius.circular(30),
            border: Border.all(color: Colors.white.withOpacity(0.08)),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              SizedBox(
                width: 12,
                height: 12,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: const Color(0xFF00E5FF),
                  value: null,
                ),
              ),
              const SizedBox(width: 14),
              Text(
                'ENVIRONMENT SCAN ACTIVE',
                style: GoogleFonts.inter(
                  color: Colors.white54,
                  fontSize: 13,
                  letterSpacing: 2.0,
                  fontWeight: FontWeight.w600,
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
              color: const Color(0xFF00E5FF),
            ),
            const Spacer(),
          ],
          _buildGlassChip(
            label: 'Module A • 8D Audio',
            color: Colors.blueAccent,
          ),
          const SizedBox(width: 10),
          _buildGlassChip(
            label: 'Module B • AR Haptics',
            color: Colors.orangeAccent,
          ),
          if (isDesktop) const Spacer(),
        ],
      ),
    );
  }

  Widget _buildGlassChip({
    required String label,
    Color color = Colors.white,
    IconData? icon,
  }) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(30),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 10, sigmaY: 10),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
          decoration: BoxDecoration(
            color: Colors.black.withOpacity(0.45),
            borderRadius: BorderRadius.circular(30),
            border: Border.all(color: color.withOpacity(0.3), width: 1.2),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (icon != null) ...[
                Icon(icon, size: 15, color: color),
                const SizedBox(width: 8),
              ] else ...[
                Container(
                  width: 8, height: 8,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: color,
                    boxShadow: [BoxShadow(color: color, blurRadius: 6)],
                  ),
                ),
                const SizedBox(width: 10),
              ],
              Text(label,
                  style: GoogleFonts.inter(
                    color: Colors.white,
                    fontWeight: FontWeight.w600,
                    fontSize: 12,
                    letterSpacing: 0.3,
                  )),
            ],
          ),
        ),
      ),
    );
  }

  // ── BOUNDING BOX OVERLAYS ─────────────────────────────────────
  List<Widget> _buildObjectOverlays({
    double canvasWidth = 390,
    double canvasHeight = 700,
  }) {
    return _detectedObjects.map((obj) {
      final double x = (obj['x'] as double);
      final double y = (obj['y'] as double);
      final double w = (obj['width'] as double);
      final double h = (obj['height'] as double);
      final double dist = (obj['distance'] as double);
      final double threat = (obj['threatLevel'] as double);
      final int classId = (obj['classId'] as int);

      final bool isCritical = threat > 75;
      final Color boxColor =
          isCritical ? Colors.redAccent : Colors.greenAccent;
      final String label = _labelFor(classId);
      final IconData icon = _iconFor(classId);

      return Positioned(
        left: x - w / 2,
        top: y - h / 2,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 80),
          width: w,
          height: h,
          decoration: BoxDecoration(
            border: Border.all(color: boxColor, width: isCritical ? 2.5 : 1.5),
            borderRadius: BorderRadius.circular(10),
            boxShadow: [
              BoxShadow(
                  color: boxColor.withOpacity(isCritical ? 0.3 : 0.15),
                  blurRadius: 14,
                  spreadRadius: 2),
            ],
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Label chip
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: boxColor.withOpacity(0.92),
                  borderRadius: const BorderRadius.only(
                    topLeft: Radius.circular(8),
                    bottomRight: Radius.circular(8),
                  ),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(icon, size: 12, color: Colors.black87),
                    const SizedBox(width: 5),
                    Text(
                      '$label  ${dist.toStringAsFixed(1)}m',
                      style: GoogleFonts.inter(
                        color: Colors.black87,
                        fontWeight: FontWeight.w900,
                        fontSize: 11,
                        letterSpacing: 0.4,
                      ),
                    ),
                  ],
                ),
              ),
              // Threat level indicator at bottom
              const Spacer(),
              if (isCritical)
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(4),
                    child: LinearProgressIndicator(
                      value: threat / 100.0,
                      backgroundColor: Colors.black45,
                      valueColor: AlwaysStoppedAnimation<Color>(boxColor),
                      minHeight: 3,
                    ),
                  ),
                ),
            ],
          ),
        ),
      );
    }).toList();
  }

  // ── AUDIO ALERT HUD ───────────────────────────────────────────
  Widget _buildAlertHUD() {
    return Positioned.fill(
      child: IgnorePointer(
        child: AnimatedBuilder(
          animation: _pulseAnim,
          builder: (context, _) {
            final opacity = 0.4 + 0.6 * ((_pulseAnim.value - 0.7) / 0.6).clamp(0.0, 1.0);
            return Stack(
              fit: StackFit.expand,
              children: [
                // Pulsing red border
                Container(
                  decoration: BoxDecoration(
                    border: Border.all(
                      color: Colors.redAccent.withOpacity(opacity * 0.7),
                      width: 20 * (_pulseAnim.value - 0.7),
                    ),
                  ),
                ),
                // Central HUD card
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
    final type = _currentAlert!['type'] as String;
    final direction = _currentAlert!['direction'] as String;

    return ClipRRect(
      borderRadius: BorderRadius.circular(24),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 20, sigmaY: 20),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 32, horizontal: 48),
          decoration: BoxDecoration(
            color: Colors.redAccent.withOpacity(0.75),
            borderRadius: BorderRadius.circular(24),
            border: Border.all(color: Colors.white.withOpacity(0.3)),
            boxShadow: [
              BoxShadow(
                  color: Colors.redAccent.withOpacity(0.5), blurRadius: 60),
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
                  color: Colors.white.withOpacity(0.15),
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
    );
  }

  // ── MODE INDICATOR (MOCK / LIVE) ─────────────────────────────
  Widget _buildModeIndicator() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: Colors.black.withOpacity(0.5),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: Colors.amber.withOpacity(0.4)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 7, height: 7,
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

  // ── SIDEBAR (DESKTOP) ─────────────────────────────────────────
  Widget _buildSidebar() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: 36),
          // App Header
          Row(children: [
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: const Color(0xFF00E5FF).withOpacity(0.1),
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
          _sectionLabel('LIVE STATS'),
          const SizedBox(height: 12),
          _buildStatsGrid(),

          const SizedBox(height: 28),
          _sectionLabel('SLAM TOPOGRAPHY RADAR'),
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

  // ── STATS GRID ────────────────────────────────────────────────
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
        _statCard('Frames', frames, Icons.photo_camera_front_outlined, Colors.cyanAccent),
        _statCard('Alerts', alerts, Icons.notifications_active_outlined, Colors.redAccent),
        _statCard('Uptime', uptime, Icons.timer_outlined, Colors.greenAccent),
        _statCard('Sim FPS', fps, Icons.speed_outlined, Colors.amberAccent),
      ],
    );
  }

  Widget _statCard(String label, String value, IconData icon, Color color) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: color.withOpacity(0.05),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: color.withOpacity(0.15)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Icon(icon, size: 18, color: color.withOpacity(0.8)),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(value,
                  style: GoogleFonts.inter(
                      color: Colors.white,
                      fontWeight: FontWeight.w900,
                      fontSize: 18,
                      letterSpacing: -0.5)),
              Text(label,
                  style: GoogleFonts.inter(
                      color: Colors.white38,
                      fontSize: 10,
                      letterSpacing: 1.0)),
            ],
          ),
        ],
      ),
    );
  }

  // ── SLAM RADAR ────────────────────────────────────────────────
  Widget _buildRadarWidget() {
    return AnimatedBuilder(
      animation: _pulseCtrl,
      builder: (context, _) => Container(
        height: 190,
        width: double.infinity,
        decoration: BoxDecoration(
          color: Colors.black.withOpacity(0.4),
          borderRadius: BorderRadius.circular(20),
          border: Border.all(
              color: Colors.greenAccent.withOpacity(0.15), width: 1.5),
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

  // ── MODULE BUTTONS ────────────────────────────────────────────
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
        splashColor: color.withOpacity(0.15),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          decoration: BoxDecoration(
            color: Colors.white.withOpacity(0.025),
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: Colors.white.withOpacity(0.06)),
          ),
          child: Row(
            children: [
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: color.withOpacity(0.12),
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
                Icon(Icons.chevron_right_rounded,
                    color: Colors.white24, size: 20),
            ],
          ),
        ),
      ),
    );
  }

  // ── CAREGIVER SYNC TOGGLE ─────────────────────────────────────
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
                ? Colors.greenAccent.withOpacity(0.08)
                : Colors.white.withOpacity(0.025),
            borderRadius: BorderRadius.circular(18),
            border: Border.all(
              color: syncing
                  ? Colors.greenAccent.withOpacity(0.4)
                  : Colors.white.withOpacity(0.06),
              width: 1.5,
            ),
          ),
          child: Row(children: [
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: syncing
                    ? Colors.greenAccent.withOpacity(0.15)
                    : Colors.white.withOpacity(0.05),
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
                    syncing ? 'Sync Active' : 'Start Sync',
                    style: GoogleFonts.inter(
                        color: Colors.white,
                        fontWeight: FontWeight.w700,
                        fontSize: 14),
                  ),
                  Text(
                    syncing ? 'Local hotspot streaming' : 'Offline mode',
                    style: GoogleFonts.inter(
                      color:
                          syncing ? Colors.greenAccent.withOpacity(0.8) : Colors.white38,
                      fontSize: 11,
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

  // ── MOBILE BOTTOM PANEL ───────────────────────────────────────
  Widget _buildMobileBottomPanel() {
    return Positioned(
      bottom: 0, left: 0, right: 0,
      child: ClipRRect(
        borderRadius:
            const BorderRadius.vertical(top: Radius.circular(32)),
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 20, sigmaY: 20),
          child: Container(
            padding: const EdgeInsets.fromLTRB(20, 20, 20, 40),
            decoration: BoxDecoration(
              color: const Color(0xFF0B0B10).withOpacity(0.85),
              border: const Border(
                  top: BorderSide(color: Color(0xFF1A1A2E), width: 1)),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                // Drag handle
                Container(
                  width: 40, height: 4,
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

  // ── NAVIGATION ────────────────────────────────────────────────
  void _openCaregiver() {
    Navigator.push(
        context,
        MaterialPageRoute(
            builder: (_) => CaregiverView(
                service: _controller.caregiverService)));
  }

  void _openSettings() {
    Navigator.push(context,
        MaterialPageRoute(builder: (_) => const SettingsView()));
  }

  // ── HELPERS ───────────────────────────────────────────────────
  String _labelFor(int id) {
    switch (id) {
      case 0: return 'Person';
      case 1: return 'Car';
      case 2: return 'Chair';
      default: return 'Object';
    }
  }

  IconData _iconFor(int id) {
    switch (id) {
      case 0: return Icons.person_rounded;
      case 1: return Icons.directions_car_rounded;
      case 2: return Icons.chair_rounded;
      default: return Icons.category_rounded;
    }
  }
}

// ─────────────────────────────────────────────────────────────────
//  SCAN GRID PAINTER — draws the technical scanner grid background
// ─────────────────────────────────────────────────────────────────
class ScanGridPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = const Color(0xFF00E5FF).withOpacity(0.025)
      ..strokeWidth = 1.0;

    const step = 40.0;
    for (double x = 0; x < size.width; x += step) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), paint);
    }
    for (double y = 0; y < size.height; y += step) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), paint);
    }

    // Corner markers
    final cornerPaint = Paint()
      ..color = const Color(0xFF00E5FF).withOpacity(0.2)
      ..strokeWidth = 2.0
      ..style = PaintingStyle.stroke;

    const cornerSize = 20.0;
    final corners = [
      Offset(20, 100),
      Offset(size.width - 20, 100),
      Offset(20, size.height - 20),
      Offset(size.width - 20, size.height - 20),
    ];
    for (final c in corners) {
      canvas.drawRect(
          Rect.fromCenter(center: c, width: cornerSize, height: cornerSize),
          cornerPaint);
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

// ─────────────────────────────────────────────────────────────────
//  RADAR PAINTER — SLAM-lite topography ring visualizer
// ─────────────────────────────────────────────────────────────────
class RadarPainter extends CustomPainter {
  final List<Map<String, dynamic>> spatialMap;
  final double pulseValue;

  RadarPainter(this.spatialMap, this.pulseValue);

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height);
    final double maxR = size.height;

    // Grid rings
    final gridPaint = Paint()
      ..color = Colors.greenAccent.withOpacity(0.1)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.0;
    for (int i = 1; i <= 4; i++) {
      canvas.drawCircle(center, (maxR / 4.0) * i, gridPaint);
    }

    // Center cross
    final crossPaint = Paint()
      ..color = Colors.greenAccent.withOpacity(0.12)
      ..strokeWidth = 1;
    canvas.drawLine(Offset(center.dx, 0), Offset(center.dx, size.height), crossPaint);
    canvas.drawLine(Offset(0, center.dy), Offset(size.width, center.dy), crossPaint);

    // Sweeping pulse ring
    final double pr = maxR * (pulseValue - 0.7) / 0.6 * 1.0;
    final pulsePaint = Paint()
      ..color = Colors.greenAccent.withOpacity(0.07)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3;
    canvas.drawCircle(center, pr.clamp(0, maxR), pulsePaint);

    // Spatial map points
    for (final pt in spatialMap) {
      final double alpha = ((pt['alpha'] as double?) ?? 1.0).clamp(0.0, 1.0);
      if (alpha <= 0.02) continue;

      final double px = (pt['x'] as double?) ?? 320.0;
      final double dist = (pt['z'] as double?) ?? 5.0;
      final double nx = ((px - 320) / 320.0).clamp(-1.0, 1.0);
      final double radarX = center.dx + nx * size.width * 0.5;
      final double radarY = center.dy - (dist / 10.0).clamp(0.0, 1.0) * maxR;

      final bool isClose = dist < 3.0;
      final Color ptColor = isClose ? Colors.redAccent : Colors.greenAccent;

      canvas.drawCircle(
        Offset(radarX, radarY),
        isClose ? 5.0 : 3.5,
        Paint()
          ..color = ptColor.withOpacity(alpha)
          ..style = PaintingStyle.fill,
      );

      // Glow halo
      canvas.drawCircle(
        Offset(radarX, radarY),
        isClose ? 10.0 : 7.0,
        Paint()
          ..color = ptColor.withOpacity(alpha * 0.2)
          ..style = PaintingStyle.fill,
      );
    }
  }

  @override
  bool shouldRepaint(covariant RadarPainter old) => true;
}
