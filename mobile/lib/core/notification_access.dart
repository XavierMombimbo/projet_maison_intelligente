import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

class NotificationAccess {
  static const _channel = MethodChannel('sentinelle_maison/notifications');

  static Future<void> showAlert(
    String deliveryId, {
    String? eventId,
    String lockScreen = 'private',
  }) async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return;
    await _channel.invokeMethod<void>('showAlert', {
      'delivery_id': deliveryId,
      'event_id': ?eventId,
      'lock_screen': lockScreen,
    });
  }

  static Future<void> listenForOpens(
    Future<void> Function(Map<String, dynamic>) onOpen,
  ) async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return;
    _channel.setMethodCallHandler((call) async {
      if (call.method == 'alertOpened' && call.arguments is Map) {
        await onOpen(Map<String, dynamic>.from(call.arguments as Map));
      }
    });
    try {
      final initial = await _channel.invokeMapMethod<String, dynamic>(
        'takeOpenedAlert',
      );
      if (initial != null) await onOpen(initial);
    } on MissingPluginException {
      // Older Android builds have no notification tap bridge.
    }
  }

  static void stopListening() => _channel.setMethodCallHandler(null);

  static Future<bool?> areEnabled() async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return null;
    try {
      return await _channel.invokeMethod<bool>('areNotificationsEnabled');
    } on MissingPluginException {
      return null;
    } on PlatformException {
      return null;
    }
  }
}

String effectivePushPermission({
  required String firebasePermission,
  required bool isAndroid,
  required bool? notificationsEnabled,
}) {
  if (isAndroid && notificationsEnabled == false) return 'denied';
  return firebasePermission;
}
