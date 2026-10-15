class ConnectionDefaults {
  const ConnectionDefaults({
    required this.baseUrl,
    required this.deviceId,
    required this.deviceName,
    required this.identifier,
  });

  final String baseUrl;
  final String deviceId;
  final String deviceName;
  final String identifier;
}

class StoredSession {
  const StoredSession({
    required this.baseUrl,
    required this.deviceId,
    required this.deviceName,
    required this.identifier,
    required this.accessToken,
    required this.refreshToken,
    required this.sessionId,
  });

  final String baseUrl;
  final String deviceId;
  final String deviceName;
  final String identifier;
  final String accessToken;
  final String refreshToken;
  final String sessionId;

  StoredSession copyWith({
    String? accessToken,
    String? refreshToken,
    String? sessionId,
  }) {
    return StoredSession(
      baseUrl: baseUrl,
      deviceId: deviceId,
      deviceName: deviceName,
      identifier: identifier,
      accessToken: accessToken ?? this.accessToken,
      refreshToken: refreshToken ?? this.refreshToken,
      sessionId: sessionId ?? this.sessionId,
    );
  }
}

class LoginChallenge {
  const LoginChallenge({
    required this.challenge,
    required this.maskedEmail,
    required this.emailSent,
    required this.baseUrl,
    required this.deviceId,
    required this.deviceName,
    required this.identifier,
  });

  final String challenge;
  final String maskedEmail;
  final bool emailSent;
  final String baseUrl;
  final String deviceId;
  final String deviceName;
  final String identifier;
}

class RecentEvent {
  const RecentEvent({
    required this.id,
    required this.cameraName,
    required this.type,
    required this.priorityLevel,
    required this.priorityLabel,
    required this.observedAt,
    required this.confidence,
    required this.grouped,
    this.cameraId = '',
    this.status = 'new',
    this.hasCapture = false,
    this.canControl = false,
    this.reason = '',
  });

  final String id;
  final String cameraName;
  final String type;
  final int priorityLevel;
  final String priorityLabel;
  final DateTime? observedAt;
  final double? confidence;
  final bool grouped;
  final String cameraId;
  final String status;
  final bool hasCapture;
  final bool canControl;
  final String reason;

  Map<String, Object?> toCache() => {
    'id': id,
    'camera_name': cameraName,
    'type': type,
    'priority_level': priorityLevel,
    'priority_label': priorityLabel,
    'observed_at': observedAt?.toIso8601String(),
    'confidence': confidence,
    'grouped': grouped,
    'camera_id': cameraId,
    'status': status,
    'has_capture': hasCapture,
    'can_control': canControl,
    'reason': reason,
  };

  factory RecentEvent.fromCache(Map<String, dynamic> data) => RecentEvent(
    id: data['id'] as String? ?? '',
    cameraName: data['camera_name'] as String? ?? 'Caméra',
    type: data['type'] as String? ?? 'evenement',
    priorityLevel: data['priority_level'] as int? ?? 0,
    priorityLabel: data['priority_label'] as String? ?? 'Information',
    observedAt: DateTime.tryParse(data['observed_at'] as String? ?? ''),
    confidence: (data['confidence'] as num?)?.toDouble(),
    grouped: data['grouped'] == true,
    cameraId: data['camera_id'] as String? ?? '',
    status: data['status'] as String? ?? 'new',
    hasCapture: data['has_capture'] == true,
    canControl: data['can_control'] == true,
    reason: data['reason'] as String? ?? '',
  );
}

class EventPage {
  const EventPage({
    required this.items,
    required this.page,
    required this.totalCount,
    required this.hasNext,
  });

  final List<RecentEvent> items;
  final int page;
  final int totalCount;
  final bool hasNext;
}

class MobileCamera {
  const MobileCamera({
    required this.id,
    required this.name,
    required this.houseName,
    required this.active,
    this.houseId,
    this.lastSeen,
    this.canControl = false,
    this.captureEventId,
    this.appliedActive,
    this.appliedAt,
    this.pairingStatus = 'unknown',
  });
  final String id;
  final String name;
  final int? houseId;
  final String houseName;
  final bool active;
  final DateTime? lastSeen;
  final bool canControl;
  final String? captureEventId;
  final bool? appliedActive;
  final DateTime? appliedAt;
  final String pairingStatus;

