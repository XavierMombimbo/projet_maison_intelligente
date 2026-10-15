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

const _session = StoredSession(
  baseUrl: 'https://maison.example.com',
  deviceId: 'phone',
  deviceName: 'Phone',
  identifier: 'owner',
  accessToken: 'access',
  refreshToken: 'refresh',
  sessionId: 'session',
);
const _house = MobileHouse(
  id: 1,
  name: 'Maison',
  timezone: 'Africa/Kinshasa',
  role: 'owner',
);
const _camera = MobileCamera(
  id: 'camera-id',
  name: 'Camera',
  houseName: 'Maison',
  active: true,
);
Map<String, dynamic> _schedule({bool editable = true}) => {
  'timezone': 'Africa/Kinshasa',
  'can_edit': editable,
  'active': true,
  'reason': 'Planning quotidien',
  'daily_start': '20:00',
  'daily_end': '06:00',
  'override': null,
  'windows': [],
  'exceptions': [],
};
Map<String, dynamic> _preferences() => {
  'timezone': 'Africa/Kinshasa',
  'enabled': true,
  'people': true,
  'objects_enabled': true,
  'urgent_during_quiet': false,
  'quiet_start': null,
  'quiet_end': null,
};

AppController _controller(
  Future<http.Response> Function(http.Request) handler,
) {
  final store = MemorySessionStore(session: _session);
  return AppController(
    api: HttpMobileApi(store: store, client: MockClient(handler)),
    store: store,
  );
}

http.Response _json(Object value, [int status = 200]) => http.Response(
  jsonEncode(value),
  status,
  headers: {'content-type': 'application/json'},
);

