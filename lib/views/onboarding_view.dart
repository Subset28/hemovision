import 'dart:ui';
import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:permission_handler/permission_handler.dart';
import 'home_view.dart';

const Color kBackground = Color(0xFF0A0A0C);
const Color kGlassDark = Color(0x8812121A);
const Color kGlassBorder = Color(0x20FFFFFF);
const Color kAccentColor = Color(0xFFFF9F1C);
const Color kTextColor = Color(0xFFF8F9FA);

class OnboardingView extends StatefulWidget {
  const OnboardingView({super.key});

  @override
  State<OnboardingView> createState() => _OnboardingViewState();
}

class _OnboardingViewState extends State<OnboardingView> {
  final PageController _pageController = PageController();
  int _currentPage = 0;

  final List<Map<String, dynamic>> _onboardingData = [
    {
      'title': 'Navigation\nMade Simple.',
      'description': 'Welcome to OmniSight. We process your surroundings in real-time so you can navigate safely without clutter.',
      'icon': Icons.remove_red_eye_rounded,
    },
    {
      'title': 'Ambient Mode.',
      'description': 'Hold your phone up to see clearly. We naturally keep the view wide and clean, only interrupting you if something dangerous gets too close.',
      'icon': Icons.zoom_out_map_rounded,
    },
    {
      'title': 'Focus Mode.',
      'description': 'Need more detail? Switch to Focus Mode to have your entire immediate environment mapped and pinpointed perfectly.',
      'icon': Icons.find_in_page_rounded,
    },
  ];

  Future<void> _nextPage() async {
    if (_currentPage < _onboardingData.length - 1) {
      _pageController.animateToPage(
        _currentPage + 1,
        duration: const Duration(milliseconds: 600),
        curve: Curves.easeOutCubic,
      );
    } else {
      // Hardware Permission Check for "Real App" verification
      final status = await Permission.camera.request();
      
      if (status.isGranted) {
        if (mounted) {
          Navigator.of(context).pushReplacement(
            PageRouteBuilder(
              transitionDuration: const Duration(milliseconds: 800),
              pageBuilder: (_, animation, __) => FadeTransition(opacity: animation, child: const HomeView()),
            ),
          );
        }
      } else {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                'Camera Access Denied. OmniSight will operate in Simulation Mode without live background frames.',
                style: GoogleFonts.inter(fontWeight: FontWeight.w600),
              ),
              backgroundColor: const Color(0xFFFF3366),
              duration: const Duration(seconds: 4),
            ),
          );
          // Still push to HomeView so they can see the Mock simulation UI
          Future.delayed(const Duration(seconds: 1), () {
            if (mounted) {
              Navigator.of(context).pushReplacement(
                PageRouteBuilder(
                  transitionDuration: const Duration(milliseconds: 800),
                  pageBuilder: (_, animation, __) => FadeTransition(opacity: animation, child: const HomeView()),
                ),
              );
            }
          });
        }
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: kBackground,
      body: Stack(
        fit: StackFit.expand,
        children: [
          // Ambient Glow Background
          Positioned(
            top: -150,
            left: -100,
            right: -100,
            height: 500,
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 800),
              decoration: BoxDecoration(
                gradient: RadialGradient(
                  colors: [
                    kAccentColor.withOpacity(_currentPage == 0 ? 0.2 : 0.1), 
                    Colors.transparent
                  ],
                ),
              ),
            ),
          ),
          
          PageView.builder(
            controller: _pageController,
            onPageChanged: (index) => setState(() => _currentPage = index),
            itemCount: _onboardingData.length,
            itemBuilder: (context, index) {
              return Padding(
                padding: const EdgeInsets.symmetric(horizontal: 40.0),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Container(
                      padding: const EdgeInsets.all(24),
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: kAccentColor.withOpacity(0.1),
                        border: Border.all(color: kAccentColor.withOpacity(0.3), width: 2)
                      ),
                      child: Icon(
                        _onboardingData[index]['icon'],
                        size: 80,
                        color: kAccentColor,
                      ),
                    ),
                    const SizedBox(height: 60),
                    Text(
                      _onboardingData[index]['title'],
                      style: GoogleFonts.inter(
                        color: kTextColor,
                        fontSize: 42,
                        height: 1.1,
                        fontWeight: FontWeight.w900,
                        letterSpacing: -1.0,
                      ),
                    ),
                    const SizedBox(height: 24),
                    Text(
                      _onboardingData[index]['description'],
                      style: GoogleFonts.inter(
                        color: Colors.white70,
                        fontSize: 20,
                        height: 1.5,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                    const SizedBox(height: 120), // padded for bottom bar
                  ],
                ),
              );
            },
          ),
          
          // Floating Action Bottom Bar
          Positioned(
            bottom: 40,
            left: 32,
            right: 32,
            child: ClipRRect(
              borderRadius: BorderRadius.circular(40),
              child: BackdropFilter(
                filter: ImageFilter.blur(sigmaX: 30, sigmaY: 30),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 20),
                  decoration: BoxDecoration(
                    color: kGlassDark,
                    borderRadius: BorderRadius.circular(40),
                    border: Border.all(color: kGlassBorder, width: 1.5),
                  ),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      // Pagination Dots
                      Row(
                        children: List.generate(
                          _onboardingData.length,
                          (index) => AnimatedContainer(
                            duration: const Duration(milliseconds: 300),
                            margin: const EdgeInsets.only(right: 8),
                            height: 10,
                            width: _currentPage == index ? 24 : 10,
                            decoration: BoxDecoration(
                              color: _currentPage == index ? kAccentColor : Colors.white24,
                              borderRadius: BorderRadius.circular(5),
                            ),
                          ),
                        ),
                      ),
                      
                      // Next Button
                      GestureDetector(
                        onTap: _nextPage,
                        child: AnimatedContainer(
                          duration: const Duration(milliseconds: 300),
                          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
                          decoration: BoxDecoration(
                            color: kAccentColor,
                            borderRadius: BorderRadius.circular(30),
                            boxShadow: [
                              BoxShadow(
                                color: kAccentColor.withOpacity(0.4),
                                blurRadius: 15,
                                offset: const Offset(0, 4),
                              )
                            ]
                          ),
                          child: Text(
                            _currentPage == _onboardingData.length - 1 ? 'Start' : 'Next',
                            style: GoogleFonts.inter(
                              color: kBackground,
                              fontSize: 18,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
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
    );
  }
}
