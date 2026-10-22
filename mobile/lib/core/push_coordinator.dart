import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';

import 'firebase_config.dart';
import 'mobile_api.dart';
import 'notification_access.dart';

@pragma('vm:entry-point')
Future<void> sentinelleFirebaseBackgroundHandler(RemoteMessage message) async {
  if (!SentinelleFirebaseConfig.isConfigured) return;
  await Firebase.initializeApp(options: SentinelleFirebaseConfig.options);
}

class PushCoordinator {
  PushCoordinator({required MobilePushApi api}) : _api = api;

  final MobilePushApi _api;
  Future<void> Function()? onAlertReceived;
  Future<void> Function(String eventId)? onAlertOpened;
  StreamSubscription<String>? _tokenSubscription;
  StreamSubscription<RemoteMessage>? _foregroundSubscription;
  StreamSubscription<RemoteMessage>? _openedSubscription;
  bool _available = false;
  bool _authenticated = false;
  bool _started = false;
  RemoteMessage? _pendingOpened;
  static final _uuid = RegExp(r'^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$');

  Future<void> start() async {
    if (_started) return;
    _started = true;
    try {
      await NotificationAccess.listenForOpens(handleOpenedAlert);
      if (!_available) return;
      _foregroundSubscription = FirebaseMessaging.onMessage.listen(
        _onForegroundMessage,
        onError: _debugError,
      );
      _openedSubscription = FirebaseMessaging.onMessageOpenedApp.listen(
        (message) => handleOpenedAlert(message.data),
        onError: _debugError,
      );
      final initial = await FirebaseMessaging.instance.getInitialMessage();
      if (initial != null) await handleOpenedAlert(initial.data);
    } catch (error) {
      _debugError(error);
    }
  }

  Future<void> handleOpenedAlert(Map<String, dynamic> data) async {
    final eventId = data['event_id'];
    if (data['type'] != 'alert.created' ||
        eventId is! String ||
        !_uuid.hasMatch(eventId)) {
      return;
    }
    // The ID is only a navigation hint. The event is fetched with current credentials.
    await onAlertOpened?.call(eventId);
    final message = RemoteMessage(data: data);
    if (_authenticated) {
      await _acknowledge(message);
    } else {
      _pendingOpened = message;
    }
  }

  static Future<bool> configureFirebase() async {
    if (!SentinelleFirebaseConfig.isConfigured) return false;
    await Firebase.initializeApp(options: SentinelleFirebaseConfig.options);
    FirebaseMessaging.onBackgroundMessage(sentinelleFirebaseBackgroundHandler);
    return true;
  }

  void setAvailable(bool value) {
    _available = value;
  }

  Future<void> onAuthenticated() async {
    if (!_available || _authenticated) return;
    _authenticated = true;
    try {
      final pending = _pendingOpened;
      _pendingOpened = null;
      if (pending != null) await _acknowledge(pending);
      final messaging = FirebaseMessaging.instance;
      final settings = await messaging.requestPermission(
        alert: true,
        badge: true,
        sound: true,
      );
      final firebasePermission = _permissionName(settings.authorizationStatus);
      final permission = effectivePushPermission(
        firebasePermission: firebasePermission,
        isAndroid: !kIsWeb && defaultTargetPlatform == TargetPlatform.android,
        notificationsEnabled: await NotificationAccess.areEnabled(),
      );
      if (permission == 'denied') {
        await _api.registerPushInstallation(
          platform: _platform,
          permission: permission,
        );
        return;
      }
      if (permission == 'unknown') return;

      const configuredVapidKey = String.fromEnvironment(
        'FIREBASE_WEB_VAPID_KEY',
      );
      final token = await messaging.getToken(
        vapidKey: kIsWeb && configuredVapidKey.isNotEmpty
            ? configuredVapidKey
            : null,
      );
      if (token != null && token.isNotEmpty) {
        await _register(token, permission);
      }
      _tokenSubscription = messaging.onTokenRefresh.listen(
        (token) => _register(token, permission),
        onError: _debugError,
      );
    } catch (error) {
      _debugError(error);
    }
  }

  Future<void> onLogout() async {
    _pendingOpened = null;
    if (!_available) return;
    try {
      await _api.removePushInstallation();
    } catch (error) {
      _debugError(error);
    } finally {
      _authenticated = false;
      await _tokenSubscription?.cancel();
      _tokenSubscription = null;
    }
  }

  Future<void> dispose() {
    NotificationAccess.stopListening();
    return _cancelSubscriptions();
  }

  Future<void> _register(String token, String permission) =>
      _api.registerPushInstallation(
        platform: _platform,
        permission: permission,
        token: token,
      );

  Future<void> _acknowledge(RemoteMessage message) async {
    final deliveryId = message.data['delivery_id'];
    if (deliveryId is! String || !_uuid.hasMatch(deliveryId)) return;
    try {
      await _api.acknowledgePushDelivery(deliveryId);
    } catch (error) {
      _debugError(error);
    }
    try {
      await onAlertReceived?.call();
    } catch (error) {
      _debugError(error);
    }
  }

  Future<void> _onForegroundMessage(RemoteMessage message) async {
    if (!_authenticated) return;
    final deliveryId = message.data['delivery_id'];
    if (message.data['type'] != 'alert.created' ||
        deliveryId is! String ||
        deliveryId.isEmpty) {
      return;
    }
    try {
      await NotificationAccess.showAlert(
        deliveryId,
        eventId: message.data['event_id'] is String
            ? message.data['event_id'] as String
            : null,
        lockScreen: message.data['lock_screen'] is String
            ? message.data['lock_screen'] as String
            : 'private',
        personWeaponSuspicion: message.data['person_weapon_suspicion'] == 'true',
      );
    } catch (error) {
      _debugError(error);
    }
    await _acknowledge(message);
  }

  Future<void> _cancelSubscriptions() async {
    await Future.wait([
      if (_tokenSubscription != null) _tokenSubscription!.cancel(),
      if (_foregroundSubscription != null) _foregroundSubscription!.cancel(),
      if (_openedSubscription != null) _openedSubscription!.cancel(),
    ]);
    _tokenSubscription = null;
    _foregroundSubscription = null;
    _openedSubscription = null;
  }

  static String _permissionName(AuthorizationStatus status) => switch (status) {
    AuthorizationStatus.authorized => 'granted',
    AuthorizationStatus.provisional => 'provisional',
    AuthorizationStatus.denied => 'denied',
    AuthorizationStatus.deniedPermanently => 'denied',
    AuthorizationStatus.notDetermined => 'unknown',
  };

  static String get _platform {
    if (kIsWeb) return 'web';
    return switch (defaultTargetPlatform) {
      TargetPlatform.iOS || TargetPlatform.macOS => 'ios',
      _ => 'android',
    };
  }

  static void _debugError(Object error) {
    if (kDebugMode) debugPrint('Push indisponible: $error');
  }
}
