import 'package:shared_preferences/shared_preferences.dart';

class SettingsService {
  static const String _kIsMockMode = 'is_mock_mode';
  static const String _kHighContrast = 'high_contrast';
  static const String _kLargeText = 'large_text';
  static const String _kDangerSensitivity = 'danger_sensitivity';
  static const String _kMaxDistance = 'max_distance';
  static const String _kUniversalMode = 'universal_mode';

  final SharedPreferences _prefs;

  SettingsService(this._prefs);

  static Future<SettingsService> init() async {
    final prefs = await SharedPreferences.getInstance();
    return SettingsService(prefs);
  }

  bool get isMockMode => _prefs.getBool(_kIsMockMode) ?? true;
  bool get highContrast => _prefs.getBool(_kHighContrast) ?? false;
  bool get largeText => _prefs.getBool(_kLargeText) ?? false;
  double get dangerSensitivity => _prefs.getDouble(_kDangerSensitivity) ?? 75.0;
  double get maxDistance => _prefs.getDouble(_kMaxDistance) ?? 10.0;
  bool get universalMode => _prefs.getBool(_kUniversalMode) ?? false;

  Future<void> setMockMode(bool value) => _prefs.setBool(_kIsMockMode, value);
  Future<void> setHighContrast(bool value) => _prefs.setBool(_kHighContrast, value);
  Future<void> setLargeText(bool value) => _prefs.setBool(_kLargeText, value);
  Future<void> setDangerSensitivity(double value) => _prefs.setDouble(_kDangerSensitivity, value);
  Future<void> setMaxDistance(double value) => _prefs.setDouble(_kMaxDistance, value);
  Future<void> setUniversalMode(bool value) => _prefs.setBool(_kUniversalMode, value);
}
