import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sentinelle_mobile/core/auth_models.dart';
import 'package:sentinelle_mobile/core/secure_session_store.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => FlutterSecureStorage.setMockInitialValues({}));

  test('uses the production URL without asking the user', () async {
    final store = SecureSessionStore();
    final defaults = await store.readDefaults();

    expect(defaults.baseUrl, 'https://sentinelle.smartxcongo.com');
    expect(defaults.deviceId, isNotEmpty);
  });

  test('ignores an old USB address and discards its session', () async {
    const storage = FlutterSecureStorage();
    final store = SecureSessionStore(storage: storage);
    await store.saveDefaults(
      const ConnectionDefaults(
        baseUrl: 'http://127.0.0.1:8001',
        deviceId: 'phone-1',
        deviceName: 'Mon telephone',
        identifier: 'xavier',
      ),
    );
    await store.saveSession(
      const StoredSession(
        baseUrl: 'http://127.0.0.1:8001',
        deviceId: 'phone-1',
        deviceName: 'Mon telephone',
        identifier: 'xavier',
        accessToken: 'old-access',
        refreshToken: 'old-refresh',
        sessionId: 'old-session',
      ),
    );

    final defaults = await store.readDefaults();
    final session = await store.readSession();

    expect(defaults.baseUrl, 'https://sentinelle.smartxcongo.com');
    expect(defaults.deviceId, 'phone-1');
    expect(defaults.deviceName, 'Mon telephone');
    expect(defaults.identifier, 'xavier');
    expect(session, isNull);
    expect(await storage.read(key: 'session.access_token'), isNull);
    expect(await storage.read(key: 'session.refresh_token'), isNull);
  });
}