  Map<String, Object?> toCache() => {
    'id': id,
    'name': name,
    'house_id': houseId,
    'house_name': houseName,
    'active': active,
    'last_seen': lastSeen?.toIso8601String(),
    'can_control': canControl,
    'capture_event_id': captureEventId,
    'applied_active': appliedActive,
    'applied_at': appliedAt?.toIso8601String(),
    'pairing_status': pairingStatus,
  };

  factory MobileCamera.fromCache(Map<String, dynamic> data) => MobileCamera(
    id: data['id'] as String? ?? '',
    name: data['name'] as String? ?? 'Caméra',
    houseId: data['house_id'] as int?,
    houseName: data['house_name'] as String? ?? '',
    active: data['active'] == true,
    lastSeen: DateTime.tryParse(data['last_seen'] as String? ?? ''),
    canControl: data['can_control'] == true,
    captureEventId: data['capture_event_id'] as String?,
    appliedActive: data['applied_active'] as bool?,
    appliedAt: DateTime.tryParse(data['applied_at'] as String? ?? ''),
    pairingStatus: data['pairing_status'] as String? ?? 'unknown',
  );
}

class CameraPairingCode {
  const CameraPairingCode({required this.code, required this.expiresAt});
  final String code;
  final DateTime expiresAt;
}

class MobileHouse {
  const MobileHouse({
    required this.id,
    required this.name,
    required this.timezone,
    required this.role,
  });

  final int id;
  final String name;
  final String timezone;
  final String role;
}

class MobileSessionInfo {
  const MobileSessionInfo({
    required this.id,
    required this.deviceName,
    required this.current,
    required this.revoked,
    this.lastUsedAt,
  });

  final String id;
  final String deviceName;
  final bool current;
  final bool revoked;
  final DateTime? lastUsedAt;
}

class AccountSummary {
  const AccountSummary({
    required this.username,
    required this.email,
    required this.houseCount,
    required this.cameraCount,
    required this.eventCount,
    this.activeCameraCount = 0,
    this.recentEvents = const [],
    this.cameras = const [],
  });

  final String username;
  final String email;
  final int houseCount;
  final int cameraCount;
  final int eventCount;
  final int activeCameraCount;
  final List<RecentEvent> recentEvents;
  final List<MobileCamera> cameras;

  Map<String, Object?> toCache() => {
    'username': username,
    'email': email,
    'house_count': houseCount,
    'camera_count': cameraCount,
    'event_count': eventCount,
    'active_camera_count': activeCameraCount,
    'recent_events': recentEvents.map((event) => event.toCache()).toList(),
    'cameras': cameras.map((camera) => camera.toCache()).toList(),
  };

  factory AccountSummary.fromCache(Map<String, dynamic> data) => AccountSummary(
    username: data['username'] as String? ?? '',
    email: data['email'] as String? ?? '',
    houseCount: data['house_count'] as int? ?? 0,
    cameraCount: data['camera_count'] as int? ?? 0,
    eventCount: data['event_count'] as int? ?? 0,
    activeCameraCount: data['active_camera_count'] as int? ?? 0,
    recentEvents: (data['recent_events'] as List? ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(RecentEvent.fromCache)
        .toList(),
    cameras: (data['cameras'] as List? ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(MobileCamera.fromCache)
        .toList(),
  );
}

class CachedSummary {
  const CachedSummary({required this.summary, required this.savedAt});

  final AccountSummary summary;
  final DateTime savedAt;
}

class ApiFailure implements Exception {
  const ApiFailure(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

class NetworkFailure extends ApiFailure {
  const NetworkFailure(super.message);
}

class SessionExpiredFailure extends ApiFailure {
  const SessionExpiredFailure()
    : super('Votre session a expiré. Connectez-vous de nouveau.');
}
