part of '../app.dart';

class CameraFormScreen extends StatefulWidget {
  const CameraFormScreen({super.key, required this.controller, this.camera, this.initialName});
  final AppController controller;
  final MobileCamera? camera;
  final String? initialName;

  @override
  State<CameraFormScreen> createState() => _CameraFormScreenState();
}

class _CameraFormScreenState extends State<CameraFormScreen> {
  final _form = GlobalKey<FormState>();
  late final TextEditingController _name;
  final _url = TextEditingController();
  final _username = TextEditingController();
  final _password = TextEditingController();
  List<MobileHouse> _houses = [];
  int? _houseId;
  String _source = 'webcam';
  String? _error;
  bool _loading = false;
  bool _saving = false;
  bool get _editing => widget.camera != null;

  @override
  void initState() {
    super.initState();
    _name = TextEditingController(text: widget.initialName ?? widget.camera?.name ?? '');
    if (!_editing) _loadHouses();
  }

  Future<void> _loadHouses() async {
    setState(() { _loading = true; _error = null; });
    try {
      final houses = await widget.controller.loadHouses();
      if (!mounted) return;
      setState(() {
        _houses = houses.where((house) => house.role == 'owner').toList();
        _houseId = _houses.isEmpty ? null : _houses.first.id;
      });
    } catch (error) {
      if (mounted) {
        setState(() => _error = error is ApiFailure ? error.message : 'Chargement impossible.');
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _save() async {
    if (_saving || !_form.currentState!.validate()) return;
    setState(() { _saving = true; _error = null; });
    try {
      await widget.controller.saveCamera(id: widget.camera?.id, name: _name.text,
        houseId: _houseId, source: _source, url: _url.text,
        username: _username.text, password: _password.text);
      if (!mounted) return;
      // Re-enable route popping before returning the successful result.
      setState(() => _saving = false);
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) Navigator.of(context).pop(_name.text.trim());
      });
    } catch (error) {
      if (mounted) {
        setState(() {
          _saving = false;
          _error = error is ApiFailure ? error.message : 'Enregistrement impossible.';
        });
      }
    }
  }

  @override
  void dispose() {
    for (final field in [_name, _url, _username, _password]) { field.dispose(); }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final allowed = _editing ? widget.camera!.canControl : _houses.isNotEmpty;
    return PopScope(
      canPop: !_saving,
      child: Scaffold(
        appBar: AppBar(title: Text(_editing ? 'Renommer la caméra' : 'Ajouter une caméra')),
        body: SafeArea(child: Center(child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 600),
          child: _loading ? const Center(child: CircularProgressIndicator()) : Form(
            key: _form,
            child: ListView(padding: const EdgeInsets.all(20), children: [
              if (!_editing && _houses.isEmpty)
                const _InfoBanner(icon: Icons.home_outlined, text: 'Aucune maison propriétaire disponible.'),
              if (!_editing && _houses.isNotEmpty) ...[
                DropdownButtonFormField<int>(
                  initialValue: _houseId, isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Maison'),
                  items: _houses.map((house) => DropdownMenuItem(value: house.id,
                    child: Text(house.name, overflow: TextOverflow.ellipsis))).toList(),
                  onChanged: _saving ? null : (value) => setState(() => _houseId = value),
                  validator: (value) => value == null ? 'Maison requise.' : null,
                ),
                const SizedBox(height: 16),
              ],
              TextFormField(controller: _name, enabled: allowed && !_saving, maxLength: 120,
                decoration: const InputDecoration(labelText: 'Nom de la caméra'),
                validator: (value) => value == null || value.trim().isEmpty ? 'Nom requis.' : null),
              if (!_editing) ...[
                const SizedBox(height: 16),
                SegmentedButton<String>(
                  segments: const [
                    ButtonSegment(value: 'webcam', icon: Icon(Icons.videocam_outlined), label: Text('Webcam')),
                    ButtonSegment(value: 'rtsp', icon: Icon(Icons.router_outlined), label: Text('RTSP')),
                  ],
                  selected: {_source}, showSelectedIcon: false,
                  onSelectionChanged: _saving || !allowed ? null : (value) => setState(() => _source = value.first),
                ),
                if (_source == 'rtsp') ...[
                  const SizedBox(height: 16),
                  TextFormField(controller: _url, enabled: !_saving, autocorrect: false,
                    decoration: const InputDecoration(labelText: 'Adresse RTSP'),
                    validator: (value) => value == null || value.trim().isEmpty ? 'Adresse requise.' : null),
                  const SizedBox(height: 16),
                  TextFormField(controller: _username, enabled: !_saving, autocorrect: false,
                    enableSuggestions: false,
                    decoration: const InputDecoration(labelText: 'Utilisateur RTSP')),
                  const SizedBox(height: 16),
                  TextFormField(controller: _password, enabled: !_saving, obscureText: true,
                    autocorrect: false, enableSuggestions: false,
                    decoration: const InputDecoration(labelText: 'Mot de passe RTSP')),
                ],
              ],
              if (_error != null) ...[
                const SizedBox(height: 16), _ErrorBanner(message: _error!),
                if (!_editing && _houses.isEmpty)
                  TextButton.icon(onPressed: _loadHouses, icon: const Icon(Icons.refresh), label: const Text('Réessayer')),
              ],
              const SizedBox(height: 24),
              FilledButton.icon(onPressed: allowed && !_saving ? _save : null,
                icon: _saving ? const SizedBox(width: 18, height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.save_outlined),
                label: const Text('Enregistrer')),
            ]),
          ),
        ))),
      ),
    );
  }
}
