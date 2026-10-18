import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:sentinelle_mobile/core/auth_models.dart';
import 'package:sentinelle_mobile/core/mobile_api.dart';

import 'test_support.dart';

void main() {
  group('HttpMobileApi', () {
    test(
      'le lien profond charge uniquement le detail avec la session courante',
      () async {
        final store = MemorySessionStore(
          session: const StoredSession(
            baseUrl: 'https://maison.example.com',
            deviceId: 'phone',
            deviceName: 'Phone',
            identifier: 'owner',
            accessToken: 'access-1',
            refreshToken: 'refresh-1',
            sessionId: 'session-1',
          ),
        );
        final api = HttpMobileApi(
          store: store,
          client: MockClient((request) async {
            expect(request.method, 'GET');
            expect(request.url.path, '/api/v1/events/event-1/');
            expect(request.headers['authorization'], 'Bearer access-1');
            return _json({
              'id': 'event-1',
              'camera_name': 'Entree',
              'can_control': false,
            });
          }),
        );
        final event = await api.loadEvent('event-1');
        expect(event.id, 'event-1');
        expect(event.canControl, isFalse);
      },
    );
    test(
      'creation et modification de maison utilisent la session authentifiee',
      () async {
        final store = MemorySessionStore(
          session: const StoredSession(
            baseUrl: 'https://maison.example.com',
            deviceId: 'phone',
            deviceName: 'Phone',
            identifier: 'owner',
            accessToken: 'access-1',
            refreshToken: 'refresh-1',
            sessionId: 'session-1',
          ),
        );
        final paths = <String>[];
        final api = HttpMobileApi(
          store: store,
          client: MockClient((request) async {
            expect(request.method, 'POST');
            expect(request.headers['authorization'], 'Bearer access-1');
            paths.add(request.url.path);
            final body = jsonDecode(request.body) as Map<String, dynamic>;
            expect(body['nom'], 'Maison');
            expect(body.containsKey('proprietaire'), isFalse);
            return _json({
              'id': 12,
              ...body,
              'role': 'owner',
            }, paths.length == 1 ? 201 : 200);
          }),
        );
        final created = await api.saveHouse(
          name: ' Maison ',
          timezone: 'Africa/Kinshasa',
        );
        expect(created.id, 12);
        await api.saveHouse(
          id: created.id,
          name: 'Maison',
          timezone: 'Africa/Lubumbashi',
        );
        expect(paths, ['/api/v1/houses/', '/api/v1/houses/12/']);
      },
    );
    test(
      'MFA enregistre les jetons puis charge les données filtrées',
      () async {
        final store = MemorySessionStore();
        final client = MockClient((request) async {
          switch (request.url.path) {
            case '/api/v1/auth/login/':
              final body = jsonDecode(request.body) as Map<String, dynamic>;
              expect(body['password'], 'secret');
              return _json({
                'challenge': 'challenge-1',
                'email': 'x***@example.com',
                'email_sent': true,
              }, 202);
            case '/api/v1/auth/mfa/verify/':
              return _json({
                'access_token': 'access-1',
                'refresh_token': 'refresh-1',
                'session_id': 'session-1',
              });
            case '/api/v1/me/':
              expect(request.headers['authorization'], 'Bearer access-1');
              return _json({'username': 'xavier', 'email': 'x@example.com'});
            case '/api/v1/houses/':
              return _json({'count': 1, 'results': []});
            case '/api/v1/cameras/':
              return _json({
                'count': 15,
                'results': [
                  {
                    'surveillance_active': true,
                    'surveillance_appliquee': false,
                    'surveillance_appliquee_le': '2026-09-28T12:00:00Z',
                  },
                  {'surveillance_active': false},
                ],
              });
            case '/api/v1/events/':
              return _json({
                'count': 145,
                'results': [
                  {
                    'id': 'event-1',
                    'camera_name': 'Entrée',
                    'type': 'line_crossing',
                    'priorite_alerte': 50,
                    'alert_priority_label': 'Normale',
                    'horodatage_observation': '2026-09-27T10:00:00Z',
                    'confiance_ia': 0.91,
                    'notification_supprimee': true,
                    'raison_priorite':
                        'Profil volontaire reconnu ; présence conservée sans notification.',
                  },
                ],
              });
            default:
              return _json({'detail': 'Introuvable'}, 404);
          }
        });
        final api = HttpMobileApi(client: client, store: store);

        final challenge = await api.login(
          baseUrl: 'https://maison.example.com/',
          identifier: 'xavier',
          password: 'secret',
          deviceId: 'device-test',
          deviceName: 'Téléphone de test',
        );
        final summary = await api.verifyMfa(challenge, '123456');

        expect(challenge.baseUrl, 'https://maison.example.com');
        expect(summary.houseCount, 1);
        expect(summary.cameraCount, 15);
        expect(summary.eventCount, 145);
        expect(summary.activeCameraCount, 1);
        expect(summary.cameras.first.appliedActive, isFalse);
        expect(summary.cameras.first.appliedAt, isNotNull);
        expect(summary.recentEvents.single.cameraName, 'Entrée');
        expect(summary.recentEvents.single.priorityLevel, 50);
        expect(summary.recentEvents.single.isKnownPresence, isTrue);
        expect(store.session?.refreshToken, 'refresh-1');
      },
    );

    test('un jeton expiré déclenche une seule rotation concurrente', () async {
      final store = MemorySessionStore(
        session: const StoredSession(
          baseUrl: 'https://maison.example.com',
          deviceId: 'device-test',
          deviceName: 'Téléphone de test',
          identifier: 'xavier',
          accessToken: 'access-old',
          refreshToken: 'refresh-old',
          sessionId: 'session-1',
        ),
      );
      var refreshCount = 0;
      final client = MockClient((request) async {
        if (request.url.path == '/api/v1/auth/refresh/') {
          refreshCount += 1;
          await Future<void>.delayed(const Duration(milliseconds: 15));
          return _json({
            'access_token': 'access-new',
            'refresh_token': 'refresh-new',
            'session_id': 'session-1',
          });
        }
        if (request.headers['authorization'] == 'Bearer access-old') {
          return _json({'detail': 'Jeton expiré.'}, 401);
        }
        expect(request.headers['authorization'], 'Bearer access-new');
        return switch (request.url.path) {
          '/api/v1/me/' => _json({
            'username': 'xavier',
            'email': 'x@example.com',
          }),
          '/api/v1/houses/' => _json({'count': 1, 'results': []}),
          '/api/v1/cameras/' => _json({'count': 15, 'results': []}),
          '/api/v1/events/' => _json({'count': 145, 'results': []}),
          _ => _json({'detail': 'Introuvable'}, 404),
        };
      });
      final api = HttpMobileApi(client: client, store: store);

      final summary = await api.loadSummary();

      expect(summary.eventCount, 145);
      expect(refreshCount, 1);
      expect(store.session?.refreshToken, 'refresh-new');
    });

    test('charge les maisons et gère les sessions mobiles', () async {
      final store = MemorySessionStore(
        session: const StoredSession(
          baseUrl: 'https://maison.example.com',
          deviceId: 'device-test',
          deviceName: 'Téléphone de test',
          identifier: 'xavier',
          accessToken: 'access-1',
          refreshToken: 'refresh-1',
          sessionId: 'session-1',
        ),
      );
      var revoked = false;
      final client = MockClient((request) async {
        expect(request.headers['authorization'], 'Bearer access-1');
        return switch (request.url.path) {
          '/api/v1/houses/' => _json({
            'count': 1,
            'results': [
              {
                'id': 7,
                'nom': 'Maison X',
                'fuseau_horaire': 'Africa/Kinshasa',
                'role': 'owner',
              },
            ],
          }),
          '/api/v1/auth/sessions/' => http.Response(
            jsonEncode([
              {
                'id': 'session-1',
                'device_name': 'Téléphone de test',
                'current': true,
                'last_used_at': '2026-09-28T08:00:00Z',
                'revoked_at': null,
              },
            ]),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          ),
          '/api/v1/auth/sessions/session-2/revoke/' => (() {
            revoked = true;
            return http.Response('', 204);
          })(),
          _ => _json({'detail': 'Introuvable'}, 404),
        };
      });
      final api = HttpMobileApi(client: client, store: store);

      final houses = await api.loadHouses();
      final sessions = await api.loadSessions();
      await api.revokeSession('session-2');

      expect(houses.single.name, 'Maison X');
      expect(houses.single.role, 'owner');
      expect(sessions.single.current, isTrue);
      expect(sessions.single.deviceName, 'Téléphone de test');
      expect(revoked, isTrue);
    });

    test('charge une page précise de l’historique caméra', () async {
      final store = MemorySessionStore(
        session: const StoredSession(
          baseUrl: 'https://maison.example.com',
          deviceId: 'device-test',
          deviceName: 'Téléphone de test',
          identifier: 'xavier',
          accessToken: 'access-1',
          refreshToken: 'refresh-1',
          sessionId: 'session-1',
        ),
      );
      final client = MockClient((request) async {
        expect(request.url.path, '/api/v1/events/');
        expect(request.url.queryParameters['camera'], 'camera-1');
        expect(request.url.queryParameters['page'], '2');
        expect(request.url.queryParameters['page_size'], '20');
        return _json({
          'count': 21,
          'next': null,
          'results': [
            {
              'id': 'event-21',
              'camera_id': 'camera-1',
              'camera_name': 'Entrée',
              'type': 'person_detected',
              'priorite_alerte': 50,
              'alert_priority_label': 'Importante',
              'horodatage': '2026-09-28T12:00:00Z',
            },
          ],
        });
      });
      final api = HttpMobileApi(client: client, store: store);

      final page = await api.loadEvents(cameraId: 'camera-1', page: 2);

      expect(page.page, 2);
      expect(page.totalCount, 21);
      expect(page.hasNext, isFalse);
      expect(page.items.single.id, 'event-21');
    });

    test('synchronise l’installation push et accuse la réception', () async {
      final store = MemorySessionStore(
        session: const StoredSession(
          baseUrl: 'https://maison.example.com',
          deviceId: 'device-test',
          deviceName: 'Téléphone de test',
          identifier: 'xavier',
          accessToken: 'access-1',
          refreshToken: 'refresh-1',
          sessionId: 'session-1',
        ),
      );
      final methods = <String>[];
      final client = MockClient((request) async {
        methods.add('${request.method} ${request.url.path}');
        expect(request.headers['authorization'], 'Bearer access-1');
        if (request.method == 'PUT') {
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['platform'], 'android');
          expect(body['permission'], 'granted');
          expect(body['token'], 'fcm-token');
          return _json({'registered': true, 'active': true});
        }
        return http.Response('', 204);
      });
      final api = HttpMobileApi(client: client, store: store);

      await api.registerPushInstallation(
        platform: 'android',
        permission: 'granted',
        token: 'fcm-token',
      );
      await api.acknowledgePushDelivery('delivery-1');
      await api.removePushInstallation();

      expect(methods, [
        'PUT /api/v1/push/installation/',
        'POST /api/v1/push/deliveries/delivery-1/received/',
        'DELETE /api/v1/push/installation/',
      ]);
    });

    test(
      'la déconnexion efface les jetons même si le serveur est indisponible',
      () async {
        final store = MemorySessionStore(
          session: const StoredSession(
            baseUrl: 'https://maison.example.com',
            deviceId: 'device-test',
            deviceName: 'Téléphone de test',
            identifier: 'xavier',
            accessToken: 'access-1',
            refreshToken: 'refresh-1',
            sessionId: 'session-1',
          ),
        );
        final api = HttpMobileApi(
          client: MockClient(
            (_) async => throw http.ClientException('hors ligne'),
          ),
          store: store,
        );

        final revoked = await api.logout();

        expect(revoked, isFalse);
        expect(store.session, isNull);
      },
    );
  });
}

http.Response _json(Map<String, Object?> body, [int status = 200]) {
  return http.Response(
    jsonEncode(body),
    status,
    headers: {'content-type': 'application/json; charset=utf-8'},
  );
}
