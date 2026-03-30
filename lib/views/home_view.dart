import 'package:flutter/material.dart';
import 'dart:ui';
import '../controllers/main_controller.dart';
import 'caregiver_view.dart';

class HomeView extends StatefulWidget {
  const HomeView({super.key});

  @override
  State<HomeView> createState() => _HomeViewState();
}

class _HomeViewState extends State<HomeView> with SingleTickerProviderStateMixin {
  late MainController _controller;
  List<Map<String, dynamic>> _detectedObjects = [];
  List<Map<String, dynamic>> _spatialMap = [];
  Map<String, dynamic>? _currentAlert;
  
  late AnimationController _pulseController;
  late Animation<double> _pulseAnimation;

  @override
  void initState() {
    super.initState();
    _controller = MainController();
    
    _controller.detectedObjectsStream.listen((objects) {
      if (mounted) setState(() => _detectedObjects = objects);
    });

    _controller.spatialMapStream.listen((map) {
      if (mounted) setState(() => _spatialMap = map);
    });

    _controller.audioAlertStream.listen((alert) {
      if (mounted) {
        setState(() => _currentAlert = alert);
        Future.delayed(const Duration(seconds: 3), () {
          if (mounted && _currentAlert == alert) {
            setState(() => _currentAlert = null);
          }
        });
      }
    });

    _controller.startProcessing();

    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1000),
    )..repeat(reverse: true);
    
    _pulseAnimation = Tween<double>(begin: 0.8, end: 1.2).animate(
      CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut),
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    _pulseController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // Determine layout based on platform/screen width
    return LayoutBuilder(
      builder: (context, constraints) {
        bool isDesktop = constraints.maxWidth > 800; // Standard threshold for Windows/Tablets
        
        return Scaffold(
          backgroundColor: const Color(0xFF07070A),
          body: isDesktop 
              ? _buildDesktopLayout(constraints) 
              : _buildMobileLayout(constraints),
        );
      },
    );
  }

  // --- RESPONSIVE LAYOUTS ---

  Widget _buildMobileLayout(BoxConstraints constraints) {
    return Stack(
      children: [
        _buildCameraFeed(isDesktop: false),
        ..._buildObjectOverlays(),
        if (_currentAlert != null) _buildAudioAlertHUD(),
        _buildTopStatusBar(),
        Positioned(
          bottom: 24,
          left: 16,
          right: 16,
          child: _buildGlassControlPanel(isDesktop: false),
        ),
      ],
    );
  }

  Widget _buildDesktopLayout(BoxConstraints constraints) {
    return Row(
      children: [
        // Left Panel (Camera Feed & HUD)
        Expanded(
          flex: 7, 
          child: ClipRRect(
            borderRadius: const BorderRadius.only(topRight: Radius.circular(30), bottomRight: Radius.circular(30)),
            child: Stack(
              children: [
                _buildCameraFeed(isDesktop: true),
                ..._buildObjectOverlays(),
                if (_currentAlert != null) _buildAudioAlertHUD(),
                _buildTopStatusBar(),
              ],
            ),
          )
        ),
        // Right Panel (Control Dashboard)
        Expanded(
          flex: 3, 
          child: Container(
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
               gradient: LinearGradient(
                  colors: [const Color(0xFF0F0F15), const Color(0xFF07070A)],
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
               )
            ),
            child: _buildDesktopSidebar(),
          ),
        ),
      ],
    );
  }

  // --- CORE UI COMPONENTS ---

  Widget _buildCameraFeed({required bool isDesktop}) {
    return Container(
      decoration: const BoxDecoration(
        color: Colors.black,
        image: DecorationImage(
           // A subtle geometric grid to emulate a technical scanner overlay
           image: NetworkImage('https://www.transparenttextures.com/patterns/dark-matter.png'), 
           repeat: ImageRepeat.repeat,
           opacity: 0.3,
        )
      ),
      child: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
             Icon(Icons.camera_alt_rounded, size: isDesktop ? 100 : 70, color: Colors.blueAccent.withOpacity(0.05)),
             const SizedBox(height: 24),
             Container(
               padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 10),
               decoration: BoxDecoration(
                  color: Colors.black45,
                  borderRadius: BorderRadius.circular(30),
                  border: Border.all(color: Colors.white10),
               ),
               child: const Row(
                 mainAxisSize: MainAxisSize.min,
                 children: [
                   SizedBox(
                     width: 14, height: 14,
                     child: CircularProgressIndicator(strokeWidth: 2, color: Colors.blueAccent),
                   ),
                   SizedBox(width: 16),
                   Text(
                    "ENVIRONMENT SCAN ACTIVE",
                    style: TextStyle(color: Colors.white54, fontSize: 16, letterSpacing: 3.0, fontWeight: FontWeight.w600),
                  ),
                 ],
               ),
             ),
          ],
        ),
      ),
    );
  }

  Widget _buildTopStatusBar() {
    return Positioned(
      top: 48,
      left: 20,
      right: 20,
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          _buildGlassStatusChip("Module A: 8D Audio", Colors.blueAccent),
          _buildGlassStatusChip("Module B: AR Haptics", Colors.orangeAccent),
        ],
      ),
    );
  }

  Widget _buildGlassStatusChip(String label, Color color) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(30),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 10, sigmaY: 10),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          decoration: BoxDecoration(
            color: Colors.black.withOpacity(0.4),
            borderRadius: BorderRadius.circular(30),
            border: Border.all(color: color.withOpacity(0.3), width: 1.5),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 10,
                height: 10,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: color,
                  boxShadow: [BoxShadow(color: color, blurRadius: 8, spreadRadius: 1)]
                ),
              ),
              const SizedBox(width: 12),
              Text(label, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 13, letterSpacing: 0.5)),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildGlassControlPanel({required bool isDesktop}) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(32),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 20, sigmaY: 20),
        child: Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: const Color(0xFF15151A).withOpacity(0.7),
            borderRadius: BorderRadius.circular(32),
            border: Border.all(color: Colors.white.withOpacity(0.1), width: 1),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withOpacity(0.5),
                blurRadius: 30,
                spreadRadius: 5,
              )
            ]
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                children: [
                  Expanded(child: _buildGlassButton(Icons.volume_up_rounded, "Spatial Audio", "Navigation", Colors.blueAccent)),
                  const SizedBox(width: 12),
                  Expanded(child: _buildGlassButton(Icons.visibility_rounded, "AR Haptics", "Alerts", Colors.orangeAccent)),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(child: _buildToggleBroadcastingButton()),
                  const SizedBox(width: 12),
                  Expanded(
                    child: _buildGlassButton(
                      Icons.admin_panel_settings_rounded, 
                      "Caregiver", 
                      "Local Sync",
                      Colors.purpleAccent,
                      onTap: () {
                         Navigator.push(context, MaterialPageRoute(builder: (context) => CaregiverView(service: _controller.caregiverService)));
                      }
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildDesktopSidebar() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
         const Text("OmniSight Engine", style: TextStyle(color: Colors.white, fontSize: 28, fontWeight: FontWeight.bold, letterSpacing: -1)),
         const SizedBox(height: 8),
         Text("System Telemetry Menu", style: TextStyle(color: Colors.white.withOpacity(0.5), fontSize: 14, letterSpacing: 1.5)),
         const SizedBox(height: 32),
         
         const Text("SLAM TOPOGRAPHY RADAR", style: TextStyle(color: Colors.white30, fontSize: 12, fontWeight: FontWeight.bold, letterSpacing: 1.5)),
         const SizedBox(height: 16),
         _buildRadarWidget(),
         const SizedBox(height: 32),
         
         const Text("ACCESSIBILITY MODULES", style: TextStyle(color: Colors.white30, fontSize: 12, fontWeight: FontWeight.bold, letterSpacing: 1.5)),
         const SizedBox(height: 16),
         _buildGlassButton(Icons.volume_up_rounded, "Spatial Audio", "8D Distance Calibration", Colors.blueAccent),
         const SizedBox(height: 16),
         _buildGlassButton(Icons.visibility_rounded, "AR Haptics", "Vibration Frequencies", Colors.orangeAccent),
         
         const Spacer(),
         const Text("CAREGIVER NETWORK", style: TextStyle(color: Colors.white30, fontSize: 12, fontWeight: FontWeight.bold, letterSpacing: 1.5)),
         const SizedBox(height: 16),
         _buildToggleBroadcastingButton(),
         const SizedBox(height: 16),
         _buildGlassButton(
            Icons.admin_panel_settings_rounded, 
            "Caregiver Dashboard", 
            "View connected telemetry",
            Colors.purpleAccent,
            onTap: () {
               Navigator.push(context, MaterialPageRoute(builder: (context) => CaregiverView(service: _controller.caregiverService)));
            }
          ),
      ],
    );
  }

  Widget _buildRadarWidget() {
    return Container(
      height: 200,
      width: double.infinity,
      decoration: BoxDecoration(
        color: Colors.black.withOpacity(0.3),
        borderRadius: BorderRadius.circular(24),
        border: Border.all(color: Colors.greenAccent.withOpacity(0.2), width: 1)
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(24),
        child: CustomPaint(
          painter: RadarPainter(_spatialMap, _pulseAnimation.value),
        ),
      ),
    );
  }

  Widget _buildGlassButton(IconData icon, String label, String subtitle, Color accentColor, {VoidCallback? onTap}) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap ?? () {}, 
        borderRadius: BorderRadius.circular(20),
        splashColor: accentColor.withOpacity(0.2),
        highlightColor: accentColor.withOpacity(0.1),
        child: Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Colors.white.withOpacity(0.03),
            borderRadius: BorderRadius.circular(20),
            border: Border.all(color: Colors.white.withOpacity(0.08), width: 1),
          ),
          child: Row(
            children: [
               Container(
                 padding: const EdgeInsets.all(12),
                 decoration: BoxDecoration(
                    color: accentColor.withOpacity(0.15),
                    borderRadius: BorderRadius.circular(14),
                 ),
                 child: Icon(icon, size: 24, color: accentColor),
               ),
               const SizedBox(width: 16),
               Expanded(
                 child: Column(
                   crossAxisAlignment: CrossAxisAlignment.start,
                   children: [
                     Text(label, style: const TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.bold, letterSpacing: 0.3)),
                     const SizedBox(height: 2),
                     Text(subtitle, style: TextStyle(color: Colors.white.withOpacity(0.5), fontSize: 12, fontWeight: FontWeight.w500)),
                   ],
                 ),
               )
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildToggleBroadcastingButton() {
    return AnimatedBuilder(
      animation: _controller.caregiverService.incomingAlerts,
      builder: (context, child) {
         bool isSyncing = _controller.caregiverService.isBroadcasting;
         return Material(
            color: Colors.transparent,
            child: InkWell(
              onTap: () async {
                await _controller.toggleCaregiverSync();
                setState(() {}); 
              },
              borderRadius: BorderRadius.circular(20),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 300),
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: isSyncing ? Colors.greenAccent.withOpacity(0.1) : Colors.white.withOpacity(0.03),
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(
                    color: isSyncing ? Colors.greenAccent.withOpacity(0.5) : Colors.white.withOpacity(0.08), 
                    width: 1.5
                  ),
                ),
                child: Row(
                  children: [
                     Container(
                       padding: const EdgeInsets.all(12),
                       decoration: BoxDecoration(
                          color: isSyncing ? Colors.greenAccent.withOpacity(0.2) : Colors.grey.withOpacity(0.15),
                          borderRadius: BorderRadius.circular(14),
                       ),
                       child: Icon(isSyncing ? Icons.cell_tower_rounded : Icons.portable_wifi_off_rounded, size: 24, color: isSyncing ? Colors.greenAccent : Colors.white70),
                     ),
                     const SizedBox(width: 16),
                     Expanded(
                       child: Column(
                         crossAxisAlignment: CrossAxisAlignment.start,
                         children: [
                           Text(isSyncing ? "Syncing Active" : "Start Sync", style: const TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.bold, letterSpacing: 0.3)),
                           const SizedBox(height: 2),
                           Text(isSyncing ? "Local Network Live" : "Offline Mode", style: TextStyle(color: isSyncing ? Colors.greenAccent.withOpacity(0.7) : Colors.white.withOpacity(0.5), fontSize: 12, fontWeight: FontWeight.w500)),
                         ],
                       ),
                     ),
                     if (isSyncing)
                        const Icon(Icons.check_circle, color: Colors.greenAccent, size: 18)
                  ],
                ),
              ),
            ),
          );
      }
    );
  }

  // --- DYNAMIC OVERLAYS ---

  List<Widget> _buildObjectOverlays() {
    return _detectedObjects.map((obj) {
      double x = obj['x'];
      double y = obj['y'];
      double w = obj['width'];
      double h = obj['height'];
      double dist = obj['distance'];
      int classId = obj['classId'];
      
      String label = classId == 1 ? "Car" : classId == 2 ? "Chair" : "Person";
      Color boxColor = obj['threatLevel'] > 50 ? Colors.redAccent : Colors.greenAccent;

      return Positioned(
        left: x - w / 2,
        top: y - h / 2,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 100),
          width: w,
          height: h,
          decoration: BoxDecoration(
            border: Border.all(color: boxColor, width: 2),
            borderRadius: BorderRadius.circular(12),
            boxShadow: [
              BoxShadow(
                color: boxColor.withOpacity(0.2),
                blurRadius: 10,
                spreadRadius: 2,
              )
            ]
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                decoration: BoxDecoration(
                  color: boxColor.withOpacity(0.9),
                  borderRadius: const BorderRadius.only(
                    topLeft: Radius.circular(10),
                    bottomRight: Radius.circular(10),
                  ),
                ),
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                     Icon(
                        classId == 1 ? Icons.directions_car : classId == 2 ? Icons.chair : Icons.person,
                        size: 14,
                        color: Colors.black87,
                     ),
                     const SizedBox(width: 6),
                     Text(
                      "$label • ${dist.toStringAsFixed(1)}m",
                      style: const TextStyle(color: Colors.black87, fontWeight: FontWeight.w900, fontSize: 12, letterSpacing: 0.5),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
    }).toList();
  }

  Widget _buildAudioAlertHUD() {
    return Positioned.fill(
      child: IgnorePointer(
        child: AnimatedBuilder(
          animation: _pulseAnimation,
          builder: (context, child) {
            return Container(
              decoration: BoxDecoration(
                border: Border.all(
                  color: Colors.redAccent.withOpacity(0.6 * _pulseAnimation.value),
                  width: 30 * _pulseAnimation.value,
                ),
              ),
              child: Center(
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(24),
                  child: BackdropFilter(
                    filter: ImageFilter.blur(sigmaX: 10, sigmaY: 10),
                    child: Container(
                      padding: const EdgeInsets.symmetric(vertical: 32, horizontal: 48),
                      decoration: BoxDecoration(
                        color: Colors.redAccent.withOpacity(0.7),
                        borderRadius: BorderRadius.circular(24),
                        border: Border.all(color: Colors.white30),
                        boxShadow: [BoxShadow(color: Colors.redAccent.withOpacity(0.5), blurRadius: 40)]
                      ),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const Icon(Icons.hearing_disabled_rounded, size: 72, color: Colors.white),
                          const SizedBox(height: 16),
                          Text(
                            _currentAlert!['type'].toUpperCase(),
                            style: const TextStyle(fontSize: 28, fontWeight: FontWeight.black, color: Colors.white, letterSpacing: 2.0),
                          ),
                          const SizedBox(height: 8),
                          Text(
                            "DIRECTION: ${_currentAlert!['direction'].toUpperCase()}",
                            style: const TextStyle(fontSize: 18, color: Colors.white, fontWeight: FontWeight.bold, letterSpacing: 1.5),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}

class RadarPainter extends CustomPainter {
  final List<Map<String, dynamic>> spatialMap;
  final double pulseValue;

  RadarPainter(this.spatialMap, this.pulseValue);

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height); // Camera originates at bottom center
    
    // Draw Radar Grid
    final gridPaint = Paint()
      ..color = Colors.greenAccent.withOpacity(0.1)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.0;

    for (int i = 1; i <= 4; i++) {
       canvas.drawCircle(center, (size.height / 4) * i, gridPaint);
    }
    
    // Draw sweeping pulse
    final pulsePaint = Paint()
      ..color = Colors.greenAccent.withOpacity(0.05 * (1.2 - pulseValue))
      ..style = PaintingStyle.fill;
    canvas.drawCircle(center, size.height * pulseValue, pulsePaint);

    // Draw Map Points
    for (var point in spatialMap) {
      double alpha = point['alpha'] ?? 1.0;
      if (alpha <= 0) continue;
      
      // Map x (0-640) and distance (0-10m) to local coordinates
      double px = point['x'] ?? 320.0;
      double dist = point['z'] ?? 5.0; // 0 to 10 meters roughly
      
      // Normalize X from 0-640 to -1 to 1
      double nx = (px - 320) / 320.0;
      
      // Calculate radar rendering position
      double radarX = center.dx + (nx * size.width / 2);
      double radarY = center.dy - ((dist / 10.0).clamp(0.0, 1.0) * size.height);

      final pointPaint = Paint()
        ..color = point['z'] < 3.0 ? Colors.redAccent.withOpacity(alpha) : Colors.greenAccent.withOpacity(alpha)
        ..style = PaintingStyle.fill;
        
      canvas.drawCircle(Offset(radarX, radarY), 4.0, pointPaint);
    }
  }

  @override
  bool shouldRepaint(covariant RadarPainter oldDelegate) => true;
}
