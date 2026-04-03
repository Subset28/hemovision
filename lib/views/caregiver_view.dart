import 'package:flutter/material.dart';
import 'dart:async';
import '../services/caregiver_service.dart';
import '../controllers/main_controller.dart';
import '../engines/vision_engine.dart';

class CaregiverView extends StatefulWidget {
  final MainController controller;
  final CaregiverService service;

  const CaregiverView({super.key, required this.controller, required this.service});

  @override
  State<CaregiverView> createState() => _CaregiverViewState();
}

class _CaregiverViewState extends State<CaregiverView> {
  final List<String> _logs = [];
  late StreamSubscription _logSub;

  @override
  void initState() {
    super.initState();
    _logSub = widget.service.statusStream.listen((msg) {
      setState(() {
        _logs.insert(0, '${DateTime.now().toLocal().toString().split(' ')[1].split('.')[0]} - $msg');
        if (_logs.length > 50) _logs.removeLast();
      });
    });
    widget.service.start();
  }

  @override
  void dispose() {
    _logSub.cancel();
    widget.service.stop();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isHighContrast = widget.controller.highContrast;

    return Scaffold(
      backgroundColor: isHighContrast ? Colors.black : const Color(0xFF0A0A0C),
      appBar: AppBar(
        title: const Text('Caregiver Remote Control'),
        backgroundColor: Colors.transparent,
        elevation: 0,
      ),
      body: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Status Card
            _buildStatusCard(theme, isHighContrast),
            const SizedBox(height: 24),
            Text(
              'Real-Time Telemetry Feed',
              style: theme.textTheme.titleMedium?.copyWith(
                color: Colors.white,
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 8),
            Expanded(
              child: _buildLogFeed(theme, isHighContrast),
            ),
            const SizedBox(height: 16),
            _buildActionButtons(theme),
          ],
        ),
      ),
    );
  }

  Widget _buildStatusCard(ThemeData theme, bool isHighContrast) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: isHighContrast ? Colors.black : const Color(0xFF161618),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: isHighContrast ? Colors.white : Colors.blue.withOpacity(0.3),
        ),
      ),
      child: Row(
        children: [
          const Icon(Icons.router, color: Colors.blue, size: 32),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Local TCP Server',
                  style: TextStyle(color: Colors.white70, fontSize: 12),
                ),
                Text(
                  '0.0.0.0:8085',
                  style: theme.textTheme.titleLarge?.copyWith(
                    color: Colors.white,
                    fontFamily: 'JetBrainsMono',
                  ),
                ),
              ],
            ),
          ),
          Column(
            children: [
              const Text(
                'Clients',
                style: TextStyle(color: Colors.white70, fontSize: 12),
              ),
              Text(
                '${widget.service.clientCount}',
                style: theme.textTheme.headlineSmall?.copyWith(
                  color: Colors.blue,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildLogFeed(ThemeData theme, bool isHighContrast) {
    return Container(
      decoration: BoxDecoration(
        color: isHighContrast ? Colors.black : const Color(0xFF161618),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: isHighContrast ? Colors.white : Colors.white10,
        ),
      ),
      child: ListView.separated(
        padding: const EdgeInsets.all(12),
        itemCount: _logs.length,
        separatorBuilder: (_, __) => const Divider(color: Colors.white10),
        itemBuilder: (context, index) => Text(
          _logs[index],
          style: const TextStyle(
            color: Colors.white70,
            fontFamily: 'JetBrainsMono',
            fontSize: 12,
          ),
        ),
      ),
    );
  }

  Widget _buildActionButtons(ThemeData theme) {
    return Row(
      children: [
        Expanded(
          child: ElevatedButton.icon(
            onPressed: () => setState(() => _logs.clear()),
            icon: const Icon(Icons.clear_all),
            label: const Text('Clear Dashboard'),
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.white10,
              foregroundColor: Colors.white,
              padding: const EdgeInsets.symmetric(vertical: 16),
            ),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: ElevatedButton.icon(
            onPressed: () {
              // Trigger a manual poll or sync
            },
            icon: const Icon(Icons.sync),
            label: const Text('Ping Clients'),
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.blue.withOpacity(0.2),
              foregroundColor: Colors.blue,
              padding: const EdgeInsets.symmetric(vertical: 16),
            ),
          ),
        ),
      ],
    );
  }
}
