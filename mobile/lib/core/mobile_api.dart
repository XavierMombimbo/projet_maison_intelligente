import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import 'auth_models.dart';
import 'session_store.dart';

abstract interface class MobileApi {
  Future<LoginChallenge> login({
    required String baseUrl,
    required String identifier,
    required String password,
    required String deviceId,
    required String deviceName,
  });

  Future<AccountSummary> verifyMfa(LoginChallenge challenge, String code);

  Future<AccountSummary?> restoreSession();

  Future<AccountSummary> loadSummary();

  Future<List<MobileHouse>> loadHouses();

  Future<List<MobileSessionInfo>> loadSessions();

  Future<void> revokeSession(String sessionId);

  Future<bool> logout();
}

abstract interface class MobileMonitoringApi {
  Future<Uint8List> loadCapture(String eventId);
  Future<EventPage> loadEvents({
    String? cameraId,
    int page = 1,
    int pageSize = 20,
  });
  Future<void> setMonitoring(String cameraId, bool active);
  Future<RecentEvent> decideEvent(String eventId, String decision);
}

abstract interface class MobileEventDetailApi {
  Future<RecentEvent> loadEvent(String eventId);
}

abstract interface class MobileHouseManagementApi {
  Future<MobileHouse> saveHouse({
    int? id,
    required String name,
    required String timezone,
  });
}

abstract interface class MobileCameraManagementApi {
  Future<void> saveCamera({
    String? id,
    required String name,
    int? houseId,
    String source = 'webcam',
    String url = '',
    String username = '',
    String password = '',
  });
}

abstract interface class MobileCameraPairingApi {
  Future<CameraPairingCode> createPairingCode(String cameraId);
  Future<String> loadPairingStatus(String cameraId);
}

abstract interface class MobileSettingsApi {
  Future<Map<String, dynamic>> loadSettings(String path);
  Future<Map<String, dynamic>> saveSettings(
    String path,
    Map<String, Object?> body,
  );
}

abstract interface class MobilePushApi {
  Future<void> registerPushInstallation({
    required String platform,
    required String permission,
    String? token,
  });

  Future<void> removePushInstallation();

  Future<void> acknowledgePushDelivery(String deliveryId);
}

