import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:sentinelle_mobile/app.dart';
import 'package:sentinelle_mobile/app_controller.dart';
import 'package:sentinelle_mobile/core/auth_models.dart';
import 'package:sentinelle_mobile/core/mobile_api.dart';
import 'test_support.dart';

void main() {
  testWidgets('nom requis et saisie conservee apres refus serveur', (tester) async {
    var requests = 0;
    final store = MemorySessionStore(session: const StoredSession(
      baseUrl: 'https://maison.example.com', deviceId: 'phone', deviceName: 'Phone',
      identifier: 'owner', accessToken: 'access', refreshToken: 'refresh', sessionId: 'session',
    ));
    final api = HttpMobileApi(store: store, client: MockClient((request) async {
      requests++;
      return http.Response('{"fuseau_horaire":["Fuseau invalide."]}', 400,
        headers: {'content-type': 'application/json'});
    }));
    final controller = AppController(api: api, store: store);
    addTearDown(controller.dispose);
    await tester.pumpWidget(MaterialApp(home: HouseCreateScreen(controller: controller)));
    await tester.tap(find.text('Enregistrer'));
    await tester.pumpAndSettle();
    expect(find.text('Nom requis.'), findsOneWidget);
    expect(requests, 0);
    await tester.enterText(find.byType(TextFormField).first, 'Ma maison');
    await tester.tap(find.text('Enregistrer'));
    await tester.pumpAndSettle();
    expect(requests, 1);
    expect(find.text('Fuseau invalide.'), findsOneWidget);
    expect(find.text('Ma maison'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
