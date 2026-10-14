part of '../app.dart';

class MemberEditScreen extends StatefulWidget {
  const MemberEditScreen({
    super.key,
    required this.controller,
    required this.path,
    required this.cameras,
    this.member,
  });
  final AppController controller;
  final String path;
  final List<Map<String, dynamic>> cameras;
  final Map<String, dynamic>? member;
  @override
  State<MemberEditScreen> createState() => _MemberEditScreenState();
}

class _MemberEditScreenState extends State<MemberEditScreen> {
  final _form = GlobalKey<FormState>();
  String _username = '';
  late String _role;
  late Map<String, Map<String, Object?>> _access;
  bool _busy = false;
  String? _error;
  @override
  void initState() {
    super.initState();
    _role = widget.member?['role'] as String? ?? 'guest';
    _access = {
      for (final camera in widget.cameras)
        camera['id'] as String: {
          'camera_id': camera['id'],
          'peut_voir': false,
          'peut_controler': false,
        },
    };
    for (final item in (widget.member?['access'] as List? ?? [])) {
      if (_access.containsKey(item['camera_id'])) {
        _access[item['camera_id'] as String] = Map<String, Object?>.from(
          item as Map,
        );
      }
    }
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
        'action': widget.member == null ? 'invite' : 'update',
        if (widget.member != null)
          'id': widget.member!['id']
        else
          'username': _username,
        'role': _role,
        'access': _access.values.toList(),
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
    title: widget.member == null ? 'Inviter un membre' : 'Acces du membre',
    busy: _busy,
    error: _error,
    children: [
      Form(
        key: _form,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (widget.member == null)
              TextFormField(
                maxLength: 150,
                autocorrect: false,
                decoration: const InputDecoration(
                  labelText: "Nom d'utilisateur",
                ),
                validator: (value) => value == null || value.trim().isEmpty
                    ? 'Compte requis.'
                    : null,
                onSaved: (value) => _username = value!.trim(),
              )
            else
              Text(
                widget.member!['username'] as String,
                style: Theme.of(context).textTheme.titleMedium,
              ),
            DropdownButtonFormField<String>(
              initialValue: _role,
              decoration: const InputDecoration(labelText: 'Role'),
              items: ['guest', 'family']
                  .map(
                    (role) => DropdownMenuItem(
                      value: role,
                      child: Text(_memberRole(role)),
                    ),
                  )
                  .toList(),
              onChanged: (value) => setState(() => _role = value!),
            ),
            const SizedBox(height: 16),
            for (final camera in widget.cameras) ...[
              Text(
                camera['nom'] as String,
                style: Theme.of(context).textTheme.titleSmall,
              ),
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Voir la camera'),
                value: _access[camera['id']]!['peut_voir'] == true,
                onChanged: (value) => setState(() {
                  _access[camera['id']]!['peut_voir'] = value;
                  if (value != true) {
                    _access[camera['id']]!['peut_controler'] = false;
                  }
                }),
              ),
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Traiter les alertes'),
                value: _access[camera['id']]!['peut_controler'] == true,
                onChanged: _access[camera['id']]!['peut_voir'] != true
                    ? null
                    : (value) => setState(
                        () => _access[camera['id']]!['peut_controler'] = value,
                      ),
              ),
              const Divider(),
            ],
            FilledButton.icon(
              onPressed: _save,
              icon: const Icon(Icons.save_outlined),
              label: Text(
                widget.member == null ? 'Envoyer l\'invitation' : 'Enregistrer',
              ),
            ),
          ],
        ),
      ),
    ],
  );
}
