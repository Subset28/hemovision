import 'package:flutter/material.dart';
import 'views/home_view.dart';

void main() {
  runApp(const OmniSightApp());
}

class OmniSightApp extends StatelessWidget {
  const OmniSightApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'OmniSight Engine',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF00C853),
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
        fontFamily: 'Inter',
      ),
      home: const HomeView(),
    );
  }
}
