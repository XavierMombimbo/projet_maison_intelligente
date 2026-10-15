import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'app.dart';
import 'core/mobile_api.dart';
import 'core/push_coordinator.dart';
import 'core/secure_session_store.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final store = SecureSessionStore();
  final api = HttpMobileApi(client: http.Client(), store: store);
  final push = PushCoordinator(api: api);
  push.setAvailable(await PushCoordinator.configureFirebase());
  runApp(
    SentinelleApp(
      api: api,
      store: store,
      push: push,
      refreshInterval: const Duration(seconds: 15),
    ),
  );
}
