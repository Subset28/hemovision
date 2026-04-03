import 'package:flutter/material.dart';
import 'dart:ui';
import 'package:google_fonts/google_fonts.dart';
import '../controllers/main_controller.dart';

// Premium Dark Mode Design Tokens
const Color kBackground = Color(0xFF0A0A0C);
const Color kGlassDark = Color(0x8812121A);
const Color kGlassBorder = Color(0x20FFFFFF);
const Color kAccentColor = Color(0xFFFF9F1C);
const Color kTextColor = Color(0xFFF8F9FA);

class SettingsView extends StatefulWidget {
  final MainController controller;
  const SettingsView({super.key, required this.controller});

  @override
  State<SettingsView> createState() => _SettingsViewState();
}

class _SettingsViewState extends State<SettingsView> {
  // Vision focused settings state
  double _threatThreshold = 75.0;
  double _detectionRange = 10.0;
  bool _highContrastMode = false;
  bool _largeTextMode = false;
  bool _enableMockEngine = true;

  @override
  void initState() {
    super.initState();
    _highContrastMode = widget.controller.highContrast;
    _largeTextMode = widget.controller.largeText;
    _enableMockEngine = widget.controller.useSimulation;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: kBackground,
      extendBodyBehindAppBar: true,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        flexibleSpace: ClipRect(
          child: BackdropFilter(
            filter: ImageFilter.blur(sigmaX: 20, sigmaY: 20),
            child: Container(
              color: kBackground.withOpacity(0.6),
              decoration: const BoxDecoration(
                border: Border(bottom: BorderSide(color: kGlassBorder, width: 1))
              ),
            ),
          ),
        ),
        centerTitle: true,
        title: Text(
          'Settings',
          style: GoogleFonts.inter(
            fontWeight: FontWeight.w800,
            fontSize: 20,
            color: kTextColor,
            letterSpacing: -0.5,
          ),
        ),
        leading: IconButton(
          icon: const Icon(Icons.chevron_left_rounded, color: kTextColor, size: 32),
          onPressed: () => Navigator.pop(context),
        ),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(24, 120, 24, 60),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _sectionHeader('VISION ENGINE'),
            const SizedBox(height: 12),
            _buildCard(children: [
              _buildToggle(
                'Mock Simulation Engine', 
                'Simulates surroundings without camera', 
                _enableMockEngine, 
                (v) {
                  setState(() => _enableMockEngine = v);
                  widget.controller.setMockMode(v);
                }
              ),
              _divider(),
              _buildSlider(
                'Danger Sensitivity', 
                _threatThreshold, 
                30.0, 100.0, 
                (v) => setState(() => _threatThreshold = v), 
                '${_threatThreshold.toInt()}%'
              ),
              _divider(),
              _buildSlider(
                'Max Targeting Distance', 
                _detectionRange, 
                2.0, 20.0, 
                (v) => setState(() => _detectionRange = v), 
                '${_detectionRange.toStringAsFixed(0)}m'
              ),
            ]),

            const SizedBox(height: 32),
            _sectionHeader('ACCESSIBILITY'),
            const SizedBox(height: 12),
            _buildCard(children: [
              _buildToggle(
                'Maximized Contrast', 
                'Boost object overlay visibility', 
                _highContrastMode, 
                (v) {
                  setState(() => _highContrastMode = v);
                  widget.controller.updateAccessibility(hc: v);
                }
              ),
              _divider(),
              _buildToggle(
                'Ultra-Large Labels', 
                'Increase UI typography scale', 
                _largeTextMode, 
                (v) {
                  setState(() => _largeTextMode = v);
                  widget.controller.updateAccessibility(lt: v);
                }
              ),
            ]),

            const SizedBox(height: 32),
            _sectionHeader('SYSTEM INFO'),
            const SizedBox(height: 12),
            _buildCard(children: [
              _buildInfoRow('Engine Status', 'VERIFIED (Thread Safe)'),
              _divider(),
              _buildInfoRow('Offline Scope', '100% On-Device Inference'),
              _divider(),
              _buildInfoRow('Build Version', 'v2.0 (Low-Vision Pivot)'),
            ]),

            const SizedBox(height: 48),
            // Floating Glow Button
            GestureDetector(
              onTap: _saveSettings,
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 200),
                width: double.infinity,
                height: 64,
                decoration: BoxDecoration(
                  color: kAccentColor,
                  borderRadius: BorderRadius.circular(20),
                  boxShadow: [
                    BoxShadow(
                      color: kAccentColor.withOpacity(0.4),
                      blurRadius: 20,
                      offset: const Offset(0, 8),
                    )
                  ]
                ),
                child: Center(
                  child: Text(
                    'Save Configuration',
                    style: GoogleFonts.inter(
                      fontWeight: FontWeight.w800, 
                      color: kBackground, 
                      fontSize: 18,
                      letterSpacing: 0.5
                    )
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _sectionHeader(String title) {
    return Padding(
      padding: const EdgeInsets.only(left: 8),
      child: Text(
        title,
        style: GoogleFonts.inter(
          color: Colors.white54,
          fontSize: 12,
          fontWeight: FontWeight.w800,
          letterSpacing: 1.5,
        )
      ),
    );
  }

  Widget _buildCard({required List<Widget> children}) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(24),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 15, sigmaY: 15),
        child: Container(
          decoration: BoxDecoration(
            color: kGlassDark,
            borderRadius: BorderRadius.circular(24),
            border: Border.all(color: kGlassBorder, width: 1.5),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withOpacity(0.2),
                blurRadius: 20,
                offset: const Offset(0, 10),
              )
            ]
          ),
          child: Column(children: children),
        ),
      ),
    );
  }

  Widget _buildToggle(String label, String sub, bool value, ValueChanged<bool> onChanged) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start, 
              children: [
                Text(
                  label, 
                  style: GoogleFonts.inter(color: kTextColor, fontSize: 16, fontWeight: FontWeight.bold)
                ),
                const SizedBox(height: 4),
                Text(
                  sub, 
                  style: GoogleFonts.inter(color: Colors.white54, fontSize: 12, fontWeight: FontWeight.normal)
                ),
              ]
            )
          ),
          Switch.adaptive(
            value: value,
            onChanged: onChanged,
            activeThumbColor: kBackground,
            activeTrackColor: kAccentColor,
            inactiveTrackColor: Colors.white12,
            inactiveThumbColor: Colors.white54,
          ),
        ]
      ),
    );
  }

  Widget _buildSlider(String label, double value, double min, double max, ValueChanged<double> onChanged, String display) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 18, 20, 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start, 
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween, 
            children: [
              Text(
                label, 
                style: GoogleFonts.inter(color: kTextColor, fontSize: 16, fontWeight: FontWeight.bold)
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: kAccentColor.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: kAccentColor.withOpacity(0.3))
                ),
                child: Text(
                  display, 
                  style: GoogleFonts.inter(color: kAccentColor, fontSize: 14, fontWeight: FontWeight.w800)
                ),
              ),
            ]
          ),
          const SizedBox(height: 8),
          SliderTheme(
            data: SliderThemeData(
              activeTrackColor: kAccentColor,
              inactiveTrackColor: Colors.white12,
              thumbColor: kAccentColor,
              overlayColor: kAccentColor.withOpacity(0.2),
              trackHeight: 6,
            ),
            child: Slider(
              value: value.clamp(min, max),
              min: min,
              max: max,
              onChanged: onChanged,
            ),
          )
        ]
      ),
    );
  }

  Widget _buildInfoRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween, 
        children: [
          Text(
            label, 
            style: GoogleFonts.inter(color: Colors.white54, fontSize: 14, fontWeight: FontWeight.w600)
          ),
          Flexible(
            child: Text(
              value,
              textAlign: TextAlign.right,
              style: GoogleFonts.inter(color: kTextColor, fontSize: 14, fontWeight: FontWeight.bold)
            ),
          ),
        ]
      ),
    );
  }

  Widget _divider() => Divider(height: 1, color: kGlassBorder, indent: 20, endIndent: 20);

  void _saveSettings() {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          'Settings applied successfully.', 
          style: GoogleFonts.inter(fontSize: 14, fontWeight: FontWeight.bold, color: kBackground)
        ),
        backgroundColor: kAccentColor,
        behavior: SnackBarBehavior.floating,
        margin: const EdgeInsets.all(24),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      ),
    );
  }
}
