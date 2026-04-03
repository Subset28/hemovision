import 'dart:ui';
import 'package:flutter/material.dart';
import 'package:camera/camera.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:permission_handler/permission_handler.dart';
import '../controllers/main_controller.dart';
import '../engines/vision_engine.dart';
import 'settings_view.dart';
import '../main.dart';

// Premium Dark Mode Design Tokens
const Color kBackground = Color(0xFF0A0A0C);
const Color kGlassDark = Color(0x8812121A);
const Color kGlassBorder = Color(0x20FFFFFF);
const Color kAccentColor = Color(0xFFFF9F1C); // Warm amber glow (PlayClip inspo)
const Color kAccentInactive = Color(0x44FFFFFF);
const Color kAlertColor = Color(0xFFFF3366); // Premium red/pink alert
const Color kSafeColor = Color(0xFF2EC4B6);  // Teal neon green
const Color kTextColor = Color(0xFFF8F9FA);

class HomeView extends StatefulWidget {
  const HomeView({super.key});

  @override
  State<HomeView> createState() => _HomeViewState();
}

class _HomeViewState extends State<HomeView> {
  late MainController _controller;
  CameraController? _cameraController;
  List<DetectedObjectData> _detectedObjects = [];
  AudioAlertData? _currentAlert;
  bool _isMode1 = true; // Mode 1: Ambient Mode, Mode 2: Target Mode

  @override
  void initState() {
    super.initState();
    _controller = MainController(globalSettings);
    
    _controller.detectedObjectsStream.listen((objects) {
      if (mounted) setState(() => _detectedObjects = objects);
    });

    _controller.audioAlertStream.listen((alert) {
      if (mounted) setState(() => _currentAlert = alert);
    });

    _controller.startProcessing();
    _initCamera();
  }

  Future<void> _initCamera() async {
    final status = await Permission.camera.request();
    if (!status.isGranted) {
      debugPrint('Camera permission denied.');
      return;
    }

    try {
      final cameras = await availableCameras();
      if (cameras.isNotEmpty) {
        _cameraController = CameraController(
          cameras.first, 
          ResolutionPreset.high, 
          enableAudio: false,
          imageFormatGroup: ImageFormatGroup.bgra8888, // Optimal for AI processing
        );
        await _cameraController!.initialize();
        
        // Wire the real-time frame stream to the controller
        _cameraController!.startImageStream((image) {
          _controller.onCameraFrame(image);
        });

        if (mounted) setState(() {});
      }
    } catch (e) {
      debugPrint('Camera failed to initialize: $e');
    }
  }