class HttpMobileApi
    implements
        MobileApi,
        MobileMonitoringApi,
        MobilePushApi,
        MobileHouseManagementApi,
        MobileCameraManagementApi,
        MobileCameraPairingApi,
        MobileSettingsApi,
        MobileEventDetailApi {
  HttpMobileApi({
    required http.Client client,
    required SessionStore store,
    this.timeout = const Duration(seconds: 15),
  }) : _client = client,
       _store = store;

  final http.Client _client;
  @override
  Future<RecentEvent> loadEvent(String eventId) async => _decodeRecentEvent(
    _decodeObject(
      await _authorizedGet('/api/v1/events/${Uri.encodeComponent(eventId)}/'),
    ),
  );
  final SessionStore _store;
  final Duration timeout;
  Future<StoredSession>? _refreshing;

  @override
  Future<LoginChallenge> login({
    required String baseUrl,
    required String identifier,
    required String password,
    required String deviceId,
    required String deviceName,
  }) async {
    final normalizedUrl = _normalizeBaseUrl(baseUrl);
    final response = await _postJson(normalizedUrl, '/api/v1/auth/login/', {
      'identifier': identifier.trim(),
      'password': password,
      'device_id': deviceId,
      'device_name': deviceName.trim(),
    });
    final data = _decodeObject(response);
    return LoginChallenge(
      challenge: data['challenge'] as String,
      maskedEmail: data['email'] as String? ?? 'votre adresse e-mail',
      emailSent: data['email_sent'] as bool? ?? false,
      baseUrl: normalizedUrl,
      deviceId: deviceId,
      deviceName: deviceName.trim(),
      identifier: identifier.trim(),
    );
  }

  @override
  Future<AccountSummary> verifyMfa(
    LoginChallenge challenge,
    String code,
  ) async {
    final response = await _postJson(
      challenge.baseUrl,
      '/api/v1/auth/mfa/verify/',
      {'challenge': challenge.challenge, 'code': code.trim()},
    );
    final data = _decodeObject(response);
    await _store.saveSession(
      StoredSession(
        baseUrl: challenge.baseUrl,
        deviceId: challenge.deviceId,
        deviceName: challenge.deviceName,
        identifier: challenge.identifier,
        accessToken: data['access_token'] as String,
        refreshToken: data['refresh_token'] as String,
        sessionId: data['session_id'] as String,
      ),
    );
    return loadSummary();
  }

  @override
  Future<AccountSummary?> restoreSession() async {
    if (await _store.readSession() == null) {
      return null;
    }
    return loadSummary();
  }

  @override
  Future<AccountSummary> loadSummary() async {
    final responses = await Future.wait([
      _authorizedGet('/api/v1/me/'),
      _authorizedGet('/api/v1/houses/?page_size=1'),
      _authorizedGet('/api/v1/cameras/?page_size=100'),
      _authorizedGet('/api/v1/events/?page_size=5'),
    ]);
    final me = _decodeObject(responses[0]);
    final cameras = _decodeObject(responses[2]);
    final events = _decodeObject(responses[3]);
    return AccountSummary(
      username: me['username'] as String? ?? '',
      email: me['email'] as String? ?? '',
      houseCount: _decodeCount(responses[1]),
      cameraCount: _decodeCount(responses[2]),
      eventCount: _decodeCount(responses[3]),
      activeCameraCount: _decodeResults(
        cameras,
      ).where((camera) => camera['surveillance_active'] == true).length,
      recentEvents: _decodeResults(events).map(_decodeRecentEvent).toList(),
      cameras: _decodeResults(cameras)
          .map(
            (data) => MobileCamera(
              id: data['id']?.toString() ?? '',
              name: data['nom'] as String? ?? 'Caméra',
              houseId: data['house_id'] as int?,
              houseName: data['house_name'] as String? ?? '',
              active: data['surveillance_active'] == true,
              lastSeen: DateTime.tryParse(
                data['derniere_connexion'] as String? ?? '',
              ),
              canControl: data['can_control'] == true,
              pairingStatus: data['statut_appairage'] as String? ?? 'unknown',
              captureEventId: data['latest_capture_event_id'] as String?,
              appliedActive: data['surveillance_appliquee'] as bool?,
              appliedAt: DateTime.tryParse(
                data['surveillance_appliquee_le'] as String? ?? '',
              ),
            ),
          )
          .toList(),
    );
  }

  @override
  Future<List<MobileHouse>> loadHouses() async {
    final data = _decodeObject(
      await _authorizedGet('/api/v1/houses/?page_size=100'),
    );
    return _decodeResults(data)
        .map(
          (house) => MobileHouse(
            id: house['id'] as int? ?? 0,
            name: house['nom'] as String? ?? 'Maison',
            timezone: house['fuseau_horaire'] as String? ?? 'UTC',
            role: house['role'] as String? ?? 'member',
          ),
        )
        .toList();
  }

  @override
  Future<CameraPairingCode> createPairingCode(String cameraId) async {
    final data = _decodeObject(
      await _authorizedJson('/api/v1/cameras/$cameraId/pairing-code/', {}),
    );
    final code = data['code'];
    final expires = DateTime.tryParse(data['expires_at'] as String? ?? '');
    if (code is! String ||
        !RegExp(r'^\d{6}$').hasMatch(code) ||
        expires == null) {
      throw const ApiFailure('Code d\'appairage indisponible.');
    }
    return CameraPairingCode(code: code, expiresAt: expires);
  }

  @override
  Future<String> loadPairingStatus(String cameraId) async {
    final data = _decodeObject(
      await _authorizedGet('/api/v1/cameras/$cameraId/'),
    );
    return data['statut_appairage'] as String? ?? 'unknown';
  }

  @override
  Future<Map<String, dynamic>> loadSettings(String path) async =>
      _decodeObject(await _authorizedGet(path));

  @override
  Future<Map<String, dynamic>> saveSettings(
    String path,
    Map<String, Object?> body,
  ) async => _decodeObject(await _authorizedJson(path, body));

  @override
  Future<MobileHouse> saveHouse({
    int? id,
    required String name,
    required String timezone,
  }) async {
    final data = _decodeObject(
      await _authorizedJson(
        id == null ? '/api/v1/houses/' : '/api/v1/houses/$id/',
        {'nom': name.trim(), 'fuseau_horaire': timezone},
      ),
    );
    return MobileHouse(
      id: data['id'] as int,
      name: data['nom'] as String,
      timezone: data['fuseau_horaire'] as String,
      role: data['role'] as String,
    );
  }

  @override
  Future<List<MobileSessionInfo>> loadSessions() async {
    final response = await _authorizedGet('/api/v1/auth/sessions/');
    final data = jsonDecode(utf8.decode(response.bodyBytes));
    if (data is! List) {
      throw const ApiFailure('Réponse inattendue du serveur.');
    }
    return data.whereType<Map<String, dynamic>>().map((session) {
      return MobileSessionInfo(
        id: session['id']?.toString() ?? '',
        deviceName: session['device_name'] as String? ?? 'Appareil mobile',
        current: session['current'] == true,
        revoked: session['revoked_at'] != null,
        lastUsedAt: DateTime.tryParse(session['last_used_at'] as String? ?? ''),
      );
    }).toList();
  }

  @override
  Future<void> saveCamera({
    String? id,
    required String name,
    int? houseId,
    String source = 'webcam',
    String url = '',
    String username = '',
    String password = '',
  }) async {
    await _authorizedJson(
      id == null ? '/api/v1/cameras/' : '/api/v1/cameras/$id/',
      {
        'nom': name.trim(),
        if (id == null) ...{
          'maison': houseId,
          'type_source': source,
          if (source == 'rtsp') ...{
            'adresse_rtsp': url.trim(),
            'utilisateur_rtsp': username.trim(),
            'mot_de_passe_rtsp': password,
          },
        },
      },
    );
  }

  @override
  Future<void> revokeSession(String sessionId) async {
    await _authorizedPost('/api/v1/auth/sessions/$sessionId/revoke/');
  }

  @override
  Future<void> registerPushInstallation({
    required String platform,
    required String permission,
    String? token,
  }) async {
    final body = <String, Object?>{
      'platform': platform,
      'permission': permission,
    };
    if (token != null) body['token'] = token;
    await _authorizedRequest(
      (uri, headers) =>
          _client.put(uri, headers: headers, body: jsonEncode(body)),
      '/api/v1/push/installation/',
    );
  }

  @override
  Future<void> removePushInstallation() async {
    await _authorizedRequest(
      (uri, headers) => _client.delete(uri, headers: headers),
      '/api/v1/push/installation/',
    );
  }

  @override
  Future<void> acknowledgePushDelivery(String deliveryId) async {
    await _authorizedPost('/api/v1/push/deliveries/$deliveryId/received/');
  }

  @override
  Future<Uint8List> loadCapture(String eventId) async =>
      (await _authorizedGet('/api/v1/events/$eventId/capture/')).bodyBytes;

  @override
  Future<EventPage> loadEvents({
    String? cameraId,
    int page = 1,
    int pageSize = 20,
  }) async {
    final queryParameters = {'page': '$page', 'page_size': '$pageSize'};
    if (cameraId != null) queryParameters['camera'] = cameraId;
    final query = Uri(queryParameters: queryParameters).query;
    final data = _decodeObject(await _authorizedGet('/api/v1/events/?$query'));
    return EventPage(
      items: _decodeResults(data).map(_decodeRecentEvent).toList(),
      page: page,
      totalCount: data['count'] as int? ?? 0,
      hasNext: data['next'] != null,
    );
  }

  @override
  Future<void> setMonitoring(String cameraId, bool active) async {
    await _authorizedJson('/api/v1/cameras/$cameraId/monitoring/', {
      'active': active,
    });
  }

  @override
  Future<RecentEvent> decideEvent(String eventId, String decision) async =>
      _decodeRecentEvent(
        _decodeObject(
          await _authorizedJson('/api/v1/events/$eventId/decision/', {
            'decision': decision,
          }),
        ),
      );

  Future<http.Response> _authorizedJson(
    String path,
    Map<String, Object?> body,
  ) => _authorizedRequest(
    (uri, headers) =>
        _client.post(uri, headers: headers, body: jsonEncode(body)),
    path,
  );

  @override
  Future<bool> logout() async {
    final session = await _store.readSession();
    if (session == null) {
      return true;
    }
    var remoteRevoked = false;
    try {
      final response = await _authorizedPost(
        '/api/v1/auth/sessions/${session.sessionId}/revoke/',
      );
      remoteRevoked = response.statusCode == HttpStatus.noContent;
    } on ApiFailure {
      remoteRevoked = false;
    } finally {
      await _store.clearSession();
    }
    return remoteRevoked;
  }

  Future<http.Response> _authorizedGet(String path) {
    return _authorizedRequest(
      (uri, headers) => _client.get(uri, headers: headers),
      path,
    );
  }

  Future<http.Response> _authorizedPost(String path) {
    return _authorizedRequest(
      (uri, headers) => _client.post(uri, headers: headers),
      path,
    );
  }

  Future<http.Response> _authorizedRequest(
    Future<http.Response> Function(Uri uri, Map<String, String> headers) send,
    String path,
  ) async {
    var session = await _store.readSession();
    if (session == null) {
      throw const SessionExpiredFailure();
    }
    var response = await _sendNetwork(
      () => send(
        Uri.parse('${session!.baseUrl}$path'),
        _headers(accessToken: session.accessToken),
      ),
    );
    if (response.statusCode == HttpStatus.unauthorized) {
      session = await _sessionAfterUnauthorized(session);
      response = await _sendNetwork(
        () => send(
          Uri.parse('${session!.baseUrl}$path'),
          _headers(accessToken: session.accessToken),
        ),
      );
    }
    _throwForResponse(response);
    return response;
  }

  Future<StoredSession> _sessionAfterUnauthorized(
    StoredSession rejectedSession,
  ) async {
    final latest = await _store.readSession();
    if (latest != null && latest.refreshToken != rejectedSession.refreshToken) {
      return latest;
    }
    final activeRefresh = _refreshing;
    if (activeRefresh != null) {
      return activeRefresh;
    }
    final refresh = _refresh(rejectedSession);
    _refreshing = refresh;
    try {
      return await refresh;
    } finally {
      if (identical(_refreshing, refresh)) {
        _refreshing = null;
      }
    }
  }

  Future<StoredSession> _refresh(StoredSession session) async {
    try {
      final response = await _postJson(
        session.baseUrl,
        '/api/v1/auth/refresh/',
        {'refresh_token': session.refreshToken},
      );
      final data = _decodeObject(response);
      final rotated = session.copyWith(
        accessToken: data['access_token'] as String,
        refreshToken: data['refresh_token'] as String,
        sessionId: data['session_id'] as String,
      );
      await _store.saveSession(rotated);
      return rotated;
    } on ApiFailure catch (error) {
      if (error.statusCode == HttpStatus.unauthorized) {
        await _store.clearSession();
        throw const SessionExpiredFailure();
      }
      rethrow;
    }
  }

  Future<http.Response> _postJson(
    String baseUrl,
    String path,
    Map<String, Object?> body,
  ) async {
    final response = await _sendNetwork(
      () => _client.post(
        Uri.parse('$baseUrl$path'),
        headers: _headers(),
        body: jsonEncode(body),
      ),
    );
    _throwForResponse(response);
    return response;
  }

  Future<http.Response> _sendNetwork(
    Future<http.Response> Function() action,
  ) async {
    try {
      return await action().timeout(timeout);
    } on TimeoutException {
      throw const NetworkFailure(
        'Le serveur met trop de temps à répondre. Vérifiez votre connexion Internet.',
      );
    } on SocketException {
      throw const NetworkFailure(
        'Serveur inaccessible. Vérifiez votre connexion Internet et réessayez.',
      );
    } on http.ClientException {
      throw const NetworkFailure(
        'Connexion impossible. Vérifiez votre connexion Internet et réessayez.',
      );
    }
  }

  void _throwForResponse(http.Response response) {
    if (response.statusCode >= 200 && response.statusCode < 300) {
      return;
    }
    var message = 'Le serveur a refusé la demande.';
    try {
      final data = jsonDecode(utf8.decode(response.bodyBytes));
      if (data is Map<String, dynamic>) {
        message =
            data['detail'] as String? ?? _firstValidationError(data) ?? message;
      }
    } on FormatException {
      // Keep the safe generic error instead of exposing an HTML response.
    }
    throw ApiFailure(message, statusCode: response.statusCode);
  }

  Map<String, dynamic> _decodeObject(http.Response response) {
    final data = jsonDecode(utf8.decode(response.bodyBytes));
    if (data is! Map<String, dynamic>) {
      throw const ApiFailure('Réponse inattendue du serveur.');
    }
    return data;
  }

  int _decodeCount(http.Response response) {
    final data = _decodeObject(response);
    return data['count'] as int? ?? 0;
  }

  List<Map<String, dynamic>> _decodeResults(Map<String, dynamic> data) {
    final results = data['results'];
    if (results is! List) return const [];
    return results.whereType<Map<String, dynamic>>().toList();
  }

  RecentEvent _decodeRecentEvent(Map<String, dynamic> data) {
    final confidence = data['confiance_ia'];
    final priority = data['priorite_alerte'];
    return RecentEvent(
      id: data['id']?.toString() ?? '',
      cameraName: data['camera_name'] as String? ?? 'Caméra',
      type: data['type'] as String? ?? 'evenement',
      priorityLevel: priority is num
          ? priority.toInt()
          : int.tryParse(priority?.toString() ?? '') ?? 0,
      priorityLabel: data['alert_priority_label'] as String? ?? 'Information',
      observedAt: DateTime.tryParse(
        data['horodatage_observation'] as String? ??
            data['horodatage'] as String? ??
            '',
      ),
      confidence: confidence is num ? confidence.toDouble() : null,
      grouped: data['notification_supprimee'] == true,
      cameraId: data['camera_id']?.toString() ?? '',
      status: data['statut'] as String? ?? 'new',
      hasCapture: data['has_capture'] == true,
      canControl: data['can_control'] == true,
      reason: data['raison_priorite'] as String? ?? '',
    );
  }

  String? _firstValidationError(Map<String, dynamic> data) {
    for (final value in data.values) {
      if (value is List && value.isNotEmpty) {
        return value.first.toString();
      }
      if (value is String) {
        return value;
      }
    }
    return null;
  }

  String _normalizeBaseUrl(String value) {
    final normalized = value.trim().replaceFirst(RegExp(r'/+$'), '');
    final uri = Uri.tryParse(normalized);
    if (uri == null ||
        !uri.hasAuthority ||
        (uri.scheme != 'http' && uri.scheme != 'https')) {
      throw const ApiFailure(
        'Saisissez une adresse complète, par exemple https://maison.exemple.fr.',
      );
    }
    return normalized;
  }

  Map<String, String> _headers({String? accessToken}) => {
    HttpHeaders.acceptHeader: 'application/json',
    HttpHeaders.contentTypeHeader: 'application/json; charset=utf-8',
    if (accessToken != null)
      HttpHeaders.authorizationHeader: 'Bearer $accessToken',
  };
}
