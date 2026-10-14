import 'dart:async';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import 'app_controller.dart';
import 'core/auth_models.dart';
import 'core/mobile_api.dart';
import 'core/push_coordinator.dart';
import 'core/session_store.dart';
part 'screens/auth_screens.dart';
part 'screens/home_screen.dart';
part 'screens/house_create_screen.dart';
part 'screens/house_edit_screen.dart';
part 'screens/camera_form_screen.dart';
part 'screens/camera_pairing_screen.dart';
part 'screens/house_schedule_screen.dart';
part 'screens/schedule_entry_screen.dart';
part 'screens/camera_preferences_screen.dart';
part 'screens/house_members_screen.dart';
part 'screens/member_edit_screen.dart';
part 'screens/invitations_screen.dart';
part 'screens/notification_event_screen.dart';
part 'ui/settings_widgets.dart';
part 'ui/house_form.dart';
part 'tabs/alerts_tab.dart';
part 'tabs/security_tab.dart';
part 'ui/shared_widgets.dart';
part 'monitoring_screens.dart';

const _navy = Color(0xFF0F172A);
const _green = Color(0xFF087A55);
const _mint = Color(0xFFDFF6EC);
const _surface = Color(0xFFF2F6F5);
const _border = Color(0xFFD8E2DF);
const _neutralAlert = Color(0xFF425D69);
const _neutralAlertSoft = Color(0xFFEAF0F3);

typedef ExternalPageOpener = Future<bool> Function(Uri uri);

Future<bool> _openExternalPage(Uri uri) =>
    launchUrl(uri, mode: LaunchMode.externalApplication);

class SentinelleApp extends StatefulWidget {
  const SentinelleApp({
    super.key,
    required this.api,
    required this.store,
    this.push,
    this.refreshInterval,
    this.openExternalPage = _openExternalPage,
  });

  final MobileApi api;
  final SessionStore store;
  final PushCoordinator? push;
  final Duration? refreshInterval;
  final ExternalPageOpener openExternalPage;

  @override
  State<SentinelleApp> createState() => _SentinelleAppState();
}

class _SentinelleAppState extends State<SentinelleApp> {
  late final AppController controller;
  final _navigator = GlobalKey<NavigatorState>();
  String? _pendingEvent;
  String? _openEvent;
  AppPhase _previousPhase = AppPhase.booting;

  @override
  void initState() {
    super.initState();
    controller = AppController(
      api: widget.api,
      store: widget.store,
      push: widget.push,
    );
    widget.push?.onAlertReceived = _refreshAfterAlert;
    widget.push?.onAlertOpened = _queueEvent;
    controller.addListener(_routePendingEvent);
    widget.push?.start();
    controller.initialize();
  }

  Future<void> _queueEvent(String id) async {
    _pendingEvent = id;
    _routePendingEvent();
  }

