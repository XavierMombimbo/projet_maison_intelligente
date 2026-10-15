part of '../app.dart';

class InvitationsScreen extends StatefulWidget {
  const InvitationsScreen({super.key, required this.controller});
  final AppController controller;
  @override
  State<InvitationsScreen> createState() => _InvitationsScreenState();
}

class _InvitationsScreenState extends _SettingsState<InvitationsScreen> {
  @override
  AppController get controller => widget.controller;
  @override
  String get path => '/api/v1/invitations/';
  Future<void> _respond(int id, String action) async {
    if (await _confirmRemoval(
          context,
          action == 'accept'
              ? 'Accepter cette invitation ?'
              : 'Refuser cette invitation ?',
        ) &&
        mounted) {
      if (await save({'id': id, 'action': action})) await controller.refresh();
    }
  }

  @override
  Widget build(BuildContext context) {
    final items = data?['invitations'] as List? ?? [];
    return page('Invitations', [
      if (items.isEmpty) const Text('Aucune invitation en attente.'),
      for (final item in items) ...[
        ListTile(
          contentPadding: EdgeInsets.zero,
          title: Text(item['maison__nom'] as String),
          subtitle: Text(
            '${item['maison__proprietaire__username']} - ${_memberRole(item['role'] as String)}',
          ),
        ),
        Wrap(
          spacing: 12,
          children: [
            FilledButton.icon(
              onPressed: () => _respond(item['id'] as int, 'accept'),
              icon: const Icon(Icons.check),
              label: const Text('Accepter'),
            ),
            TextButton.icon(
              onPressed: () => _respond(item['id'] as int, 'refuse'),
              icon: const Icon(Icons.close),
              label: const Text('Refuser'),
            ),
          ],
        ),
        const Divider(),
      ],
    ]);
  }
}
