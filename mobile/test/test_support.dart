import 'package:sentinelle_mobile/core/auth_models.dart';
import 'package:sentinelle_mobile/core/session_store.dart';

class MemorySessionStore implements SessionStore {
  MemorySessionStore({this.session, this.cachedSummary});

  StoredSession? session;
  CachedSummary? cachedSummary;
  ConnectionDefaults defaults = const ConnectionDefaults(
    baseUrl: '',
    deviceId: 'device-test',
    deviceName: 'Téléphone de test',
    identifier: '',
  );

  @override
  Future<void> clearSession() async {
    session = null;
    cachedSummary = null;
  }

  @override
  Future<CachedSummary?> readCachedSummary() async => cachedSummary;

  @override
  Future<ConnectionDefaults> readDefaults() async {
    final current = session;
    if (current == null) return defaults;
    return ConnectionDefaults(
      baseUrl: current.baseUrl,
      deviceId: current.deviceId,
      deviceName: current.deviceName,
      identifier: current.identifier,
    );
  }

  @override
  Future<void> saveDefaults(ConnectionDefaults value) async {
    defaults = value;
  }

  @override
  Future<StoredSession?> readSession() async => session;

  @override
  Future<void> saveSession(StoredSession value) async {
    session = value;
  }

  @override
  Future<void> saveCachedSummary(CachedSummary value) async {
    cachedSummary = value;
  }
}
