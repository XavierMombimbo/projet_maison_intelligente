part of '../app.dart';

class _SecurityTab extends StatefulWidget {
  const _SecurityTab({
    required this.controller,
    required this.summary,
    required this.busy,
    required this.onLogout,
  });

  final AppController controller;
  final AccountSummary summary;
  final bool busy;
  final VoidCallback onLogout;

  @override
  State<_SecurityTab> createState() => _SecurityTabState();
}

class _SecurityTabState extends State<_SecurityTab> {
  late Future<List<MobileSessionInfo>> _sessions;

  @override
  void initState() {
    super.initState();
    _sessions = widget.controller.loadSessions();
  }

  Future<void> _reload() async {
    setState(() {
      _sessions = widget.controller.loadSessions();
    });
    await _sessions;
  }

  Future<void> _revoke(MobileSessionInfo session) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        icon: const Icon(Icons.phonelink_erase_outlined),
        title: Text('Révoquer ${session.deviceName} ?'),
        content: const Text('Cet appareil devra se reconnecter avec le MFA.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Annuler'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Révoquer'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await widget.controller.revokeSession(session.id);
      await _reload();
    } on ApiFailure catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(error.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: _reload,
      child: ListView(
        key: const PageStorageKey('security-tab'),
        physics: const AlwaysScrollableScrollPhysics(),
        padding: _screenPadding(context),
        children: [
          const _ScreenTitle(
            eyebrow: 'Sécurité',
            title: 'Compte et appareils',
            description: 'Contrôlez les sessions mobiles liées au compte.',
          ),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.surface,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(
                color: Theme.of(context).colorScheme.outlineVariant,
              ),
              boxShadow: [_cardShadow(context)],
            ),
            child: Row(
              children: [
                const Icon(Icons.account_circle_outlined),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        widget.summary.username,
                        style: const TextStyle(fontWeight: FontWeight.w800),
                      ),
                      Text(widget.summary.email),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
          Text(
            'Appareils connectés',
            style: Theme.of(
              context,
            ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 8),
          FutureBuilder<List<MobileSessionInfo>>(
            future: _sessions,
            builder: (context, snapshot) {
              if (snapshot.connectionState != ConnectionState.done) {
                return const Center(child: CircularProgressIndicator());
              }
              if (snapshot.hasError) {
                return const _ErrorBanner(
                  message: 'Impossible de charger les sessions mobiles.',
                );
              }
              final sessions = snapshot.data ?? const [];
              if (sessions.isEmpty) {
                return const _InfoBanner(
                  icon: Icons.phone_android_outlined,
                  text: 'Aucune autre session mobile.',
                );
              }
              return Column(
                children: sessions
                    .map(
                      (session) => Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: _SessionTile(
                          session: session,
                          onRevoke: session.current || session.revoked
                              ? null
                              : () => _revoke(session),
                        ),
                      ),
                    )
                    .toList(),
              );
            },
          ),
          const SizedBox(height: 14),
          OutlinedButton.icon(
            key: const Key('logoutButton'),
            onPressed: widget.busy ? null : widget.onLogout,
            icon: const Icon(Icons.logout_rounded),
            label: Text(widget.busy ? 'Déconnexion…' : 'Se déconnecter'),
          ),
        ],
      ),
    );
  }
}

class _SessionTile extends StatelessWidget {
  const _SessionTile({required this.session, this.onRevoke});

  final MobileSessionInfo session;
  final VoidCallback? onRevoke;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final status = session.revoked
        ? 'Révoqué'
        : session.current
        ? 'Cet appareil'
        : 'Actif';
    return Container(
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: colors.outlineVariant),
      ),
      child: ListTile(
        minLeadingWidth: 32,
        minVerticalPadding: 6,
        visualDensity: const VisualDensity(vertical: -1),
        leading: Icon(Icons.phone_android_outlined, color: colors.onSurface),
        title: Text(
          session.deviceName,
          style: const TextStyle(fontWeight: FontWeight.w700),
        ),
        subtitle: Text(
          session.lastUsedAt == null
              ? status
              : '$status · ${_formatDate(session.lastUsedAt)}',
        ),
        trailing: onRevoke == null
            ? null
            : IconButton(
                tooltip: 'Révoquer ${session.deviceName}',
                onPressed: onRevoke,
                icon: const Icon(Icons.phonelink_erase_outlined),
              ),
      ),
    );
  }
}
