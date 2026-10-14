part of '../app.dart';

const _weekDays = [
  'Lundi',
  'Mardi',
  'Mercredi',
  'Jeudi',
  'Vendredi',
  'Samedi',
  'Dimanche',
];

class HouseScheduleScreen extends StatefulWidget {
  const HouseScheduleScreen({
    super.key,
    required this.controller,
    required this.house,
  });
  final AppController controller;
  final MobileHouse house;
  @override
  State<HouseScheduleScreen> createState() => _HouseScheduleScreenState();
}

class _HouseScheduleScreenState extends _SettingsState<HouseScheduleScreen> {
  @override
  AppController get controller => widget.controller;
  @override
  String get path => '/api/v1/houses/${widget.house.id}/schedule/';
  bool _overrideActive = true;
  int _minutes = 60;
  Future<void> _entry(String kind, [Map<String, dynamic>? entry]) async {
    final saved = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => ScheduleEntryScreen(
          controller: controller,
          path: path,
          kind: kind,
          timezone: data?['timezone'] as String? ?? widget.house.timezone,
          entry: entry,
        ),
      ),
    );
    if (saved == true && mounted) await reload();
  }

  Future<void> _delete(String action, [int? id]) async {
    if (await _confirmRemoval(context, 'Supprimer ce reglage ?') && mounted) {
      await save({'action': action, 'id': id});
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = data ?? {};
    final editable = d['can_edit'] == true;
    return page('Surveillance', [
      Text(widget.house.name, style: Theme.of(context).textTheme.titleMedium),
      Text(d['timezone'] as String? ?? ''),
      const SizedBox(height: 8),
      Text(d['active'] == true ? 'Surveillance demandee' : 'Arret demande'),
      Text(d['reason'] as String? ?? ''),
      const Divider(),
      Text('Tous les jours', style: Theme.of(context).textTheme.titleMedium),
      _TimeSetting(
        label: 'Activation',
        value: d['daily_start'] as String?,
        onChanged: editable
            ? (value) => setState(() => d['daily_start'] = value)
            : null,
      ),
      _TimeSetting(
        label: 'Arret',
        value: d['daily_end'] as String?,
        onChanged: editable
            ? (value) => setState(() => d['daily_end'] = value)
            : null,
      ),
      if (editable) ...[
        FilledButton.icon(
          onPressed: () => save({
            'action': 'daily',
            'heure_activation': d['daily_start'],
            'heure_arret': d['daily_end'],
          }),
          icon: const Icon(Icons.save_outlined),
          label: const Text('Enregistrer les horaires'),
        ),
        TextButton.icon(
          onPressed: () => _delete('daily_clear'),
          icon: const Icon(Icons.delete_outline),
          label: const Text('Supprimer les horaires quotidiens'),
        ),
      ],
      const Divider(),
      Text(
        'Priorite temporaire',
        style: Theme.of(context).textTheme.titleMedium,
      ),
      if (d['override'] != null)
        Text('Expiration : ${d['override']['expires_at']}'),
      if (editable) ...[
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('Surveillance active'),
          value: _overrideActive,
          onChanged: (value) => setState(() => _overrideActive = value),
        ),
        DropdownButtonFormField<int>(
          initialValue: _minutes,
          decoration: const InputDecoration(labelText: 'Duree'),
          items: [15, 30, 60, 120, 480, 1440]
              .map(
                (n) => DropdownMenuItem(
                  value: n,
                  child: Text(n < 60 ? '$n minutes' : '${n ~/ 60} heures'),
                ),
              )
              .toList(),
          onChanged: (value) => setState(() => _minutes = value!),
        ),
        const SizedBox(height: 12),
        FilledButton.icon(
          onPressed: () => save({
            'action': 'override',
            'surveillance_active': _overrideActive,
            'duree_minutes': _minutes,
          }),
          icon: const Icon(Icons.timer_outlined),
          label: const Text('Appliquer'),
        ),
        if (d['override'] != null)
          TextButton.icon(
            onPressed: () => _delete('override_clear'),
            icon: const Icon(Icons.clear),
            label: const Text('Revenir au planning'),
          ),
      ],
      for (final kind in ['window', 'exception']) ...[
        const Divider(),
        Row(
          children: [
            Expanded(
              child: Text(
                kind == 'window' ? 'Plages hebdomadaires' : 'Exceptions',
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
            if (editable)
              IconButton(
                tooltip: 'Ajouter',
                onPressed: () => _entry(kind),
                icon: const Icon(Icons.add),
              ),
          ],
        ),
        for (final item
            in (d[kind == 'window' ? 'windows' : 'exceptions'] as List? ?? []))
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(item['nom'] as String),
            subtitle: Text(
              kind == 'window'
                  ? '${_weekDays[item['jour'] as int]} ${item['heure_debut']} - ${item['heure_fin']}${item['active'] == true ? '' : ' (suspendue)'}'
                  : '${item['date_debut']} - ${item['date_fin']}',
            ),
            onTap: editable
                ? () => _entry(kind, Map<String, dynamic>.from(item as Map))
                : null,
            trailing: editable
                ? IconButton(
                    tooltip: 'Supprimer',
                    icon: const Icon(Icons.delete_outline),
                    onPressed: () =>
                        _delete('${kind}_delete', item['id'] as int),
                  )
                : null,
          ),
      ],
    ]);
  }
}