  @override
  void dispose() {
    _cameraController?.dispose();
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: kBackground,
      extendBodyBehindAppBar: true,
      body: Stack(
        fit: StackFit.expand,
        children: [
          // 1. Live Camera / Simulated Background
          Container(
            color: Colors.black,
            child: Stack(
              fit: StackFit.expand,
              children: [
                if (_cameraController != null && _cameraController!.value.isInitialized)
                  CameraPreview(_cameraController!)
                else
                  Center(
                    child: Icon(
                      _isMode1 ? Icons.camera_alt_outlined : Icons.center_focus_strong_outlined, 
                      size: 150, 
                      color: Colors.white12
                    ),
                  ),
                // Subtle warm gradient glow at the bottom inspired by PlayClip
                Positioned(
                  bottom: -100,
                  left: -100,
                  right: -100,
                  height: 400,
                  child: Container(
                    decoration: BoxDecoration(
                      gradient: RadialGradient(
                        colors: [kAccentColor.withOpacity(0.15), Colors.transparent],
                      ),
                    ),
                  ),
                )
              ],
            ),
          ),
          
          // 2. Object Overlays
          _buildObjectOverlays(_detectedObjects),

          // 2.5 Audio Alert HUD
          if (_currentAlert != null) _buildAlertHUD(_currentAlert!),

          // 3. Floating Top App Bar (Glassmorphic)
          Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: ClipRRect(
              child: BackdropFilter(
                filter: ImageFilter.blur(sigmaX: 20, sigmaY: 20),
                child: Container(
                  padding: EdgeInsets.only(
                    top: MediaQuery.of(context).padding.top + 16,
                    bottom: 20,
                    left: 24,
                    right: 24
                  ),
                  decoration: BoxDecoration(
                    color: kBackground.withOpacity(0.6),
                    border: const Border(
                      bottom: BorderSide(color: kGlassBorder, width: 1)
                    )
                  ),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Row(
                        children: [
                          Icon(Icons.remove_red_eye, color: kAccentColor, size: 28),
                          const SizedBox(width: 12),
                          Text(
                            _isMode1 ? 'Ambient Awareness' : 'Target Tactical',
                            style: GoogleFonts.inter(
                              color: kTextColor,
                              fontWeight: FontWeight.w900,
                              fontSize: 18,
                              letterSpacing: -0.5,
                            ),
                          ),
                        ],
                      ),
                      Container(
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: Colors.white.withOpacity(0.05),
                          border: Border.all(color: kGlassBorder, width: 1)
                        ),
                        child: IconButton(
                          icon: const Icon(Icons.settings_outlined, color: kTextColor),
                          onPressed: () => Navigator.push(
                            context,
                            MaterialPageRoute(builder: (_) => SettingsView(controller: _controller)),
                          ).then((_) => setState(() {})),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Container(
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: _controller.universalMode ? kAccentColor.withOpacity(0.2) : Colors.white.withOpacity(0.05),
                          border: Border.all(color: _controller.universalMode ? kAccentColor : kGlassBorder, width: 1)
                        ),
                        child: IconButton(
                          icon: Icon(
                            _controller.universalMode ? Icons.public_rounded : Icons.person_off_rounded, 
                            color: _controller.universalMode ? kAccentColor : kTextColor
                          ),
                          onPressed: () {
                            setState(() => _controller.updateAccessibility(um: !_controller.universalMode));
                          },
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),

          // 4. Floating Bottom Navigation Pill (Glassmorphic)
          Positioned(
            bottom: 40,
            left: 32,
            right: 32,
            child: _buildFloatingBottomNav(),
          ),
        ],
      ),
    );
  }

  Widget _buildFloatingBottomNav() {
    return ClipRRect(
      borderRadius: BorderRadius.circular(40),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 30, sigmaY: 30),
        child: Container(
          height: 90,
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
          decoration: BoxDecoration(
            color: kGlassDark,
            borderRadius: BorderRadius.circular(40),
            border: Border.all(color: kGlassBorder, width: 1.5),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withOpacity(0.3),
                blurRadius: 20,
                offset: const Offset(0, 10),
              )
            ]
          ),
          child: Row(
            children: [
              Expanded(
                child: _buildPillNavButton(
                  title: 'Ambient',
                  icon: Icons.zoom_out_map_rounded,
                  isActive: _isMode1,
                  onTap: () => setState(() => _isMode1 = true),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: _buildPillNavButton(
                  title: 'Target',
                  icon: Icons.find_in_page_rounded,
                  isActive: !_isMode1,
                  onTap: () => setState(() => _isMode1 = false),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildPillNavButton({
    required String title,
    required IconData icon,
    required bool isActive,
    required VoidCallback onTap,
  }) {
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 300),
        curve: Curves.easeOutCubic,
        decoration: BoxDecoration(
          color: isActive ? kAccentColor : Colors.transparent,
          borderRadius: BorderRadius.circular(30),
          boxShadow: isActive ? [
            BoxShadow(
              color: kAccentColor.withOpacity(0.4),
              blurRadius: 15,
              offset: const Offset(0, 4)
            )
          ] : [],
        ),
        child: Center(
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(
                icon,
                size: 24,
                color: isActive ? kBackground : kAccentInactive,
              ),
              if (isActive) const SizedBox(width: 8),
              if (isActive)
                Text(
                  title,
                  style: GoogleFonts.inter(
                    fontSize: 16,
                    fontWeight: FontWeight.w800,
                    color: kBackground,
                    letterSpacing: 0.5,
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildObjectOverlays(List<DetectedObjectData> objects) {
    // Mode 1: show ONLY critical targets logic
    final displayObjects = _isMode1 ? objects.where((o) => o.isCritical).toList() : objects;

    return Stack(
      children: displayObjects.map((obj) {
        final boxColor = obj.isCritical ? kAlertColor : kSafeColor;
        
        return Positioned(
          left: obj.x - obj.width / 2,
          top: obj.y - obj.height / 2,
          child: Container(
            width: obj.width,
            height: obj.height,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(24),
              border: Border.all(color: boxColor, width: 4.0),
              boxShadow: [
                BoxShadow(
                  color: boxColor.withOpacity(0.5),
                  blurRadius: 20,
                  spreadRadius: 2,
                )
              ]
            ),
            child: Stack(
              clipBehavior: Clip.none,
              children: [
                // Floating Glassmorphic Label Pill
                Positioned(
                  top: -24,
                  left: 20,
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(20),
                    child: BackdropFilter(
                      filter: ImageFilter.blur(sigmaX: 15, sigmaY: 15),
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                        decoration: BoxDecoration(
                          color: boxColor.withOpacity(0.2),
                          borderRadius: BorderRadius.circular(20),
                          border: Border.all(color: boxColor.withOpacity(0.5), width: 1.5)
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Container(
                              width: 10,
                              height: 10,
                              decoration: BoxDecoration(
                                shape: BoxShape.circle,
                                color: boxColor,
                                boxShadow: [BoxShadow(color: boxColor, blurRadius: 5)]
                              ),
                            ),
                            const SizedBox(width: 8),
                            Text(
                              _controller.universalMode 
                                ? '${obj.label.toUpperCase()} • ${(obj.distance * 3.28).toStringAsFixed(0)}ft'
                                : '${obj.label.toUpperCase()} • ${obj.distance.toStringAsFixed(1)}m',
                              style: GoogleFonts.inter(
                                color: Colors.white,
                                fontWeight: FontWeight.w900,
                                fontSize: 18,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        );
      }).toList(),
    );
  }

  Widget _buildAlertHUD(AudioAlertData alert) {
    return Positioned(
      top: 140,
      left: 24,
      right: 24,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(20),
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 20, sigmaY: 20),
          child: Container(
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(
              color: const Color(0xFFFF3366).withOpacity(0.15),
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: const Color(0xFFFF3366).withOpacity(0.5), width: 1.5),
            ),
            child: Row(
              children: [
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: const Color(0xFFFF3366),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: const Icon(Icons.emergency_rounded, color: Colors.white, size: 30),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        alert.type.toUpperCase(),
                        style: GoogleFonts.inter(color: Colors.white, fontWeight: FontWeight.w900, fontSize: 18),
                      ),
                      Text(
                        'Location: ${alert.direction} | ${alert.frequency.toInt()} Hz',
                        style: GoogleFonts.inter(color: Colors.white70, fontSize: 14, fontWeight: FontWeight.w600),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
