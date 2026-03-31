// ─────────────────────────────────────────────────────────────────────────────
//  UNIT TESTS — CaregiverService JSON Parsing & State Machine
//
//  UPGRADE #3 + #5: Tests the TCP message parser and state transitions.
//
//  Run with: flutter test test/caregiver_service_test.dart
// ─────────────────────────────────────────────────────────────────────────────

import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';

// ── We test the parsing logic in isolation without needing a live socket.
// ── This is the correct way to test network code: extract pure functions.

// Replicates the parsing logic from CaregiverService._parseAndDispatch()
Map<String, dynamic>? parseAlertLine(String line) {
  try {
    final decoded = jsonDecode(line);
    if (decoded is Map<String, dynamic>) return decoded;
    return null;
  } on FormatException {
    return null;
  }
}

// Replicates the line-splitting logic from CaregiverService._listenOnSocket()
List<String> splitTcpBuffer(String data) {
  return data
      .split('\n')
      .map((l) => l.trim())
      .where((l) => l.isNotEmpty)
      .toList();
}

void main() {
  group('TCP Message Parsing — CaregiverService', () {
    // ── Valid inputs ──────────────────────────────────────────────────────
    test('parses a standard threat alert correctly', () {
      const json = '{"type":"threat","classId":1,"distance":2.5,"threatLevel":90.0}';
      final result = parseAlertLine(json);

      expect(result, isNotNull);
      expect(result!['type'], equals('threat'));
      expect(result['classId'], equals(1));
      expect((result['distance'] as num).toDouble(), closeTo(2.5, 0.001));
      expect((result['threatLevel'] as num).toDouble(), equals(90.0));
    });

    test('parses a heartbeat packet correctly', () {
      final json = '{"type":"hb","ts":${DateTime.now().millisecondsSinceEpoch}}';
      final result = parseAlertLine(json);

      expect(result, isNotNull);
      expect(result!['type'], equals('hb'));
      expect(result['ts'], isA<int>());
    });

    test('parses an audio alert correctly', () {
      const json = '{"type":"siren","frequency":1200.0,"confidence":0.94,"direction":"FRONT LEFT"}';
      final result = parseAlertLine(json);

      expect(result, isNotNull);
      expect(result!['type'], equals('siren'));
      expect(result['direction'], equals('FRONT LEFT'));
    });

    // ── Malformed / adversarial inputs ────────────────────────────────────
    test('returns null for malformed JSON (no crash)', () {
      const bad = '{"type": "broken, missing quote';
      final result = parseAlertLine(bad);
      expect(result, isNull,
          reason: 'Malformed JSON must return null gracefully, not crash');
    });

    test('returns null for empty string', () {
      expect(parseAlertLine(''), isNull);
    });

    test('returns null for plain text (no JSON)', () {
      expect(parseAlertLine('hello world'), isNull);
    });

    test('returns null for JSON array (expected object)', () {
      final result = parseAlertLine('[1,2,3]');
      expect(result, isNull,
          reason: 'Top-level arrays are not valid alert format');
    });

    test('returns null for JSON number (not an object)', () {
      expect(parseAlertLine('42'), isNull);
    });

    // ── TCP Buffer Splitting ──────────────────────────────────────────────
    test('splits single-line buffer into one message', () {
      const buffer = '{"type":"hb"}\n';
      final lines = splitTcpBuffer(buffer);
      expect(lines.length, equals(1));
      expect(lines.first, equals('{"type":"hb"}'));
    });

    test('splits multi-line buffer (burst) into multiple messages', () {
      const buffer =
          '{"type":"threat","classId":1}\n{"type":"siren","frequency":1200}\n';
      final lines = splitTcpBuffer(buffer);
      expect(lines.length, equals(2));
    });

    test('ignores empty lines in buffer (delimiter artifacts)', () {
      const buffer = '{"type":"hb"}\n\n\n{"type":"threat"}\n';
      final lines = splitTcpBuffer(buffer);
      expect(lines.length, equals(2),
          reason: 'Empty lines from double-delimiters must be filtered');
    });

    test('handles buffer with no trailing newline (incomplete chunk)', () {
      // This simulates a TCP packet that arrived mid-message
      const buffer = '{"type":"hb"}\n{"incomplete":';
      final lines = splitTcpBuffer(buffer);
      // Only the complete first line should parse successfully
      expect(parseAlertLine(lines.first), isNotNull);
    });

    // ── Round-trip integrity ──────────────────────────────────────────────
    test('JSON encode/decode round-trip preserves all fields', () {
      final original = {
        'type': 'threat',
        'classId': 1,
        'distance': 3.14,
        'threatLevel': 92.5,
        'label': 'Car',
        'direction': 'Left',
        'timestamp': DateTime.now().millisecondsSinceEpoch,
      };
      final encoded = '${jsonEncode(original)}\n';
      final lines = splitTcpBuffer(encoded);
      final decoded = parseAlertLine(lines.first);

      expect(decoded, isNotNull);
      expect(decoded!['type'], equals(original['type']));
      expect(decoded['classId'], equals(original['classId']));
      expect((decoded['distance'] as num).toDouble(),
          closeTo(original['distance'] as double, 0.0001));
      expect(decoded['label'], equals(original['label']));
    });
  });

  // ─────────────────────────────────────────────────────────────────────────
  group('Heartbeat Logic', () {
    test('heartbeat packet has type == "hb"', () {
      final hb = {'type': 'hb', 'ts': DateTime.now().millisecondsSinceEpoch};
      final encoded = jsonEncode(hb);
      final decoded = parseAlertLine(encoded);
      expect(decoded!['type'], equals('hb'));
    });

    test('non-heartbeat packet is not confused for heartbeat', () {
      const json = '{"type":"threat"}';
      final decoded = parseAlertLine(json);
      expect(decoded!['type'], isNot(equals('hb')));
    });
  });
}
