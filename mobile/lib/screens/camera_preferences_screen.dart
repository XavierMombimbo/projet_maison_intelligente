part of '../app.dart';

class CameraPreferencesScreen extends StatefulWidget {
  const CameraPreferencesScreen({
    super.key,
    required this.controller,
    required this.camera,
  });
  final AppController controller;
  final MobileCamera camera;
  @override
  State<CameraPreferencesScreen> createState() =>
      _CameraPreferencesScreenState();
}

class _CameraPreferencesScreenState
    extends _SettingsState<CameraPreferencesScreen> {
  @override
  AppController get controller => widget.controller;
  @override
  String get path => '/api/v1/cameras/${widget.camera.id}/preferences/';
  @override
  Widget build(BuildContext context) {
    final d = data ?? {};
    Widget toggle(String key, String label) => SwitchListTile(
      contentPadding: EdgeInsets.zero,
      title: Text(label),
      value: d[key] == true,
      onChanged: (value) => setState(() => d[key] = value),
    );
    return page('Mes notifications', [
      Text(widget.camera.name, style: Theme.of(context).textTheme.titleMedium),
      Text(d['timezone'] as String? ?? ''),
      toggle('enabled', 'Recevoir les notifications'),
      toggle('people', 'Personnes'),
      toggle('objects_enabled', 'Objets et animaux'),
      DropdownButtonFormField<String>(
        initialValue: d['lock_screen'] as String? ?? 'private',
        isExpanded: true,
        decoration: const InputDecoration(
          labelText: 'Ecran verrouille Android',
        ),
        items: const [
          DropdownMenuItem(value: 'private', child: Text('Masquer le contenu')),
          DropdownMenuItem(
            value: 'secret',
            child: Text('Masquer la notification'),
          ),
          DropdownMenuItem(value: 'public', child: Text('Message generique')),
        ],
        onChanged: (value) => setState(() => d['lock_screen'] = value),
      ),
      const Divider(),
      _TimeSetting(
        label: 'Debut du silence',
        value: d['quiet_start'] as String?,
        onChanged: (value) => setState(() => d['quiet_start'] = value),
      ),
      _TimeSetting(
        label: 'Fin du silence',
        value: d['quiet_end'] as String?,
        onChanged: (value) => setState(() => d['quiet_end'] = value),
      ),
      TextButton.icon(
        onPressed: () => setState(() {
          d['quiet_start'] = null;
          d['quiet_end'] = null;
        }),
        icon: const Icon(Icons.clear),
        label: const Text('Effacer la plage silencieuse'),
      ),
      toggle('urgent_during_quiet', 'Alertes urgentes pendant le silence'),
      const SizedBox(height: 16),
      FilledButton.icon(
        onPressed: () => save({
          for (final key in [
            'enabled',
            'people',
            'objects_enabled',
            'quiet_start',
            'quiet_end',
            'urgent_during_quiet',
            'lock_screen',
          ])
            key: key == 'lock_screen' ? (d[key] ?? 'private') : d[key],
        }),
        icon: const Icon(Icons.save_outlined),
        label: const Text('Enregistrer'),
      ),
    ]);
  }
}
