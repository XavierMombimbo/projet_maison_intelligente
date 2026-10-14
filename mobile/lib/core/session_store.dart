import 'auth_models.dart';

abstract interface class SessionStore {
  Future<ConnectionDefaults> readDefaults();

  Future<void> saveDefaults(ConnectionDefaults defaults);

  Future<StoredSession?> readSession();

  Future<void> saveSession(StoredSession session);

  Future<CachedSummary?> readCachedSummary();

  Future<void> saveCachedSummary(CachedSummary cached);

  Future<void> clearSession();
}
