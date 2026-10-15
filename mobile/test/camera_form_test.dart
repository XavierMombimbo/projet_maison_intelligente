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

const session = StoredSession(baseUrl: 'https://maison.example.com', deviceId: 'phone',
  deviceName: 'Phone', identifier: 'owner', accessToken: 'access',
  refreshToken: 'refresh', sessionId: 'session');

void main() {
  test('camera creation and rename use authenticated POST with limited fields', () async {
    final bodies = <Map<String, dynamic>>[];
    final paths = <String>[];
    final api = HttpMobileApi(store: MemorySessionStore(session: session),
      client: MockClient((request) async {
        expect(request.method, 'POST');
        expect(request.headers['authorization'], 'Bearer access');
        paths.add(request.url.path);
        bodies.add(jsonDecode(request.body) as Map<String, dynamic>);
        return http.Response('{}', 201);
      }));
    await api.saveCamera(name: ' Camera ', houseId: 1, source: 'rtsp',
      url: 'rtsp://camera/live', username: 'user', password: ' secret ');
    await api.saveCamera(id: 'camera-id', name: ' Nouveau ', password: 'ignored');
    expect(paths, ['/api/v1/cameras/', '/api/v1/cameras/camera-id/']);
    expect(bodies.first['mot_de_passe_rtsp'], ' secret ');
    expect(bodies.first['maison'], 1);
    expect(bodies.last, {'nom': 'Nouveau'});
  });

  testWidgets('camera form validates name and preserves input on server error', (tester) async {
    var writes = 0;
    final store = MemorySessionStore(session: session);
    final api = HttpMobileApi(store: store, client: MockClient((request) async {
      if (request.method == 'GET') {
        return http.Response(jsonEncode({'results': [
          {'id': 1, 'nom': 'Ma maison', 'role': 'owner', 'fuseau_horaire': 'UTC'},
          {'id': 2, 'nom': 'Maison membre', 'role': 'member', 'fuseau_horaire': 'UTC'},
        ]}), 200);
      }
      writes++;
      expect(jsonDecode(request.body)['maison'], 1);
      return http.Response('{"nom":["Refus serveur."]}', 400);
    }));
    final controller = AppController(api: api, store: store);
    addTearDown(controller.dispose);
    await tester.pumpWidget(MaterialApp(home: CameraFormScreen(controller: controller)));
    await tester.pumpAndSettle();
    expect(find.text('Maison membre'), findsNothing);
    await tester.tap(find.text('Enregistrer'));
    await tester.pumpAndSettle();
    expect(find.text('Nom requis.'), findsOneWidget);
    expect(writes, 0);
    await tester.enterText(find.byType(TextFormField).first, 'Entree');
    await tester.tap(find.text('Enregistrer'));
    await tester.pumpAndSettle();
    expect(writes, 1);
    expect(find.text('Refus serveur.'), findsOneWidget);
    expect(find.text('Entree'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('successful rename returns to the previous screen', (tester) async {
    final store = MemorySessionStore(session: session);
    final api = HttpMobileApi(store: store,
      client: MockClient((_) async => http.Response('{}', 200)));
    final controller = AppController(api: api, store: store);
    addTearDown(controller.dispose);
    String? result;
    await tester.pumpWidget(MaterialApp(home: Builder(builder: (context) => Scaffold(
      body: TextButton(onPressed: () async {
        result = await Navigator.of(context).push<String>(MaterialPageRoute(
          builder: (_) => CameraFormScreen(controller: controller,
            camera: const MobileCamera(id: 'id', name: 'Avant', houseName: 'Maison',
              active: false, canControl: true)),
        ));
      }, child: const Text('Ouvrir')),
    ))));
    await tester.tap(find.text('Ouvrir'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextFormField), 'Apres');
    await tester.tap(find.text('Enregistrer'));
    await tester.pumpAndSettle();
    expect(result, 'Apres');
    expect(find.text('Ouvrir'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
