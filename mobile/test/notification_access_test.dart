import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:sentinelle_mobile/core/notification_access.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('un toucher natif au demarrage transmet seulement les identifiants', () async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    const channel = MethodChannel('sentinelle_maison/notifications');
    final payload = {'type': 'alert.created', 'event_id': 'event', 'delivery_id': 'delivery'};
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(channel, (call) async {
      expect(call.method, 'takeOpenedAlert');
      return payload;
    });
    addTearDown(() {
      NotificationAccess.stopListening();
      debugDefaultTargetPlatformOverride = null;
      messenger.setMockMethodCallHandler(channel, null);
    });
    final opened = <Map<String, dynamic>>[];
    await NotificationAccess.listenForOpens((data) async { opened.add(data); });
    expect(opened, [payload]);
  });
  test('une alerte Android demande une notification native', () async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    const channel = MethodChannel('sentinelle_maison/notifications');
    final calls = <MethodCall>[];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
          calls.add(call);
          return null;
        });
    addTearDown(() {
      debugDefaultTargetPlatformOverride = null;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, null);
    });
    await NotificationAccess.showAlert('delivery-test');
    expect(calls.single.method, 'showAlert');
    expect(calls.single.arguments, {
      'delivery_id': 'delivery-test',
      'lock_screen': 'private',
    });
    await NotificationAccess.showAlert(
      'second',
      eventId: 'event-id',
      lockScreen: 'secret',
    );
    expect(calls.last.arguments, {
      'delivery_id': 'second',
      'event_id': 'event-id',
      'lock_screen': 'secret',
    });
    await NotificationAccess.showAlert('combined', personWeaponSuspicion: true);
    expect(calls.last.arguments['person_weapon_suspicion'], true);
    expect(calls.last.arguments['lock_screen'], 'private');
  });
  test('le blocage Android rend la permission push refusée', () {
    expect(
      effectivePushPermission(
        firebasePermission: 'granted',
        isAndroid: true,
        notificationsEnabled: false,
      ),
      'denied',
    );
  });

  test('les autres plateformes conservent la permission Firebase', () {
    expect(
      effectivePushPermission(
        firebasePermission: 'granted',
        isAndroid: false,
        notificationsEnabled: false,
      ),
      'granted',
    );
  });

  test('un état natif indisponible conserve la permission Firebase', () {
    expect(
      effectivePushPermission(
        firebasePermission: 'provisional',
        isAndroid: true,
        notificationsEnabled: null,
      ),
      'provisional',
    );
  });
}
