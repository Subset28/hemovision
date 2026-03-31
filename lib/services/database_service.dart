import 'dart:async';
import 'package:path/path.dart';
import 'package:sqflite/sqflite.dart';
import 'package:flutter/foundation.dart' show kIsWeb;

// ─────────────────────────────────────────────────────────────────────────────
//  DATABASE SERVICE — Local-First Persistence
//
//  UPGRADE #6: Digital Equity & Remote Resilience.
//  This service ensures that alert history and telemetry logs are persisted
//  locally on the device. It requires ZERO internet or cloud connection.
//
//  Design choice: SQLite (sqflite)
//  Rationale: Transactional reliability for medical-grade data integrity.
// ─────────────────────────────────────────────────────────────────────────────

class DatabaseService {
  static final DatabaseService _instance = DatabaseService._internal();
  factory DatabaseService() => _instance;
  DatabaseService._internal();

  Database? _db;

  Future<Database?> get database async {
    if (kIsWeb) return null;
    if (_db != null) return _db!;
    _db = await _initDb();
    return _db;
  }

  Future<Database> _initDb() async {
    final path = join(await getDatabasesPath(), 'omnisight_v1.db');
    return await openDatabase(
      path,
      version: 1,
      onCreate: (db, version) async {
        // Table for alert history
        await db.execute('''
          CREATE TABLE alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT,
            direction TEXT,
            info TEXT,
            threatLevel REAL,
            timestamp INTEGER
          )
        ''');

        // Table for session telemetry
        await db.execute('''
          CREATE TABLE telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            frameCount INTEGER,
            uptime TEXT,
            fps REAL,
            timestamp INTEGER
          )
        ''');
      },
    );
  }

  // ── ALERTS ─────────────────────────────────────────────────────────────────

  Future<void> saveAlert(Map<String, dynamic> alert) async {
    if (kIsWeb) return;
    final db = await database;
    if (db == null) return;
    await db.insert('alerts', {
      'type': alert['type'],
      'direction': alert['direction'],
      'info': alert['info'],
      'threatLevel': alert['threatLevel'] ?? 0.0,
      'timestamp': DateTime.now().millisecondsSinceEpoch,
    });
  }

  Future<List<Map<String, dynamic>>> getLatestAlerts({int limit = 50}) async {
    if (kIsWeb) return [];
    final db = await database;
    if (db == null) return [];
    return await db.query('alerts', orderBy: 'timestamp DESC', limit: limit);
  }

  // ── TELEMETRY ──────────────────────────────────────────────────────────────

  Future<void> saveTelemetry(Map<String, dynamic> stats) async {
    if (kIsWeb) return;
    final db = await database;
    if (db == null) return;
    await db.insert('telemetry', {
      'frameCount': stats['frames'] ?? 0,
      'uptime': stats['uptime'] ?? '00:00:00',
      'fps': double.tryParse(stats['fps'] ?? '0.0') ?? 0.0,
      'timestamp': DateTime.now().millisecondsSinceEpoch,
    });
  }

  Future<void> clearAll() async {
    if (kIsWeb) return;
    final db = await database;
    if (db == null) return;
    await db.delete('alerts');
    await db.delete('telemetry');
  }

  Future<void> dispose() async {
    final db = _db;
    if (db != null) {
      await db.close();
      _db = null;
    }
  }
}
