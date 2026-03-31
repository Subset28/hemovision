import 'package:flutter/material.dart';
import 'dart:ui';
import 'package:google_fonts/google_fonts.dart';
import '../controllers/main_controller.dart';

// ─────────────────────────────────────────────────────────────────
//  DESIGN TOKENS (Shared System)
// ─────────────────────────────────────────────────────────────────
const Color kObsidian = Color(0xFF030305);
const Color kDeepNavy = Color(0xFF0A0A14);
const Color kNeonCyan = Color(0xFF00FFD1);
const Color kCyberBlue = Color(0xFF2E6FF2);
const Color kEmergencyRed = Color(0xFFFF3131);
const Color kAmberAlert = Color(0xFFFFB800);

// ─────────────────────────────────────────────────────────────────
//  SETTINGS VIEW — Engine and audio calibration configuration
// ─────────────────────────────────────────────────────────────────
class SettingsView extends StatefulWidget {
  final MainController controller;
  const SettingsView({super.key, required this.controller});

  @override
  State<SettingsView> createState() => _SettingsViewState();
}

class _SettingsViewState extends State<SettingsView> {
  // Settings state
  double _audioVolume = 0.8;
  double _vibrationIntensity = 0.7;
  double _threatThreshold = 75.0;
  double _detectionRange = 10.0;
  bool _enableSpatialAudio = true;
  bool _enableHaptics = true;
  bool _enableSirenDetection = true;
  bool _enableSlamTracking = true;
  bool _highContrastMode = false;
  bool _largeTextMode = false;
  String _selectedAudioProfile = 'Standard';

  @override
  void initState() {
    super.initState();
    _highContrastMode = widget.controller.highContrast;
    _largeTextMode = widget.controller.largeText;
  }

