part of '../app.dart';

String _memberRole(String role) => switch (role) {
  'owner' => 'Proprietaire',
  'family' => 'Famille',
  _ => 'Invite',
};
String _memberStatus(String status) => switch (status) {
  'accepted' => 'Acceptee',
  'refused' => 'Refusee',
  _ => 'En attente',
};

class HouseMembersScreen extends StatefulWidget {
  const HouseMembersScreen({
    super.key,
    required this.controller,
    required this.house,
  });
  final AppController controller;
  final MobileHouse house;
  @override
  State<HouseMembersScreen> createState() => _HouseMembersScreenState();
}

class _HouseMembersScreenState extends _SettingsState<HouseMembersScreen> {
  @override
  AppController get controller => widget.controller;
  @override
  String get path => '/api/v1/houses/${widget.house.id}/members/';
  Future<void> _edit([Map<String, dynamic>? member]) async {
    final saved = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => MemberEditScreen(
          controller: controller,
          path: path,
          member: member,
          cameras: (data?['cameras'] as List? ?? [])
              .map((e) => Map<String, dynamic>.from(e as Map))
              .toList(),
        ),
      ),
    );
    if (saved == true && mounted) await reload();
  }

  Future<void> _remove(Map<String, dynamic> member) async {
    if (await _confirmRemoval(
          context,
          'Retirer ${member['username']} de la maison ?',
        ) &&
        mounted) {
      await save({'action': 'remove', 'id': member['id']});
    }
  }

  @override
  Widget build(BuildContext context) => page('Membres', [
    Text(widget.house.name, style: Theme.of(context).textTheme.titleMedium),
    Align(
      alignment: Alignment.centerRight,
      child: IconButton(
        tooltip: 'Inviter un membre',
        icon: const Icon(Icons.person_add_outlined),
        onPressed: () => _edit(),
      ),
    ),
    for (final item in (data?['members'] as List? ?? []))
      ListTile(
        contentPadding: EdgeInsets.zero,
        title: Text(item['username'] as String),
        subtitle: Text(
          '${_memberRole(item['role'] as String)} - ${_memberStatus(item['status'] as String)}',
        ),
        onTap: item['is_owner'] == true
            ? null
            : () => _edit(Map<String, dynamic>.from(item as Map)),
        trailing: item['is_owner'] == true
            ? const Icon(Icons.shield_outlined)
            : IconButton(
                tooltip: 'Retirer le membre',
                icon: const Icon(Icons.person_remove_outlined),
                onPressed: () =>
                    _remove(Map<String, dynamic>.from(item as Map)),
              ),
      ),
  ]);
}
