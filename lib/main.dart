import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_fonts/google_fonts.dart';
import 'views/home_view.dart';
import 'views/onboarding_view.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // ─────────────────────────────────────────────────────────────────────────────
  //  OFFLINE ASSET CONFIGURATION
  //  Disabling runtime fetching ensures the app works in air-gapped environments.
  //  It will strictly use the .ttf assets bundled in pubspec.yaml.
  // ─────────────────────────────────────────────────────────────────────────────
  // Pre-load critical assets and allow offline fonts (fetch once, cache forever)
  GoogleFonts.config.allowRuntimeFetching = true;

  // Lock orientation to portrait for mobile, allow all for desktop
  await SystemChrome.setPreferredOrientations([
    DeviceOrientation.portraitUp,
    DeviceOrientation.landscapeLeft,
    DeviceOrientation.landscapeRight,
  ]);

  // Full immersive mode for a premium feel
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: Colors.transparent,
    statusBarBrightness: Brightness.dark,
    statusBarIconBrightness: Brightness.light,
    systemNavigationBarColor: Color(0xFF07070A),
    systemNavigationBarIconBrightness: Brightness.light,
  ));

  runApp(const OmniSightApp());
}

class OmniSightApp extends StatelessWidget {
  const OmniSightApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'OmniSight Engine',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFFFF9F1C),
          brightness: Brightness.dark,
          surface: const Color(0xFF0A0A0C),
        ),
        useMaterial3: true,
        textTheme: GoogleFonts.interTextTheme(ThemeData.dark().textTheme),
        scaffoldBackgroundColor: const Color(0xFF0A0A0C),
        splashFactory: InkRipple.splashFactory,
      ),
      home: const SplashScreen(),
    );
  }
}

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen>
    with SingleTickerProviderStateMixin {
  late AnimationController _ctrl;
  late Animation<double> _fade;
  late Animation<double> _scale;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
        vsync: this, duration: const Duration(milliseconds: 1800));

    _fade = Tween<double>(begin: 0.0, end: 1.0).animate(
        CurvedAnimation(parent: _ctrl, curve: const Interval(0.0, 0.5)));

    _scale = Tween<double>(begin: 0.85, end: 1.0).animate(
        CurvedAnimation(parent: _ctrl, curve: Curves.easeOutCubic));

    _ctrl.forward();

    Future.delayed(const Duration(milliseconds: 2600), () {
      if (mounted) {
        Navigator.of(context).pushReplacement(
          PageRouteBuilder(
            transitionDuration: const Duration(milliseconds: 600),
            pageBuilder: (_, animation, __) => FadeTransition(
                opacity: animation, child: const OnboardingView()),
          ),
        );
      }
    });
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF07070A),
      body: Center(
        child: AnimatedBuilder(
          animation: _ctrl,
          builder: (context, _) => Opacity(
            opacity: _fade.value,
            child: Transform.scale(
              scale: _scale.value,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  // Animated logo ring
                  Container(
                    width: 110,
                    height: 110,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      gradient: RadialGradient(
                        colors: [
                          const Color(0xFFFF9F1C).withOpacity(0.3),
                          Colors.transparent,
                        ],
                      ),
                      border: Border.all(
                        color: const Color(0xFFFF9F1C).withOpacity(0.5),
                        width: 2,
                      ),
                    ),
                    child: const Icon(Icons.remove_red_eye_outlined,
                        size: 54, color: Color(0xFFFF9F1C)),
                  ),
                  const SizedBox(height: 28),
                  Text('OmniSight',
                      style: GoogleFonts.inter(
                        fontSize: 36,
                        fontWeight: FontWeight.w900,
                        color: Colors.white,
                        letterSpacing: -1.5,
                      )),
                  const SizedBox(height: 8),
                  Text('ENGINE  v2.0',
                      style: GoogleFonts.inter(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                        color: const Color(0xFFFF9F1C),
                        letterSpacing: 4.0,
                      )),
                  const SizedBox(height: 48),
                  SizedBox(
                    width: 160,
                    child: LinearProgressIndicator(
                      value: _ctrl.value,
                      backgroundColor:
                          const Color(0xFFFF9F1C).withOpacity(0.1),
                      valueColor: const AlwaysStoppedAnimation<Color>(
                          Color(0xFFFF9F1C)),
                      borderRadius: BorderRadius.circular(8),
                    ),
                  ),
                  const SizedBox(height: 16),
                  Text('INITIALIZING CORE MODULES...',
                      style: GoogleFonts.inter(
                        fontSize: 11,
                        color: Colors.white38,
                        letterSpacing: 2.0,
                      )),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
