import 'package:flutter_test/flutter_test.dart';
import 'package:hemovision/main.dart';

void main() {
  testWidgets('App smoke test', (WidgetTester tester) async {
    // Build our app and trigger a frame.
    await tester.pumpWidget(const OmniSightApp());

    // Verify that the splash screen text is present
    expect(find.text('OmniSight'), findsOneWidget);
    expect(find.text('ENGINE  v2.0'), findsOneWidget);
  });
}