  void _routePendingEvent() {
    final signedOut = controller.phase == AppPhase.signedOut;
    if (signedOut && _previousPhase == AppPhase.signedIn) {
      _pendingEvent = null;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) {
          _navigator.currentState?.popUntil((route) => route.isFirst);
        }
      });
    }
    _previousPhase = controller.phase;
    if (controller.phase != AppPhase.signedIn || _pendingEvent == null) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || controller.phase != AppPhase.signedIn) return;
      final id = _pendingEvent;
      final navigator = _navigator.currentState;
      if (id == null || navigator == null) return;
      _pendingEvent = null;
      if (_openEvent == id) return;
      if (_openEvent != null) navigator.popUntil((route) => route.isFirst);
      _openEvent = id;
      navigator
          .push<void>(
            MaterialPageRoute(
              builder: (_) =>
                  NotificationEventScreen(controller: controller, eventId: id),
            ),
          )
          .whenComplete(() {
            if (_openEvent == id) _openEvent = null;
          });
    });
    WidgetsBinding.instance.ensureVisualUpdate();
  }

  Future<void> _refreshAfterAlert() async {
    if (!mounted || controller.busy) return;
    await controller.refresh();
  }

  @override
  void dispose() {
    widget.push?.onAlertReceived = null;
    widget.push?.onAlertOpened = null;
    widget.push?.dispose();
    controller.removeListener(_routePendingEvent);
    controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      navigatorKey: _navigator,
      debugShowCheckedModeBanner: false,
      title: 'Sentinelle Maison',
      theme: _theme(Brightness.light),
      darkTheme: _theme(Brightness.dark),
      themeMode: ThemeMode.system,
      home: AnimatedBuilder(
        animation: controller,
        builder: (context, _) {
          return AnimatedSwitcher(
            duration: const Duration(milliseconds: 220),
            child: switch (controller.phase) {
              AppPhase.booting => const _BootScreen(key: ValueKey('boot')),
              AppPhase.signedOut => LoginScreen(
                key: const ValueKey('login'),
                controller: controller,
                openExternalPage: widget.openExternalPage,
              ),
              AppPhase.awaitingMfa => MfaScreen(
                key: const ValueKey('mfa'),
                controller: controller,
              ),
              AppPhase.signedIn => HomeScreen(
                key: const ValueKey('home'),
                controller: controller,
                refreshInterval: widget.refreshInterval,
              ),
              AppPhase.offline => OfflineScreen(
                key: const ValueKey('offline'),
                controller: controller,
              ),
            },
          );
        },
      ),
    );
  }

  ThemeData _theme(Brightness brightness) {
    final dark = brightness == Brightness.dark;
    final scheme =
        ColorScheme.fromSeed(
          seedColor: _green,
          brightness: brightness,
          primary: dark ? const Color(0xFF45D6A5) : _green,
          secondary: const Color(0xFF20B486),
          surface: dark ? const Color(0xFF182237) : Colors.white,
          error: dark ? const Color(0xFFB8C6CD) : _neutralAlert,
        ).copyWith(
          errorContainer: dark ? const Color(0xFF23333B) : _neutralAlertSoft,
          onErrorContainer: dark
              ? const Color(0xFFEAF0F3)
              : const Color(0xFF253E49),
        );
    return ThemeData(
      useMaterial3: true,
      materialTapTargetSize: MaterialTapTargetSize.padded,
      fontFamilyFallback: const [
        'Inter',
        'Segoe UI',
        'Roboto',
        'Arial',
        'sans-serif',
      ],
      colorScheme: scheme,
      scaffoldBackgroundColor: dark ? const Color(0xFF0B1220) : _surface,
      textTheme: ThemeData(brightness: brightness).textTheme
          .copyWith(
            headlineMedium: const TextStyle(
              fontSize: 21,
              height: 1.25,
              fontWeight: FontWeight.w700,
            ),
            headlineSmall: const TextStyle(
              fontSize: 18,
              height: 1.25,
              fontWeight: FontWeight.w700,
            ),
            titleLarge: const TextStyle(
              fontSize: 16,
              height: 1.3,
              fontWeight: FontWeight.w700,
            ),
            titleMedium: const TextStyle(
              fontSize: 15,
              height: 1.35,
              fontWeight: FontWeight.w600,
            ),
            bodyLarge: const TextStyle(fontSize: 15, height: 1.4),
            bodyMedium: const TextStyle(fontSize: 13, height: 1.4),
            bodySmall: const TextStyle(fontSize: 12, height: 1.35),
          )
          .apply(
            bodyColor: dark ? const Color(0xFFE8EEF6) : const Color(0xFF17201F),
            displayColor: dark ? const Color(0xFFF8FAFC) : _navy,
          ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: dark ? const Color(0xFF111B2D) : Colors.white,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 14,
          vertical: 12,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: BorderSide(
            color: dark ? const Color(0xFF39465B) : _border,
          ),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: BorderSide(
            color: dark ? const Color(0xFF39465B) : _border,
          ),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: BorderSide(color: scheme.primary, width: 2),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size.fromHeight(48),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
          textStyle: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size.fromHeight(48),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
          textStyle: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
        ),
      ),
      iconButtonTheme: IconButtonThemeData(
        style: IconButton.styleFrom(
          minimumSize: const Size.square(48),
          iconSize: 20,
        ),
      ),
      listTileTheme: const ListTileThemeData(
        dense: true,
        minLeadingWidth: 32,
        minVerticalPadding: 6,
      ),
      appBarTheme: AppBarTheme(
        toolbarHeight: 50,
        backgroundColor: dark ? const Color(0xFF0B1220) : _surface,
        foregroundColor: dark ? Colors.white : _navy,
        iconTheme: IconThemeData(
          color: dark ? const Color(0xFFF8FAFC) : const Color(0xFF111827),
          size: 19,
        ),
        actionsIconTheme: IconThemeData(
          color: dark ? const Color(0xFFF8FAFC) : const Color(0xFF111827),
          size: 19,
        ),
        elevation: 0,
        shadowColor: Colors.black.withValues(alpha: 0.18),
        scrolledUnderElevation: 0,
      ),
      navigationBarTheme: NavigationBarThemeData(
        height: 64,
        backgroundColor: dark ? const Color(0xFF111B2D) : Colors.white,
        indicatorColor: dark ? const Color(0xFF12392F) : _mint,
        iconTheme: WidgetStatePropertyAll(
          IconThemeData(
            color: dark ? const Color(0xFFF8FAFC) : const Color(0xFF111827),
            size: 21,
          ),
        ),
        labelTextStyle: WidgetStateProperty.resolveWith((states) {
          return TextStyle(
            color: dark ? const Color(0xFFF8FAFC) : const Color(0xFF111827),
            fontSize: 10.5,
            fontWeight: states.contains(WidgetState.selected)
                ? FontWeight.w700
                : FontWeight.w600,
          );
        }),
      ),
    );
  }
}