void main() {
  test(
    'settings transport preserves typed booleans and authenticated paths',
    () async {
      final api = HttpMobileApi(
        store: MemorySessionStore(session: _session),
        client: MockClient((request) async {
          expect(request.headers['authorization'], 'Bearer access');
          expect(request.url.path, '/api/v1/houses/1/members/');
          if (request.method == 'POST') {
            expect(
              jsonDecode(request.body)['access'][0]['peut_controler'],
              false,
            );
          }
          return _json({'members': []});
        }),
      );
      expect(await api.loadSettings('/api/v1/houses/1/members/'), {
        'members': [],
      });
      await api.saveSettings('/api/v1/houses/1/members/', {
        'action': 'update',
        'id': 2,
        'access': [
          {'camera_id': 'id', 'peut_voir': true, 'peut_controler': false},
        ],
      });
    },
  );

  for (final size in [const Size(320, 720), const Size(812, 375)]) {
    testWidgets('schedule save and responsive layout $size', (tester) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      var posts = 0;
      final controller = _controller((request) async {
        if (request.method == 'POST') {
          posts++;
          final body = jsonDecode(request.body);
          expect(body['action'], 'daily');
          expect(body['heure_activation'], '20:00');
          expect(body['heure_arret'], '06:00');
        }
        return _json(_schedule());
      });
      addTearDown(controller.dispose);
      await tester.pumpWidget(
        MaterialApp(
          home: HouseScheduleScreen(controller: controller, house: _house),
        ),
      );
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('Enregistrer les horaires'));
      await tester.tap(find.text('Enregistrer les horaires'));
      await tester.pumpAndSettle();
      expect(posts, 1);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('schedule member is read only', (tester) async {
    final controller = _controller(
      (_) async => _json(_schedule(editable: false)),
    );
    addTearDown(controller.dispose);
    await tester.pumpWidget(
      MaterialApp(
        home: HouseScheduleScreen(controller: controller, house: _house),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Enregistrer les horaires'), findsNothing);
    expect(find.text('Appliquer'), findsNothing);
    expect(find.byTooltip('Ajouter'), findsNothing);
  });

  testWidgets('notification validation failure keeps toggles and user input', (
    tester,
  ) async {
    var posts = 0;
    final controller = _controller((request) async {
      if (request.method == 'POST') {
        posts++;
        expect(jsonDecode(request.body)['enabled'], false);
        expect(jsonDecode(request.body)['lock_screen'], 'secret');
        return _json({'detail': 'Refus serveur.'}, 400);
      }
      return _json(_preferences());
    });
    addTearDown(controller.dispose);
    await tester.pumpWidget(
      MaterialApp(
        home: CameraPreferencesScreen(controller: controller, camera: _camera),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Recevoir les notifications'));
    await tester.pumpAndSettle();
    await tester.tap(find.byType(DropdownButtonFormField<String>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Masquer la notification').last);
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Enregistrer'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Enregistrer'));
    await tester.pumpAndSettle();
    expect(posts, 1);
    await tester.drag(find.byType(ListView), const Offset(0, 700));
    await tester.pumpAndSettle();
    expect(find.text('Refus serveur.'), findsOneWidget);
    expect(
      tester.widget<SwitchListTile>(find.byType(SwitchListTile).first).value,
      false,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('member removal requires confirmation', (tester) async {
    var posts = 0;
    final controller = _controller((request) async {
      if (request.method == 'POST') posts++;
      return _json({
        'cameras': [],
        'members': [
          {
            'id': 1,
            'username': 'owner',
            'role': 'owner',
            'status': 'accepted',
            'is_owner': true,
            'access': [],
          },
          {
            'id': 2,
            'username': 'guest',
            'role': 'guest',
            'status': 'pending',
            'is_owner': false,
            'access': [],
          },
        ],
      });
    });
    addTearDown(controller.dispose);
    await tester.pumpWidget(
      MaterialApp(
        home: HouseMembersScreen(controller: controller, house: _house),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byTooltip('Retirer le membre'), findsOneWidget);
    await tester.tap(find.byTooltip('Retirer le membre'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Annuler'));
    await tester.pumpAndSettle();
    expect(posts, 0);
  });

  testWidgets(
    'member invitation has no owner role and keeps account on error',
    (tester) async {
      var posts = 0;
      final controller = _controller((request) async {
        posts++;
        final body = jsonDecode(request.body);
        expect(body['role'], 'guest');
        expect(body['action'], 'invite');
        expect(body['username'], 'existing-user');
        return _json({'detail': 'Compte introuvable.'}, 400);
      });
      addTearDown(controller.dispose);
      await tester.pumpWidget(
        MaterialApp(
          home: MemberEditScreen(
            controller: controller,
            path: '/api/v1/houses/1/members/',
            cameras: const [],
          ),
        ),
      );
      await tester.tap(find.text("Envoyer l'invitation"));
      await tester.pumpAndSettle();
      expect(posts, 0);
      expect(find.text('Compte requis.'), findsOneWidget);
      await tester.enterText(find.byType(TextFormField), 'existing-user');
      await tester.tap(find.text("Envoyer l'invitation"));
      await tester.pumpAndSettle();
      expect(posts, 1);
      expect(find.text('existing-user'), findsOneWidget);
      expect(find.text('Compte introuvable.'), findsOneWidget);
    },
  );

  testWidgets('invitations can be loaded and refusal cancelled', (
    tester,
  ) async {
    var posts = 0;
    final controller = _controller((request) async {
      if (request.method == 'POST') posts++;
      return _json({
        'invitations': [
          {
            'id': 3,
            'role': 'family',
            'maison__nom': 'Maison invitee',
            'maison__proprietaire__username': 'owner',
          },
        ],
      });
    });
    addTearDown(controller.dispose);
    await tester.pumpWidget(
      MaterialApp(home: InvitationsScreen(controller: controller)),
    );
    await tester.pumpAndSettle();
    expect(find.text('Maison invitee'), findsOneWidget);
    await tester.tap(find.text('Refuser'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Annuler'));
    await tester.pumpAndSettle();
    expect(posts, 0);
  });
}
