part of '../app.dart';

class ScheduleEntryScreen extends StatefulWidget {
  const ScheduleEntryScreen({
    super.key,
    required this.controller,
    required this.path,
    required this.kind,
    required this.timezone,
    this.entry,
  });
  final AppController controller;
  final String path;
  final String kind;
  final String timezone;
  final Map<String, dynamic>? entry;
  @override
  State<ScheduleEntryScreen> createState() => _ScheduleEntryScreenState();
}

class _ScheduleEntryScreenState extends State<ScheduleEntryScreen> {
  late Map<String, dynamic> _values;
  final _form = GlobalKey<FormState>();
  bool _busy = false;
  String? _error;
  bool get _window => widget.kind == 'window';
  @override
  void initState() {
    super.initState();
    _values = {
      'nom': '',
      'jour': 0,
      'heure_debut': '20:00',
      'heure_fin': '06:00',
      'active': true,
      'date_debut': '',
      'date_fin': '',
      'surveillance_active': false,
      'priorite': 0,
      ...?widget.entry,
    };
  }

  Future<void> _save() async {
    if (_busy || !_form.currentState!.validate()) return;
    _form.currentState!.save();
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.controller.settings.saveSettings(widget.path, {
        ..._values,
        'action': widget.kind,
      });
      if (!mounted) return;
      setState(() => _busy = false);
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) Navigator.pop(context, true);
      });
    } catch (failure) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = _failureText(failure);
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => _SettingsLayout(
    title: _window ? 'Plage hebdomadaire' : 'Exception',
    busy: _busy,
    error: _error,
    children: [
      Form(
        key: _form,
        child: Column(
          children: [
            Text(widget.timezone),
            TextFormField(
              initialValue: _values['nom'] as String,
              maxLength: 120,
              decoration: const InputDecoration(labelText: 'Nom'),
              validator: (value) =>
                  value == null || value.trim().isEmpty ? 'Nom requis.' : null,
              onSaved: (value) => _values['nom'] = value!.trim(),
            ),
            if (_window) ...[
              DropdownButtonFormField<int>(
                initialValue: _values['jour'] as int,
                decoration: const InputDecoration(labelText: 'Jour'),
                items: List.generate(
                  7,
                  (i) => DropdownMenuItem(value: i, child: Text(_weekDays[i])),
                ),
                onChanged: (value) => setState(() => _values['jour'] = value),
              ),
              _TimeSetting(
                label: 'Debut',
                value: _values['heure_debut'] as String?,
                onChanged: (value) =>
                    setState(() => _values['heure_debut'] = value),
              ),
              _TimeSetting(
                label: 'Fin',
                value: _values['heure_fin'] as String?,
                onChanged: (value) =>
                    setState(() => _values['heure_fin'] = value),
              ),
              SwitchListTile(
                title: const Text('Plage active'),
                value: _values['active'] == true,
                onChanged: (value) => setState(() => _values['active'] = value),
              ),
            ] else ...[
              for (final field in ['date_debut', 'date_fin'])
                _DateSetting(
                  label: field == 'date_debut' ? 'Debut' : 'Fin',
                  value: _values[field] as String,
                  onChanged: (value) => setState(() => _values[field] = value),
                ),
              SwitchListTile(
                title: const Text('Surveillance active'),
                value: _values['surveillance_active'] == true,
                onChanged: (value) =>
                    setState(() => _values['surveillance_active'] = value),
              ),
              TextFormField(
                initialValue: '${_values['priorite']}',
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'Priorite (0-100)',
                ),
                validator: (value) {
                  final n = int.tryParse(value ?? '');
                  return n == null || n < 0 || n > 100
                      ? 'Valeur de 0 a 100.'
                      : null;
                },
                onSaved: (value) => _values['priorite'] = int.parse(value!),
              ),
            ],
            const SizedBox(height: 20),
            FilledButton.icon(
              onPressed: _save,
              icon: const Icon(Icons.save_outlined),
              label: const Text('Enregistrer'),
            ),
          ],
        ),
      ),
    ],
  );
}
