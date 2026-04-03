import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hemovision/views/settings_view.dart';
import 'package:hemovision/controllers/main_controller.dart';
import 'package:google_fonts/google_fonts.dart';

void main() {
  // Disable runtime font fetching for tests to prevent network errors
  GoogleFonts.config.allowRuntimeFetching = false;

  group('SettingsView Functional Interaction Tests', () {
    late MainController controller;

    setUp(() {
      // MainController handles its own mock-mode fallback if native libs are missing
      controller = MainController();
    });

    testWidgets('Toggling High Contrast updates Controller state', (WidgetTester tester) async {
      await tester.pumpWidget(MaterialApp(
        home: SettingsView(controller: controller),
      ));

      // 1. Initial State Check
      expect(controller.highContrast, isFalse);

      // 2. Find the High Contrast Toggle 
      // It is the first Switch.adaptive in the list
      final hcToggle = find.byType(Switch).first;
      expect(hcToggle, findsOneWidget);

      // 3. Perform Toggle Action
      await tester.tap(hcToggle);
      await tester.pumpAndSettle(); // Wait for animation

      // 4. Verification
      expect(controller.highContrast, isTrue, 
        reason: 'Toggling the switch must update the controller instance state.');
      
      // 5. Toggle Back
      await tester.tap(hcToggle);
      await tester.pumpAndSettle();
      expect(controller.highContrast, isFalse);
    });

    testWidgets('Toggling Large Text updates Controller state', (WidgetTester tester) async {
      await tester.pumpWidget(MaterialApp(
        home: SettingsView(controller: controller),
      ));

      expect(controller.largeText, isFalse);

      // Find the second Switch (Large Text)
      final ltToggle = find.byType(Switch).at(1);
      
      await tester.tap(ltToggle);
      await tester.pumpAndSettle();

      expect(controller.largeText, isTrue);
    });

    testWidgets('Settings saved Snackbar appears on Save button tap', (WidgetTester tester) async {
      await tester.pumpWidget(MaterialApp(
        home: SettingsView(controller: controller),
      ));

      // Find the "Save Configuration" button text
      final saveButton = find.text('Save Configuration');
      expect(saveButton, findsOneWidget);

      await tester.tap(saveButton);
      await tester.pump(); // Trigger snackbar start
      await tester.pump(const Duration(milliseconds: 100)); // Advance animation

      // Verify snackbar visibility
      expect(find.text('Settings applied successfully.'), findsOneWidget);
    });
  });
}
