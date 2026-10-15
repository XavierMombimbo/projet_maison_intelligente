import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'auth_models.dart';
import 'session_store.dart';

class SecureSessionStore implements SessionStore {
  SecureSessionStore({FlutterSecureStorage? storage})
    : _storage = storage ?? const FlutterSecureStorage();

  static const _baseUrlKey = 'connection.base_url';
  static const _deviceIdKey = 'connection.device_id';
  static const _deviceNameKey = 'connection.device_name';
  static const _identifierKey = 'connection.identifier';
  static const _accessTokenKey = 'session.access_token';
  static const _refreshTokenKey = 'session.refresh_token';
  static const _sessionIdKey = 'session.id';
  static const _summaryCacheKey = 'cache.account_summary';
  static const _configuredBaseUrl = String.fromEnvironment(
    'SENTINELLE_API_BASE_URL',
  );
  static const _productionBaseUrl = 'https://sentinelle.smartxcongo.com';

  final FlutterSecureStorage _storage;

  @override
  Future<ConnectionDefaults> readDefaults() async {
    final values = await _storage.readAll();
    final deviceId = values[_deviceIdKey] ?? _newDeviceId();
    final savedBaseUrl = values[_baseUrlKey]?.trim() ?? '';
    final savedDeviceName = values[_deviceNameKey]?.trim() ?? '';
    if (values[_deviceIdKey] == null) {
      await _storage.write(key: _deviceIdKey, value: deviceId);
    }
    return ConnectionDefaults(
      baseUrl: _configuredBaseUrl.trim().isNotEmpty || !kIsWeb
          ? _defaultBaseUrl()
          : (savedBaseUrl.isEmpty ? _defaultBaseUrl() : savedBaseUrl),
      deviceId: deviceId,
      deviceName: savedDeviceName.isEmpty
          ? _defaultDeviceName()
          : savedDeviceName,
      identifier: values[_identifierKey] ?? '',
    );
  }

  @override
  Future<void> saveDefaults(ConnectionDefaults defaults) async {
    await Future.wait([
      _storage.write(key: _baseUrlKey, value: defaults.baseUrl),
      _storage.write(key: _deviceIdKey, value: defaults.deviceId),
      _storage.write(key: _deviceNameKey, value: defaults.deviceName),
      _storage.write(key: _identifierKey, value: defaults.identifier),
    ]);
  }

  @override
  Future<StoredSession?> readSession() async {
    final values = await _storage.readAll();
    final access = values[_accessTokenKey];
    final refresh = values[_refreshTokenKey];
    final sessionId = values[_sessionIdKey];
    final baseUrl = values[_baseUrlKey];
    final deviceId = values[_deviceIdKey];
    if ([
      access,
      refresh,
      sessionId,
      baseUrl,
      deviceId,
    ].any((value) => value == null || value.isEmpty)) {
      return null;
    }
    if ((_configuredBaseUrl.trim().isNotEmpty || !kIsWeb) &&
        baseUrl != _defaultBaseUrl()) {
      await clearSession();
      return null;
    }
    return StoredSession(
      baseUrl: baseUrl!,
      deviceId: deviceId!,
      deviceName: values[_deviceNameKey] ?? _defaultDeviceName(),
      identifier: values[_identifierKey] ?? '',
      accessToken: access!,
      refreshToken: refresh!,
      sessionId: sessionId!,
    );
  }

  @override
  Future<void> saveSession(StoredSession session) async {
    await Future.wait([
      _storage.write(key: _baseUrlKey, value: session.baseUrl),
      _storage.write(key: _deviceIdKey, value: session.deviceId),
      _storage.write(key: _deviceNameKey, value: session.deviceName),
      _storage.write(key: _identifierKey, value: session.identifier),
      _storage.write(key: _accessTokenKey, value: session.accessToken),
      _storage.write(key: _refreshTokenKey, value: session.refreshToken),
      _storage.write(key: _sessionIdKey, value: session.sessionId),
    ]);
  }

  @override
  Future<CachedSummary?> readCachedSummary() async {
    final raw = await _storage.read(key: _summaryCacheKey);
    if (raw == null || raw.isEmpty) return null;
    try {
      final data = jsonDecode(raw);
      if (data is! Map<String, dynamic>) return null;
      final savedAt = DateTime.tryParse(data['saved_at'] as String? ?? '');
      final summary = data['summary'];
      if (savedAt == null || summary is! Map<String, dynamic>) return null;
      return CachedSummary(
        summary: AccountSummary.fromCache(summary),
        savedAt: savedAt,
      );
    } on FormatException {
      return null;
    }
  }

  @override
  Future<void> saveCachedSummary(CachedSummary cached) => _storage.write(
    key: _summaryCacheKey,
    value: jsonEncode({
      'saved_at': cached.savedAt.toIso8601String(),
      'summary': cached.summary.toCache(),
    }),
  );

  @override
  Future<void> clearSession() async {
    await Future.wait([
      _storage.delete(key: _accessTokenKey),
      _storage.delete(key: _refreshTokenKey),
      _storage.delete(key: _sessionIdKey),
      _storage.delete(key: _summaryCacheKey),
    ]);
  }

  String _newDeviceId() {
    final random = Random.secure();
    final bytes = List<int>.generate(24, (_) => random.nextInt(256));
    return base64UrlEncode(bytes).replaceAll('=', '');
  }

  String _defaultBaseUrl() {
    final configured = _configuredBaseUrl.trim();
    if (configured.isNotEmpty) return configured;
    if (kIsWeb) {
      final uri = Uri.base;
      if (uri.host == '127.0.0.1' || uri.host == 'localhost') {
        return '${uri.scheme}://${uri.host}:8001';
      }
      return uri.origin;
    }
    return _productionBaseUrl;
  }

  String _defaultDeviceName() =>
      kIsWeb ? 'Navigateur web' : 'Téléphone Android';
}
