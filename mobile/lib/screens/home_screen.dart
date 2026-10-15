part of '../app.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, required this.controller, this.refreshInterval});

  final AppController controller;
  final Duration? refreshInterval;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> with WidgetsBindingObserver {
  Timer? _refreshTimer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _startTimer();
  }

  @override
  void didUpdateWidget(covariant HomeScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.refreshInterval != widget.refreshInterval) _startTimer();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _refreshTimer?.cancel();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) widget.controller.refresh();
  }

  void _startTimer() {
    _refreshTimer?.cancel();
    final interval = widget.refreshInterval ?? const Duration(seconds: 15);
    _refreshTimer = Timer.periodic(interval, (_) {
      if (mounted && !widget.controller.busy) widget.controller.refresh();
    });
  }

  @override
  Widget build(BuildContext context) {
    final controller = widget.controller;
    final summary = controller.summary;
    if (summary == null) return const _BootScreen();
    final tabs = [
      _OverviewTab(
        summary: summary,
        controller: controller,
        onCameras: () => controller.selectTab(2),
        onAlerts: () => controller.selectTab(3),
      ),
      _HousesTab(controller: controller, summary: summary),
      _CamerasTab(controller: controller),
      _AlertsTab(summary: summary, controller: controller),
      _SecurityTab(
        controller: controller,
        summary: summary,
        busy: controller.busy,
        onLogout: _confirmLogout,
      ),
    ];
    final selected = controller.selectedTab.clamp(0, tabs.length - 1);
    return Scaffold(
      appBar: AppBar(
        title: const _Logo(compact: true),
        actions: [
          IconButton(
            tooltip: 'Actualiser',
            onPressed: controller.busy ? null : controller.refresh,
            icon: const Icon(Icons.refresh_rounded),
          ),
        ],
      ),
      body: Column(
        children: [
          if (controller.usingCachedData)
            _StaleDataBanner(
              updatedAt: controller.dataUpdatedAt,
              busy: controller.busy,
              onRetry: controller.refresh,
            ),
          Expanded(child: tabs[selected]),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: selected,
        onDestinationSelected: controller.selectTab,
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.home_outlined),
            selectedIcon: Icon(Icons.home_rounded),
            label: 'Accueil',
          ),
          NavigationDestination(
            icon: Icon(Icons.maps_home_work_outlined),
            selectedIcon: Icon(Icons.maps_home_work_rounded),
            label: 'Maisons',
          ),
          NavigationDestination(
            icon: Icon(Icons.videocam_outlined),
            selectedIcon: Icon(Icons.videocam_rounded),
            label: 'Caméras',
          ),
          NavigationDestination(
            icon: Icon(Icons.notifications_none_rounded),
            selectedIcon: Icon(Icons.notifications_rounded),
            label: 'Alertes',
          ),
          NavigationDestination(
            icon: Icon(Icons.security_outlined),
            selectedIcon: Icon(Icons.security_rounded),
            label: 'Sécurité',
          ),
        ],
      ),
    );
  }

  Future<void> _confirmLogout() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        icon: const Icon(Icons.logout_rounded),
        title: const Text('Se déconnecter ?'),
        content: const Text(
          'Vous devrez saisir à nouveau votre mot de passe et votre code MFA sur ce téléphone.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Annuler'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Se déconnecter'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    final revoked = await widget.controller.logout();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          revoked
              ? 'Session révoquée et jetons effacés.'
              : 'Jetons effacés sur ce téléphone. Le serveur était inaccessible pendant la révocation.',
        ),
      ),
    );
  }
}

class _StaleDataBanner extends StatelessWidget {
  const _StaleDataBanner({
    required this.updatedAt,
    required this.busy,
    required this.onRetry,
  });

  final DateTime? updatedAt;
  final bool busy;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Material(
      color: colors.surfaceContainerHighest,
      child: SafeArea(
        top: false,
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.only(left: 14),
          child: Row(
            children: [
              Icon(Icons.wifi_off_rounded, size: 18, color: colors.onSurface),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'Hors ligne · données du ${_formatDate(updatedAt)}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 12),
                ),
              ),
              IconButton(
                tooltip: 'Réessayer la connexion',
                onPressed: busy ? null : onRetry,
                icon: const Icon(Icons.refresh_rounded, size: 18),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
