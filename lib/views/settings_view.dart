import 'package:flutter/material.dart';
import 'dart:ui';
import 'package:google_fonts/google_fonts.dart';

// ─────────────────────────────────────────────────────────────────
//  SETTINGS VIEW — Engine and audio calibration configuration
// ─────────────────────────────────────────────────────────────────
class SettingsView extends StatefulWidget {
  const SettingsView({super.key});

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

  final List<String> _audioProfiles = ['Standard', 'Low Frequency (Hearing Aid)', 'Bone Conduction', 'Silent (Visual Only)'];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF07070A),
      extendBodyBehindAppBar: true,
      appBar: AppBar(
        backgroundColor: Colors.black.withOpacity(0.5),
        elevation: 0,
        flexibleSpace: ClipRect(
          child: BackdropFilter(
            filter: ImageFilter.blur(sigmaX: 10, sigmaY: 10),
            child: Container(color: Colors.transparent),
          ),
        ),
        centerTitle: true,
        title: Text(
          'ENGINE CALIBRATION',
          style: GoogleFonts.inter(
            fontWeight: FontWeight.w900,
            fontSize: 14,
            letterSpacing: 2.5,
            color: Colors.white,
          ),
        ),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios_rounded, color: Colors.white70, size: 20),
          onPressed: () => Navigator.pop(context),
        ),
        actions: [
          TextButton(
            onPressed: _resetDefaults,
            child: Text('Reset', style: GoogleFonts.inter(color: Colors.redAccent.withOpacity(0.8), fontSize: 13)),
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 110, 20, 40),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _sectionHeader('MODULE A — SPATIAL AUDIO', Icons.surround_sound_rounded, Colors.blueAccent),
            const SizedBox(height: 16),
            _buildCard(children: [
              _buildToggle('Enable 8D Spatial Audio', 'Distance-mapped 3D sound cues', _enableSpatialAudio, (v) => setState(() => _enableSpatialAudio = v), Colors.blueAccent),
              _divider(),
              _buildDropdown('Audio Output Profile', 'Optimized for different hearing needs', _selectedAudioProfile, _audioProfiles, (v) => setState(() => _selectedAudioProfile = v!)),
              _divider(),
              _buildSlider('Master Volume', _audioVolume, 0.0, 1.0, (v) => setState(() => _audioVolume = v), Colors.blueAccent, '${(_audioVolume * 100).toInt()}%'),
            ]),

            const SizedBox(height: 28),
            _sectionHeader('MODULE B — AR HAPTICS', Icons.vibration_rounded, Colors.orangeAccent),
            const SizedBox(height: 16),
            _buildCard(children: [
              _buildToggle('Enable Haptic Alerts', 'Vibration for critical threats', _enableHaptics, (v) => setState(() => _enableHaptics = v), Colors.orangeAccent),
              _divider(),
              _buildToggle('Siren Detection', 'FFT-based audio threat identification', _enableSirenDetection, (v) => setState(() => _enableSirenDetection = v), Colors.orangeAccent),
              _divider(),
              _buildSlider('Vibration Intensity', _vibrationIntensity, 0.0, 1.0, (v) => setState(() => _vibrationIntensity = v), Colors.orangeAccent, '${(_vibrationIntensity * 100).toInt()}%'),
            ]),

            const SizedBox(height: 28),
            _sectionHeader('MODULE D — SLAM TRACKING', Icons.radar_rounded, Colors.greenAccent),
            const SizedBox(height: 16),
            _buildCard(children: [
              _buildToggle('SLAM-lite Spatial Memory', 'Environmental topography mapping', _enableSlamTracking, (v) => setState(() => _enableSlamTracking = v), Colors.greenAccent),
              _divider(),
              _buildSlider('Detection Range', _detectionRange, 2.0, 20.0, (v) => setState(() => _detectionRange = v), Colors.greenAccent, '${_detectionRange.toStringAsFixed(0)}m'),
              _divider(),
              _buildSlider('Threat Alert Threshold', _threatThreshold, 30.0, 100.0, (v) => setState(() => _threatThreshold = v), Colors.greenAccent, '${_threatThreshold.toInt()} / 100'),
            ]),

            const SizedBox(height: 28),
            _sectionHeader('ACCESSIBILITY', Icons.accessibility_new_rounded, Colors.purpleAccent),
            const SizedBox(height: 16),
            _buildCard(children: [
              _buildToggle('High Contrast Mode', 'Maximized color contrast for low vision', _highContrastMode, (v) => setState(() => _highContrastMode = v), Colors.purpleAccent),
              _divider(),
              _buildToggle('Large Text Mode', 'Increased font sizes throughout UI', _largeTextMode, (v) => setState(() => _largeTextMode = v), Colors.purpleAccent),
            ]),

            const SizedBox(height: 28),
            _sectionHeader('SYSTEM INFO', Icons.info_outline_rounded, Colors.white38),
            const SizedBox(height: 16),
            _buildCard(children: [
              _buildInfoRow('Engine Mode', 'Mock Simulation (C++ DLL pending)'),
              _divider(),
              _buildInfoRow('Architecture', 'Flutter + Dart FFI + C++ ONNX'),
              _divider(),
              _buildInfoRow('Connectivity', '100% Offline — Local TCP only'),
              _divider(),
              _buildInfoRow('Target Platform', 'Android 13+ / iOS 16+ / Windows 11'),
              _divider(),
              _buildInfoRow('AI Model', 'YOLOv8 quantized ONNX (pending)'),
            ]),

            const SizedBox(height: 40),
            // Save button
            SizedBox(
              width: double.infinity,
              height: 60,
              child: ElevatedButton(
                onPressed: _saveSettings,
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFF00E5FF).withOpacity(0.15),
                  foregroundColor: const Color(0xFF00E5FF),
                  elevation: 0,
                  side: const BorderSide(color: Color(0xFF00E5FF), width: 1.5),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
                ),
                child: Text('SAVE CALIBRATION',
                    style: GoogleFonts.inter(fontWeight: FontWeight.w800, letterSpacing: 2.0, fontSize: 14)),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _sectionHeader(String title, IconData icon, Color color) {
    return Row(children: [
      Icon(icon, size: 18, color: color),
      const SizedBox(width: 10),
      Text(title,
          style: GoogleFonts.inter(
            color: color.withOpacity(0.9),
            fontSize: 12,
            fontWeight: FontWeight.w800,
            letterSpacing: 2.0,
          )),
    ]);
  }

  Widget _buildCard({required List<Widget> children}) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.025),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: Colors.white.withOpacity(0.06)),
      ),
      child: Column(children: children),
    );
  }

  Widget _buildToggle(String label, String sub, bool value, Function(bool) onChanged, Color color) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
      child: Row(children: [
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: GoogleFonts.inter(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w600)),
          const SizedBox(height: 3),
          Text(sub, style: GoogleFonts.inter(color: Colors.white38, fontSize: 12)),
        ])),
        Switch.adaptive(
          value: value,
          onChanged: onChanged,
          activeColor: color,
          activeTrackColor: color.withOpacity(0.25),
        ),
      ]),
    );
  }

  Widget _buildSlider(String label, double value, double min, double max, Function(double) onChanged, Color color, String display) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 14, 18, 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          Text(label, style: GoogleFonts.inter(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w600)),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            decoration: BoxDecoration(color: color.withOpacity(0.12), borderRadius: BorderRadius.circular(8)),
            child: Text(display, style: GoogleFonts.inter(color: color, fontSize: 12, fontWeight: FontWeight.w700)),
          ),
        ]),
        Slider(
          value: value.clamp(min, max),
          min: min,
          max: max,
          onChanged: onChanged,
          activeColor: color,
          inactiveColor: color.withOpacity(0.12),
        ),
      ]),
    );
  }

  Widget _buildDropdown(String label, String sub, String value, List<String> options, Function(String?) onChanged) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: GoogleFonts.inter(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w600)),
        const SizedBox(height: 3),
        Text(sub, style: GoogleFonts.inter(color: Colors.white38, fontSize: 12)),
        const SizedBox(height: 10),
        DropdownButtonFormField<String>(
          value: value,
          onChanged: onChanged,
          dropdownColor: const Color(0xFF12121A),
          style: GoogleFonts.inter(color: Colors.white, fontSize: 13),
          decoration: InputDecoration(
            contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            filled: true,
            fillColor: Colors.white.withOpacity(0.05),
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: BorderSide(color: Colors.white.withOpacity(0.12)),
            ),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: BorderSide(color: Colors.white.withOpacity(0.08)),
            ),
          ),
          items: options.map((o) => DropdownMenuItem(value: o, child: Text(o))).toList(),
        ),
      ]),
    );
  }

  Widget _buildInfoRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
      child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        Text(label, style: GoogleFonts.inter(color: Colors.white54, fontSize: 13)),
        Flexible(
          child: Text(value,
              textAlign: TextAlign.right,
              style: GoogleFonts.inter(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w600)),
        ),
      ]),
    );
  }

  Widget _divider() => Divider(height: 1, color: Colors.white.withOpacity(0.05), indent: 18, endIndent: 18);

  void _saveSettings() {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('Calibration saved successfully', style: GoogleFonts.inter(fontSize: 13)),
        backgroundColor: Colors.greenAccent.withOpacity(0.2),
        behavior: SnackBarBehavior.floating,
        margin: const EdgeInsets.all(16),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
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
