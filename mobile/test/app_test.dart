import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sentinelle_mobile/app.dart';
import 'package:sentinelle_mobile/core/auth_models.dart';
import 'package:sentinelle_mobile/core/mobile_api.dart';
import 'package:sentinelle_mobile/core/push_coordinator.dart';

import 'test_support.dart';

void main() {
  const eventId = '12345678-1234-1234-1234-123456789abc';
  testWidgets(
    'notification attend la connexion puis charge le detail autorise',
    (tester) async {
      final store = MemorySessionStore()
        ..defaults = const ConnectionDefaults(
          baseUrl: 'https://example.test',
          deviceId: 'test',
          deviceName: 'Test',
          identifier: '',
        );
      final api = _FakeApi();
      final push = _TestPush();
      await tester.pumpWidget(
        SentinelleApp(api: api, store: store, push: push),
      );
      await tester.pumpAndSettle();
      await push.handleOpenedAlert({
        'type': 'alert.created',
        'event_id': eventId,
      });
      await tester.pumpAndSettle();
      expect(api.detailRequests, isEmpty);
      await tester.enterText(
        find.byKey(const Key('identifierField')),
        'xavier',
      );
      await tester.enterText(find.byKey(const Key('passwordField')), 'secret');
      await tester.ensureVisible(find.byKey(const Key('loginButton')));
      await tester.tap(find.byKey(const Key('loginButton')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('mfaCodeField')), '123456');
      await tester.ensureVisible(find.byKey(const Key('verifyButton')));
      await tester.tap(find.byKey(const Key('verifyButton')));
      await tester.pumpAndSettle();
      expect(api.detailRequests, [eventId]);
      expect(find.byType(NotificationEventScreen), findsOneWidget);
      await push.handleOpenedAlert({
        'type': 'alert.created',
        'event_id': eventId,
      });
      await tester.pumpAndSettle();
      expect(api.detailRequests, [eventId]);
      final screen = tester.widget<NotificationEventScreen>(
        find.byType(NotificationEventScreen),
      );
      await screen.controller.logout();
      await tester.pumpAndSettle();
      expect(find.byType(NotificationEventScreen), findsNothing);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );

  testWidgets(
    'notification refusee sans detail cache et permet un nouvel essai',
    (tester) async {
      final store = MemorySessionStore(
        session: const StoredSession(
          baseUrl: 'https://example.test',
          deviceId: 'test',
          deviceName: 'Test',
          identifier: 'xavier',
          accessToken: 'test',
          refreshToken: 'test',
          sessionId: 'test',
        ),
      );
      final api = _FakeApi()
        ..detailError = const ApiFailure('Not found', statusCode: 404);
      final push = _TestPush();
      await tester.pumpWidget(
        SentinelleApp(api: api, store: store, push: push),
      );
      await tester.pumpAndSettle();
      await push.handleOpenedAlert({'type': 'unknown', 'event_id': eventId});
      await push.handleOpenedAlert({
        'type': 'alert.created',
        'event_id': '../../secret',
      });
      await push.onAlertReceived?.call();
      await tester.pumpAndSettle();
      expect(api.detailRequests, isEmpty);
      await push.handleOpenedAlert({
        'type': 'alert.created',
        'event_id': eventId,
      });
      await tester.pumpAndSettle();
      expect(find.text('Alerte indisponible ou acces retire.'), findsOneWidget);
      api.detailError = const NetworkFailure('Offline');
      await tester.tap(find.text('Reessayer'));
      await tester.pumpAndSettle();
      expect(
        find.text('Serveur inaccessible. Verifiez votre connexion.'),
        findsOneWidget,
      );
      api.detailError = null;
      await tester.tap(find.text('Reessayer'));
      await tester.pumpAndSettle();
      expect(api.detailRequests.length, 3);
      expect(find.text('Reessayer'), findsNothing);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );
  for (final size in [
    const Size(375, 812),
    const Size(320, 720),
    const Size(812, 375),
    const Size(1440, 900),
  ]) {
    testWidgets('navigation et rendu ${size.width}x${size.height}', (
      tester,
    ) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      const visualReview = bool.fromEnvironment('VISUAL_REVIEW');
      if (visualReview) {
        await tester.runAsync(() async {
          final font = FontLoader('Roboto');
          font.addFont(
            File(
              'C:/Windows/Fonts/arial.ttf',
            ).readAsBytes().then((bytes) => ByteData.sublistView(bytes)),
          );
          await font.load();
          final fallback = FontLoader('Ahem');
          fallback.addFont(
            File(
              'C:/Windows/Fonts/arial.ttf',
            ).readAsBytes().then((bytes) => ByteData.sublistView(bytes)),
          );
          await fallback.load();
          final serif = FontLoader('Georgia');
          serif.addFont(
            File(
              'C:/Windows/Fonts/georgiab.ttf',
            ).readAsBytes().then((bytes) => ByteData.sublistView(bytes)),
          );
          await serif.load();
          final icons = FontLoader('MaterialIcons');
          icons.addFont(
            File(
              'C:/APP_MEMOIRE/flutter/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf',
            ).readAsBytes().then((bytes) => ByteData.sublistView(bytes)),
          );
          await icons.load();
        });
      }
      final store = MemorySessionStore(
        session: const StoredSession(
          baseUrl: 'https://example.test',
          deviceId: 'test',
          deviceName: 'Test',
          identifier: 'xavier',
          accessToken: 'test',
          refreshToken: 'test',
          sessionId: 'test',
        ),
      );
      final api = _FakeApi();
      await tester.pumpWidget(SentinelleApp(api: api, store: store));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      if (visualReview && size.width == 375) {
        await expectLater(
          find.byType(SentinelleApp),
          matchesGoldenFile('../../output/mobile-ui/home.png'),
        );
      }
      await tester.tap(find.byType(NavigationDestination).at(1));
      await tester.pumpAndSettle();
      expect(find.text('Maison'), findsWidgets);
      await tester.tap(find.byType(NavigationDestination).at(2));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('Entrée').first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Entrée').first);
      await tester.pumpAndSettle();
      expect(find.text('Caméra · Entrée'), findsOneWidget);
      expect(tester.takeException(), isNull);
      if (visualReview && size.width == 375) {
        await expectLater(
          find.byType(SentinelleApp),
          matchesGoldenFile('../../output/mobile-ui/camera.png'),
        );
      }
      if (size.width == 375) {
        await tester.tap(find.byTooltip('Modifier la surveillance'));
        await tester.pumpAndSettle();
        expect(api.lastMonitoring, false);
      }
      await tester.pageBack();
      await tester.pumpAndSettle();
      await tester.tap(find.byType(NavigationDestination).at(3));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Franchissement de ligne').first);
      await tester.pumpAndSettle();
      expect(find.text('Détail de l’alerte'), findsOneWidget);
      expect(tester.takeException(), isNull);
      if (visualReview && size.width == 375) {
        await expectLater(
          find.byType(SentinelleApp),
          matchesGoldenFile('../../output/mobile-ui/alert.png'),
        );
      }
      if (size.width == 375) {
        await tester.scrollUntilVisible(
          find.text('Fausse alerte'),
          200,
          scrollable: find.byType(Scrollable).last,
        );
        await tester.pumpAndSettle();
        await tester.tap(find.text('Fausse alerte'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Confirmer'));
        await tester.pumpAndSettle();
        expect(api.lastDecision, 'false_alarm');
      }
      await tester.tap(find.byType(NavigationDestination).first);
      await tester.pumpAndSettle();
      expect(find.text('Bonjour xavier'), findsOneWidget);
      if (size.width == 375) {
        tester.platformDispatcher.platformBrightnessTestValue = Brightness.dark;
        tester.platformDispatcher.textScaleFactorTestValue = 2;
        addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
        addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
      }
    });
  }
  testWidgets('affiche une erreur réseau compréhensible à la connexion', (
    tester,
  ) async {
    final store = MemorySessionStore()
      ..defaults = const ConnectionDefaults(
        baseUrl: 'http://127.0.0.1:8001',
        deviceId: 'device-test',
        deviceName: 'Navigateur web',
        identifier: '',
      );
    await tester.pumpWidget(
      SentinelleApp(api: _FakeApi(networkError: true), store: store),
    );
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('identifierField')), 'xavier');
    await tester.enterText(find.byKey(const Key('passwordField')), 'secret');
    await tester.ensureVisible(find.byKey(const Key('loginButton')));
    await tester.tap(find.byKey(const Key('loginButton')));
    await tester.pumpAndSettle();

    expect(find.textContaining('connexion Internet'), findsOneWidget);
    expect(find.text('Se connecter'), findsOneWidget);
    expect(store.defaults.baseUrl, 'http://127.0.0.1:8001');
    expect(store.defaults.identifier, 'xavier');
  });

  testWidgets('masque les paramètres techniques de connexion', (tester) async {
    final store = MemorySessionStore()
      ..defaults = const ConnectionDefaults(
        baseUrl: 'http://127.0.0.1:8001',
        deviceId: 'device-test',
        deviceName: 'Navigateur web',
        identifier: 'xavier',
      );

    await tester.pumpWidget(SentinelleApp(api: _FakeApi(), store: store));
    await tester.pumpAndSettle();

    expect(find.text('Paramètres de connexion'), findsNothing);
    expect(find.text('Serveur et nom du téléphone'), findsNothing);
    expect(find.byKey(const Key('baseUrlField')), findsNothing);
    expect(find.byKey(const Key('deviceNameField')), findsNothing);
    final identifier = tester.widget<TextFormField>(
      find.byKey(const Key('identifierField')),
    );
    expect(identifier.controller?.text, 'xavier');
  });

  testWidgets('propose la création de compte et le mot de passe oublié', (
    tester,
  ) async {
    final openedPages = <Uri>[];
    final store = MemorySessionStore()
      ..defaults = const ConnectionDefaults(
        baseUrl: 'https://sentinelle.example',
        deviceId: 'device-test',
        deviceName: 'Navigateur web',
        identifier: '',
      );

    await tester.pumpWidget(
      SentinelleApp(
        api: _FakeApi(),
        store: store,
        openExternalPage: (uri) async {
          openedPages.add(uri);
          return true;
        },
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Mot de passe oublié ?'), findsOneWidget);
    expect(find.text('Créer un compte'), findsOneWidget);

    await tester.tap(find.byKey(const Key('forgotPasswordButton')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('createAccountButton')));
    await tester.pump();

    expect(openedPages, [
      Uri.parse('https://sentinelle.example/mot-de-passe-oublie/'),
      Uri.parse('https://sentinelle.example/inscription/'),
    ]);
  });

  testWidgets('signale une installation sans serveur configuré', (
    tester,
  ) async {
    await tester.pumpWidget(
      SentinelleApp(api: _FakeApi(), store: MemorySessionStore()),
    );
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('identifierField')), 'xavier');
    await tester.enterText(find.byKey(const Key('passwordField')), 'secret');
    await tester.tap(find.byKey(const Key('loginButton')));
    await tester.pumpAndSettle();

    expect(find.textContaining('pas encore reliée au serveur'), findsOneWidget);
    expect(find.text('Paramètres de connexion'), findsNothing);
  });

  testWidgets('affiche les données datées du cache hors ligne', (tester) async {
    final store = MemorySessionStore(
      session: const StoredSession(
        baseUrl: 'https://example.test',
        deviceId: 'test',
        deviceName: 'Test',
        identifier: 'xavier',
        accessToken: 'test',
        refreshToken: 'test',
        sessionId: 'test',
      ),
      cachedSummary: CachedSummary(
        summary: _FakeApi._summary,
        savedAt: DateTime.utc(2026, 9, 28, 12, 30),
      ),
    );

    await tester.pumpWidget(
      SentinelleApp(api: _FakeApi(networkError: true), store: store),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('Hors ligne · données du'), findsOneWidget);
    expect(find.text('Bonjour xavier'), findsOneWidget);
  });

  testWidgets('parcourt connexion, MFA et tableau de bord', (tester) async {
    final store = MemorySessionStore()
      ..defaults = const ConnectionDefaults(
        baseUrl: 'https://maison.example.com',
        deviceId: 'device-test',
        deviceName: 'Navigateur web',
        identifier: '',
      );
    final api = _FakeApi();
    await tester.pumpWidget(SentinelleApp(api: api, store: store));
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('identifierField')), 'xavier');
    await tester.enterText(find.byKey(const Key('passwordField')), 'secret');
    await tester.ensureVisible(find.byKey(const Key('loginButton')));
    await tester.tap(find.byKey(const Key('loginButton')));
    await tester.pumpAndSettle();

    expect(find.text('Entrez votre code MFA'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('mfaCodeField')), '123456');
    await tester.ensureVisible(find.byKey(const Key('verifyButton')));
    await tester.tap(find.byKey(const Key('verifyButton')));
    await tester.pumpAndSettle();

    expect(find.text('Bonjour xavier'), findsOneWidget);
    expect(find.text('145'), findsOneWidget);
    expect(find.text('Protection active'), findsOneWidget);
    await tester.tap(find.byType(NavigationDestination).at(3));
    await tester.pumpAndSettle();
    expect(find.text('Franchissement de ligne'), findsOneWidget);

    await tester.tap(find.text('Sécurité'));
    await tester.pumpAndSettle();
    expect(find.text('Appareils connectés'), findsOneWidget);
    await tester.tap(find.byTooltip('Révoquer Tablette'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Révoquer').last);
    await tester.pumpAndSettle();
    expect(api.lastRevokedSession, 'session-2');
    expect(find.byKey(const Key('logoutButton')), findsOneWidget);
  });

  testWidgets('actualise la liste après la réception d’une nouvelle alerte', (
    tester,
  ) async {
    final store = MemorySessionStore(
      session: const StoredSession(
        baseUrl: 'https://example.test',
        deviceId: 'test',
        deviceName: 'Test',
        identifier: 'xavier',
        accessToken: 'test',
        refreshToken: 'test',
        sessionId: 'test',
      ),
    );
    final api = _FakeApi();
    await tester.pumpWidget(
      SentinelleApp(
        api: api,
        store: store,
        refreshInterval: const Duration(seconds: 1),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byType(NavigationDestination).at(3));
    await tester.pumpAndSettle();

    expect(find.text('Cuisine'), findsNothing);
    api.addAlert();
    await tester.pump(const Duration(seconds: 1));
    await tester.pumpAndSettle();

    expect(find.textContaining('Cuisine'), findsOneWidget);
    expect(find.text('Objets détectés'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}

class _FakeApi implements MobileApi, MobileMonitoringApi, MobileEventDetailApi {
  _FakeApi({this.networkError = false});

  final bool networkError;
  bool? lastMonitoring;
  String? lastDecision;
  String? lastRevokedSession;
  AccountSummary summary = _summary;
  final detailRequests = <String>[];
  ApiFailure? detailError;
  @override
  Future<RecentEvent> loadEvent(String id) async {
    detailRequests.add(id);
    if (detailError != null) throw detailError!;
    return summary.recentEvents.first;
  }

  void addAlert() {
    summary = AccountSummary(
      username: summary.username,
      email: summary.email,
      houseCount: summary.houseCount,
      cameraCount: summary.cameraCount,
      eventCount: summary.eventCount + 1,
      activeCameraCount: summary.activeCameraCount,
      cameras: summary.cameras,
      recentEvents: [
        RecentEvent(
          id: 'event-2',
          cameraName: 'Cuisine',
          cameraId: 'camera-2',
          type: 'objects_detected',
          priorityLevel: 80,
          priorityLabel: 'Élevée',
          observedAt: DateTime.utc(2026, 10, 5, 6, 38),
          confidence: 0.88,
          grouped: false,
          canControl: true,
        ),
        ...summary.recentEvents,
      ],
    );
  }

  @override
  Future<Uint8List> loadCapture(String eventId) async =>
      throw const ApiFailure('Aucune capture');
  @override
  Future<EventPage> loadEvents({
    String? cameraId,
    int page = 1,
    int pageSize = 20,
  }) async => EventPage(
    items: summary.recentEvents
        .where((event) => cameraId == null || event.cameraId == cameraId)
        .toList(),
    page: page,
    totalCount: summary.recentEvents.length,
    hasNext: false,
  );
  @override
  Future<void> setMonitoring(String cameraId, bool active) async {
    lastMonitoring = active;
  }

  @override
  Future<RecentEvent> decideEvent(String eventId, String decision) async {
    lastDecision = decision;
    return RecentEvent(
      id: eventId,
      cameraName: 'Entrée',
      cameraId: 'camera-1',
      type: 'line_crossing',
      priorityLevel: 100,
      priorityLabel: 'Urgente',
      observedAt: null,
      confidence: 0.91,
      grouped: false,
      canControl: true,
      status: decision,
    );
  }

  static final _summary = AccountSummary(
    username: 'xavier',
    email: 'x@example.com',
    houseCount: 1,
    cameraCount: 15,
    eventCount: 145,
    activeCameraCount: 2,
    cameras: [
      MobileCamera(
        id: 'camera-1',
        name: 'Entrée',
        houseId: 1,
        houseName: 'Maison',
        active: true,
        canControl: true,
        appliedActive: true,
        appliedAt: DateTime.utc(2026, 9, 28, 12),
      ),
      MobileCamera(
        id: 'camera-2',
        name: 'Salon',
        houseId: 1,
        houseName: 'Maison',
        active: false,
      ),
    ],
    recentEvents: [
      RecentEvent(
        id: 'event-1',
        cameraName: 'Entrée',
        type: 'line_crossing',
        priorityLevel: 100,
        priorityLabel: 'Urgente',
        observedAt: null,
        confidence: 0.91,
        grouped: false,
        cameraId: 'camera-1',
        canControl: true,
      ),
    ],
  );

  @override
  Future<LoginChallenge> login({
    required String baseUrl,
    required String identifier,
    required String password,
    required String deviceId,
    required String deviceName,
  }) async {
    if (networkError) {
      throw const NetworkFailure(
        'Serveur inaccessible. Vérifiez votre connexion Internet et réessayez.',
      );
    }
    return LoginChallenge(
      challenge: 'challenge-1',
      maskedEmail: 'x***@example.com',
      emailSent: true,
      baseUrl: baseUrl,
      deviceId: deviceId,
      deviceName: deviceName,
      identifier: identifier,
    );
  }

  @override
  Future<bool> logout() async => true;

  @override
  Future<List<MobileHouse>> loadHouses() async => const [
    MobileHouse(
      id: 1,
      name: 'Maison',
      timezone: 'Africa/Kinshasa',
      role: 'owner',
    ),
  ];

  @override
  Future<List<MobileSessionInfo>> loadSessions() async => const [
    MobileSessionInfo(
      id: 'test',
      deviceName: 'Téléphone de test',
      current: true,
      revoked: false,
    ),
    MobileSessionInfo(
      id: 'session-2',
      deviceName: 'Tablette',
      current: false,
      revoked: false,
    ),
  ];

  @override
  Future<void> revokeSession(String sessionId) async {
    lastRevokedSession = sessionId;
  }

  @override
  Future<AccountSummary> loadSummary() async {
    if (networkError) throw const NetworkFailure('Serveur inaccessible.');
    return summary;
  }

  @override
  Future<AccountSummary?> restoreSession() async {
    if (networkError) throw const NetworkFailure('Serveur inaccessible.');
    return summary;
  }

  @override
  Future<AccountSummary> verifyMfa(
    LoginChallenge challenge,
    String code,
  ) async {
    expect(code, '123456');
    return summary;
  }
}

class _TestPush extends PushCoordinator {
  _TestPush() : super(api: _UnusedPushApi());
  @override
  Future<void> start() async {}
  @override
  Future<void> onAuthenticated() async {}
}

class _UnusedPushApi implements MobilePushApi {
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}
