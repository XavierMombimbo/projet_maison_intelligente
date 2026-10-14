import 'package:flutter/foundation.dart';

import 'core/auth_models.dart';
import 'core/mobile_api.dart';
import 'core/push_coordinator.dart';
import 'core/session_store.dart';

enum AppPhase { booting, signedOut, awaitingMfa, signedIn, offline }

class AppController extends ChangeNotifier {
  AppController({
    required MobileApi api,
    required SessionStore store,
    PushCoordinator? push,
  }) : _api = api,
       _store = store,
       _push = push;

  final MobileApi _api;
  final SessionStore _store;
  final PushCoordinator? _push;
  MobileMonitoringApi? get monitoring =>
      _api is MobileMonitoringApi ? _api as MobileMonitoringApi : null;

  AppPhase phase = AppPhase.booting;
  ConnectionDefaults? defaults;
  LoginChallenge? challenge;
  AccountSummary? summary;
  String? errorMessage;
  bool busy = false;
  bool hasStoredSession = false;
  bool usingCachedData = false;
  DateTime? dataUpdatedAt;
  int selectedTab = 0;

  void selectTab(int index) {
    selectedTab = index;
    notifyListeners();
  }

  Future<void> initialize() async {
    defaults = await _store.readDefaults();
    hasStoredSession = await _store.readSession() != null;
    if (!hasStoredSession) {
      phase = AppPhase.signedOut;
      notifyListeners();
      return;
    }
    try {
      final restored = await _api.restoreSession();
      if (restored == null) {
        phase = AppPhase.signedOut;
      } else {
        await _acceptSummary(restored);
        phase = AppPhase.signedIn;
        await _push?.onAuthenticated();
      }
    } on NetworkFailure catch (error) {
      errorMessage = error.message;
      final cached = await _store.readCachedSummary();
      if (cached == null) {
        phase = AppPhase.offline;
      } else {
        summary = cached.summary;
        dataUpdatedAt = cached.savedAt;
        usingCachedData = true;
        phase = AppPhase.signedIn;
      }
    } on SessionExpiredFailure catch (error) {
      errorMessage = error.message;
      hasStoredSession = false;
      phase = AppPhase.signedOut;
    } on ApiFailure catch (error) {
      errorMessage = error.message;
      phase = AppPhase.signedOut;
    }
    notifyListeners();
  }

  Future<void> requestMfa({
    required String baseUrl,
    required String identifier,
    required String password,
    required String deviceName,
  }) async {
    final currentDefaults = defaults ?? await _store.readDefaults();
    if (baseUrl.trim().isEmpty) {
      errorMessage =
          'Cette application n’est pas encore reliée au serveur. '
          'Contactez la personne qui l’a installée.';
      notifyListeners();
      return;
    }
    final rememberedDefaults = ConnectionDefaults(
      baseUrl: baseUrl.trim().replaceFirst(RegExp(r'/+$'), ''),
      deviceId: currentDefaults.deviceId,
      deviceName: deviceName.trim(),
      identifier: identifier.trim(),
    );
    await _store.saveDefaults(rememberedDefaults);
    defaults = rememberedDefaults;
    await _run(() async {
      challenge = await _api.login(
        baseUrl: rememberedDefaults.baseUrl,
        identifier: rememberedDefaults.identifier,
        password: password,
        deviceId: rememberedDefaults.deviceId,
        deviceName: rememberedDefaults.deviceName,
      );
      phase = AppPhase.awaitingMfa;
    });
  }

  Future<void> verifyMfa(String code) async {
    final currentChallenge = challenge;
    if (currentChallenge == null) {
      phase = AppPhase.signedOut;
      notifyListeners();
      return;
    }
    await _run(() async {
      await _acceptSummary(await _api.verifyMfa(currentChallenge, code));
      defaults = await _store.readDefaults();
      hasStoredSession = true;
      phase = AppPhase.signedIn;
      await _push?.onAuthenticated();
    });
  }

  Future<void> refresh() async {
    await _run(() async {
      await _acceptSummary(await _api.loadSummary());
      hasStoredSession = true;
      phase = AppPhase.signedIn;
    }, offlineOnNetworkError: true);
  }

  Future<List<MobileHouse>> loadHouses() => _api.loadHouses();

