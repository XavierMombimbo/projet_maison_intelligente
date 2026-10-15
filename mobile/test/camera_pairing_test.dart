import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:sentinelle_mobile/app.dart';
import 'package:sentinelle_mobile/app_controller.dart';
import 'package:sentinelle_mobile/core/auth_models.dart';
import 'package:sentinelle_mobile/core/mobile_api.dart';
import 'test_support.dart';

const _session = StoredSession(baseUrl: 'https://maison.example.com', deviceId: 'phone',
  deviceName: 'Phone', identifier: 'owner', accessToken: 'access',
  refreshToken: 'refresh', sessionId: 'session');
const _camera = MobileCamera(id: 'camera-id', name: 'Entree', houseName: 'Maison',
  active: false, canControl: true, pairingStatus: 'unpaired');

void main() {
  test('pairing API uses session and does not cache code', () async {
    final store = MemorySessionStore(session: _session);
    final api = HttpMobileApi(store: store, client: MockClient((request) async {
      expect(request.headers['authorization'], 'Bearer access');
      if (request.method == 'POST') {
        expect(request.url.path, '/api/v1/cameras/camera-id/pairing-code/');
        return http.Response(jsonEncode({'code': '012345',
          'expires_at': DateTime.now().add(const Duration(minutes: 5)).toUtc().toIso8601String()}), 201);
      }
      expect(request.url.path, '/api/v1/cameras/camera-id/');
      return http.Response('{"statut_appairage":"unpaired"}', 200);
    }));
    expect((await api.createPairingCode('camera-id')).code, '012345');
    expect(await api.loadPairingStatus('camera-id'), 'unpaired');
    expect(store.cachedSummary, isNull);
    expect(store.session, same(_session));
    expect(MobileCamera.fromCache(_camera.toCache()).pairingStatus, 'unpaired');
  });

  for (final size in [const Size(320, 720), const Size(812, 375)]) {
    testWidgets('pairing code disappears after confirmation $size', (tester) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      var status = 'unpaired';
      var posts = 0;
      final store = MemorySessionStore(session: _session);
      final api = HttpMobileApi(store: store, client: MockClient((request) async {
        if (request.method == 'GET') {
          return http.Response(jsonEncode({'statut_appairage': status}), 200);
        }
        posts++;
        return http.Response(jsonEncode({'code': '012345',
          'expires_at': DateTime.now().add(const Duration(minutes: 5)).toUtc().toIso8601String()}), 201);
      }));
      final controller = AppController(api: api, store: store);
      addTearDown(controller.dispose);
      await tester.pumpWidget(MaterialApp(home: CameraPairingScreen(controller: controller, camera: _camera)));
      await tester.pumpAndSettle();
      expect(posts, 0);
      await tester.tap(find.text('Generer un code'));
      await tester.pumpAndSettle();
      expect(posts, 1);
      expect(find.text('012345'), findsOneWidget);
      status = 'paired';
      await tester.pump(const Duration(seconds: 5));
      await tester.pumpAndSettle();
      expect(find.text('012345'), findsNothing);
      expect(find.text('Camera appairee'), findsOneWidget);
      expect(find.text('Generer un code'), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    });
  }

  testWidgets('backgrounding clears code without automatic regeneration', (tester) async {
    var posts = 0;
    final store = MemorySessionStore(session: _session);
    final api = HttpMobileApi(store: store, client: MockClient((request) async {
      if (request.method == 'GET') return http.Response('{"statut_appairage":"unpaired"}', 200);
      posts++;
      return http.Response(jsonEncode({'code': '654321',
        'expires_at': DateTime.now().add(const Duration(minutes: 5)).toUtc().toIso8601String()}), 201);
    }));
    final controller = AppController(api: api, store: store);
    addTearDown(controller.dispose);
    await tester.pumpWidget(MaterialApp(home: CameraPairingScreen(controller: controller, camera: _camera)));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Generer un code'));
    await tester.pumpAndSettle();
    expect(find.text('654321'), findsOneWidget);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(find.text('654321'), findsNothing);
    expect(posts, 1);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('expired response never displays a code', (tester) async {
    final store = MemorySessionStore(session: _session);
    final api = HttpMobileApi(store: store, client: MockClient((request) async {
      if (request.method == 'GET') return http.Response('{"statut_appairage":"unpaired"}', 200);
      return http.Response('{"code":"000000","expires_at":"2000-01-01T00:00:00Z"}', 201);
    }));
    final controller = AppController(api: api, store: store);
    addTearDown(controller.dispose);
    await tester.pumpWidget(MaterialApp(home: CameraPairingScreen(controller: controller, camera: _camera)));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Generer un code'));
    await tester.pumpAndSettle();
    expect(find.text('000000'), findsNothing);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