  final List<String> _audioProfiles = ['Standard', 'Low Frequency', 'Bone Conduction', 'Silent'];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: kObsidian,
      extendBodyBehindAppBar: true,
      appBar: AppBar(
        backgroundColor: Colors.black.withValues(alpha: 0.4),
        elevation: 0,
        flexibleSpace: ClipRect(
          child: BackdropFilter(
            filter: ImageFilter.blur(sigmaX: 15, sigmaY: 15),
            child: Container(color: Colors.transparent),
          ),
        ),
        centerTitle: true,
        title: Text(
          'ENGINE CALIBRATION',
          style: GoogleFonts.orbitron(
            fontWeight: FontWeight.w900,
            fontSize: 14,
            letterSpacing: 4.0,
            color: kNeonCyan,
          ),
        ),
        leading: IconButton(
          icon: const Icon(Icons.chevron_left_rounded, color: Colors.white70, size: 28),
          onPressed: () => Navigator.pop(context),
        ),
        actions: [
          TextButton(
            onPressed: _resetDefaults,
            child: Text('RESET', style: GoogleFonts.inter(color: kEmergencyRed.withValues(alpha: 0.7), fontSize: 10, fontWeight: FontWeight.w900, letterSpacing: 1.5)),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 120, 20, 40),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _sectionHeader('MODULE A — SPATIAL AUDIO', Icons.surround_sound_rounded, kCyberBlue),
            const SizedBox(height: 16),
            _buildCard(children: [
              _buildToggle('Enable 8D Spatial Audio', 'Distance-mapped 3D sound cues', _enableSpatialAudio, (v) => setState(() => _enableSpatialAudio = v), kCyberBlue),
              _divider(),
              _buildDropdown('Audio Output Profile', 'Optimized for different hearing needs', _selectedAudioProfile, _audioProfiles, (v) => setState(() => _selectedAudioProfile = v!)),
              _divider(),
              _buildSlider('Master Volume', _audioVolume, 0.0, 1.0, (v) => setState(() => _audioVolume = v), kCyberBlue, '${(_audioVolume * 100).toInt()}%'),
            ]),

            const SizedBox(height: 32),
            _sectionHeader('MODULE B — AR HAPTICS', Icons.vibration_rounded, kAmberAlert),
            const SizedBox(height: 16),
            _buildCard(children: [
              _buildToggle('Enable Haptic Alerts', 'Vibration for critical threats', _enableHaptics, (v) => setState(() => _enableHaptics = v), kAmberAlert),
              _divider(),
              _buildToggle('High Contrast HUD', 'AA/AAA compliant colors', _highContrastMode, (v) {
                setState(() => _highContrastMode = v);
                widget.controller.updateAccessibility(hc: v);
              }, kAmberAlert),
              _divider(),
              _buildToggle('Large Data Readouts', 'Increased text scaling', _largeTextMode, (v) {
                setState(() => _largeTextMode = v);
                widget.controller.updateAccessibility(lt: v);
              }, kAmberAlert),
              _divider(),
              _buildToggle('Siren Detection', 'FFT-based audio threat identification', _enableSirenDetection, (v) => setState(() => _enableSirenDetection = v), kAmberAlert),
              _divider(),
              _buildSlider('Vibration Intensity', _vibrationIntensity, 0.0, 1.0, (v) => setState(() => _vibrationIntensity = v), kAmberAlert, '${(_vibrationIntensity * 100).toInt()}%'),
            ]),

            const SizedBox(height: 32),
            _sectionHeader('MODULE D — SLAM TRACKING', Icons.radar_rounded, kNeonCyan),
            const SizedBox(height: 16),
            _buildCard(children: [
              _buildToggle('SLAM-lite Spatial Memory', 'Environmental topography mapping', _enableSlamTracking, (v) => setState(() => _enableSlamTracking = v), kNeonCyan),
              _divider(),
              _buildSlider('Detection Range', _detectionRange, 2.0, 20.0, (v) => setState(() => _detectionRange = v), kNeonCyan, '${_detectionRange.toStringAsFixed(0)}m'),
              _divider(),
              _buildSlider('Threat Alert Threshold', _threatThreshold, 30.0, 100.0, (v) => setState(() => _threatThreshold = v), kNeonCyan, '${_threatThreshold.toInt()} / 100'),
            ]),

            const SizedBox(height: 32),
            _sectionHeader('SYSTEM CORE INFO', Icons.info_outline_rounded, Colors.white24),
            const SizedBox(height: 16),
            _buildCard(children: [
              _buildInfoRow('Engine Status', 'VERIFIED (Thread Safe)'),
              _divider(),
              _buildInfoRow('Offline Reach', 'GLOBAL (100% Standalone)'),
              _divider(),
              _buildInfoRow('Persistence', 'ENCRYPTED & LOCAL'),
              _divider(),
              _buildInfoRow('Latency Mode', 'Ultra-Low Isolate-Bound'),
              _divider(),
              _buildInfoRow('Build Version', 'v1.0.0 (TSA Gold Edition)'),
            ]),

            const SizedBox(height: 48),
            // Save button
            SizedBox(
              width: double.infinity,
              height: 64,
              child: ElevatedButton(
                onPressed: _saveSettings,
                style: ElevatedButton.styleFrom(
                  backgroundColor: kNeonCyan,
                  foregroundColor: kObsidian,
                  elevation: 12,
                  shadowColor: kNeonCyan.withValues(alpha: 0.35),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                ),
                child: Text('COMMIT CALIBRATION',
                    style: GoogleFonts.orbitron(fontWeight: FontWeight.w900, letterSpacing: 2.5, fontSize: 13)),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _sectionHeader(String title, IconData icon, Color color) {
    return Row(children: [
      Icon(icon, size: 16, color: color.withValues(alpha: 0.5)),
      const SizedBox(width: 12),
      Text(title,
          style: GoogleFonts.orbitron(
            color: color.withValues(alpha: 0.8),
            fontSize: 11,
            fontWeight: FontWeight.w800,
            letterSpacing: 2.5,
          )),
    ]);
  }

  Widget _buildCard({required List<Widget> children}) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.03),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: Colors.white.withValues(alpha: 0.08), width: 1.2),
      ),
      child: Column(children: children),
    );
  }

  Widget _buildToggle(String label, String sub, bool value, Function(bool) onChanged, Color color) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
      child: Row(children: [
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: GoogleFonts.inter(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w700, letterSpacing: 0.5)),
          const SizedBox(height: 4),
          Text(sub.toUpperCase(), style: GoogleFonts.inter(color: Colors.white24, fontSize: 9, fontWeight: FontWeight.w800, letterSpacing: 1.0)),
        ])),
        Switch.adaptive(
          value: value,
          onChanged: onChanged,
          activeThumbColor: color,
          activeTrackColor: color.withValues(alpha: 0.3),
        ),
      ]),
    );
  }

  Widget _buildSlider(String label, double value, double min, double max, Function(double) onChanged, Color color, String display) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 16, 18, 10),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          Text(label, style: GoogleFonts.inter(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w700, letterSpacing: 0.5)),
          Text(display, style: GoogleFonts.jetBrainsMono(color: color, fontSize: 12, fontWeight: FontWeight.bold)),
        ]),
        Slider(
          value: value.clamp(min, max),
          min: min,
          max: max,
          onChanged: onChanged,
          activeColor: color,
          inactiveColor: color.withValues(alpha: 0.12),
        ),
      ]),
    );
  }

  Widget _buildDropdown(String label, String sub, String value, List<String> options, Function(String?) onChanged) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: GoogleFonts.inter(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w700, letterSpacing: 0.5)),
        const SizedBox(height: 4),
        Text(sub.toUpperCase(), style: GoogleFonts.inter(color: Colors.white24, fontSize: 9, fontWeight: FontWeight.w800, letterSpacing: 1.0)),
        const SizedBox(height: 14),
        DropdownButtonFormField<String>(
          initialValue: value,
          onChanged: onChanged,
          dropdownColor: kDeepNavy,
          style: GoogleFonts.inter(color: Colors.white, fontSize: 13),
          decoration: InputDecoration(
            contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
            filled: true,
            fillColor: Colors.black.withValues(alpha: 0.4),
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(16),
              borderSide: BorderSide.none,
            ),
          ),
          items: options.map((o) => DropdownMenuItem(value: o, child: Text(o))).toList(),
        ),
      ]),
    );
  }

  Widget _buildInfoRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
      child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        Text(label.toUpperCase(), style: GoogleFonts.inter(color: Colors.white24, fontSize: 10, fontWeight: FontWeight.w800, letterSpacing: 1.5)),
        Flexible(
          child: Text(value,
              textAlign: TextAlign.right,
              style: GoogleFonts.jetBrainsMono(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w700)),
        ),
      ]),
    );
  }

  Widget _divider() => Divider(height: 1, color: Colors.white.withValues(alpha: 0.06), indent: 18, endIndent: 18);

  void _saveSettings() {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('CALIBRATION COMMITTED TO ENGINE', style: GoogleFonts.orbitron(fontSize: 11, fontWeight: FontWeight.w800, letterSpacing: 2.0)),
        backgroundColor: kNeonCyan.withValues(alpha: 0.15),
        behavior: SnackBarBehavior.floating,
        margin: const EdgeInsets.all(24),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16), 
          side: BorderSide(color: kNeonCyan.withValues(alpha: 0.3)),
        ),
      ),
    );
  }

  void _resetDefaults() {
    setState(() {
      _audioVolume = 0.8;
      _vibrationIntensity = 0.7;
      _threatThreshold = 75.0;
      _detectionRange = 10.0;
      _enableSpatialAudio = true;
      _enableHaptics = true;
      _enableSirenDetection = true;
      _enableSlamTracking = true;
      _highContrastMode = false;
      _largeTextMode = false;
      _selectedAudioProfile = 'Standard';
    });
  }
}