  Future<RecentEvent> loadEvent(String eventId) async {
    final api = _api;
    if (phase != AppPhase.signedIn || api is! MobileEventDetailApi) {
      throw const ApiFailure('Connectez-vous pour consulter cette alerte.');
    }
    try {
      return await (api as MobileEventDetailApi).loadEvent(eventId);
    } on SessionExpiredFailure {
      hasStoredSession = false;
      phase = AppPhase.signedOut;
      notifyListeners();
      rethrow;
    }
  }

  MobileSettingsApi get settings {
    final api = _api;
    if (api is! MobileSettingsApi) {
      throw const ApiFailure('Reglages indisponibles.');
    }
    return api as MobileSettingsApi;
  }

  MobileCameraPairingApi get cameraPairing {
    final api = _api;
    if (api is! MobileCameraPairingApi) {
      throw const ApiFailure('Appairage indisponible.');
    }
    return api as MobileCameraPairingApi;
  }

  Future<void> saveCamera({
    String? id,
    required String name,
    int? houseId,
    String source = 'webcam',
    String url = '',
    String username = '',
    String password = '',
  }) {
    final api = _api;
    if (api is! MobileCameraManagementApi) {
      throw const ApiFailure('Gestion des cameras indisponible.');
    }
    return (api as MobileCameraManagementApi).saveCamera(
      id: id,
      name: name,
      houseId: houseId,
      source: source,
      url: url,
      username: username,
      password: password,
    );
  }

  Future<MobileHouse> saveHouse({
    int? id,
    required String name,
    required String timezone,
  }) {
    final api = _api;
    if (api is! MobileHouseManagementApi) {
      throw const ApiFailure('Gestion des maisons indisponible.');
    }
    return (api as MobileHouseManagementApi).saveHouse(
      id: id,
      name: name,
      timezone: timezone,
    );
  }

  Future<List<MobileSessionInfo>> loadSessions() => _api.loadSessions();

  Future<EventPage> loadEvents({String? cameraId, int page = 1}) {
    final api = monitoring;
    if (api == null) {
      throw const ApiFailure('Historique indisponible sur ce client.');
    }
    return api.loadEvents(cameraId: cameraId, page: page);
  }

  Future<void> revokeSession(String sessionId) => _api.revokeSession(sessionId);

  Future<bool> logout() async {
    busy = true;
    errorMessage = null;
    notifyListeners();
    await _push?.onLogout();
    final revoked = await _api.logout();
    challenge = null;
    summary = null;
    hasStoredSession = false;
    busy = false;
    phase = AppPhase.signedOut;
    notifyListeners();
    return revoked;
  }

  Future<void> forgetLocalSession() async {
    await _store.clearSession();
    challenge = null;
    summary = null;
    errorMessage = null;
    hasStoredSession = false;
    phase = AppPhase.signedOut;
    notifyListeners();
  }

  void backToLogin() {
    challenge = null;
    errorMessage = null;
    phase = AppPhase.signedOut;
    notifyListeners();
  }

  void clearError() {
    errorMessage = null;
    notifyListeners();
  }

  Future<void> _acceptSummary(AccountSummary value) async {
    final now = DateTime.now();
    summary = value;
    dataUpdatedAt = now;
    usingCachedData = false;
    await _store.saveCachedSummary(CachedSummary(summary: value, savedAt: now));
  }

  Future<void> _run(
    Future<void> Function() action, {
    bool offlineOnNetworkError = false,
  }) async {
    busy = true;
    errorMessage = null;
    notifyListeners();
    try {
      await action();
    } on NetworkFailure catch (error) {
      errorMessage = error.message;
      if (offlineOnNetworkError && hasStoredSession) {
        final cached = summary == null
            ? await _store.readCachedSummary()
            : null;
        if (cached != null) {
          summary = cached.summary;
          dataUpdatedAt = cached.savedAt;
        }
        if (summary == null) {
          phase = AppPhase.offline;
        } else {
          usingCachedData = true;
          phase = AppPhase.signedIn;
        }
      }
    } on SessionExpiredFailure catch (error) {
      errorMessage = error.message;
      hasStoredSession = false;
      phase = AppPhase.signedOut;
    } on ApiFailure catch (error) {
      errorMessage = error.message;
    } finally {
      busy = false;
      notifyListeners();
    }
  }
}
