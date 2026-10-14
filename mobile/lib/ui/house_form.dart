part of '../app.dart';

class _HouseForm extends StatefulWidget {
  const _HouseForm({required this.controller, this.house});
  final AppController controller;
  final MobileHouse? house;

  @override
  State<_HouseForm> createState() => _HouseFormState();
}

class _HouseFormState extends State<_HouseForm> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _name;
  late final TextEditingController _timezone;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _name = TextEditingController(text: widget.house?.name ?? '');
    _timezone = TextEditingController(text: widget.house?.timezone ?? 'Africa/Kinshasa');
  }

  @override
  void dispose() {
    _name.dispose();
    _timezone.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_saving || !_formKey.currentState!.validate()) return;
    setState(() { _saving = true; _error = null; });
    try {
      await widget.controller.saveHouse(id: widget.house?.id,
        name: _name.text.trim(), timezone: _timezone.text.trim());
      if (mounted) Navigator.of(context).pop(true);
    } catch (error) {
      if (mounted) {
        setState(() {
        _error = error is ApiFailure ? error.message : 'Enregistrement impossible. Réessayez.';
        _saving = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final editable = widget.house == null || widget.house!.role == 'owner';
    return PopScope(
      canPop: !_saving,
      child: Scaffold(
        appBar: AppBar(title: Text(widget.house == null ? 'Ajouter une maison' : 'Modifier la maison')),
        body: SafeArea(child: Form(
          key: _formKey,
          child: ListView(padding: const EdgeInsets.all(20), children: [
            TextFormField(controller: _name, enabled: editable && !_saving,
              maxLength: 120, textCapitalization: TextCapitalization.sentences,
              decoration: const InputDecoration(labelText: 'Nom de la maison'),
              validator: (value) => value == null || value.trim().isEmpty ? 'Nom requis.' : null),
            const SizedBox(height: 16),
            TextFormField(controller: _timezone, enabled: editable && !_saving,
              maxLength: 64, autocorrect: false,
              decoration: const InputDecoration(labelText: 'Fuseau horaire', hintText: 'Africa/Kinshasa'),
              validator: (value) => value == null || value.trim().isEmpty ? 'Fuseau horaire requis.' : null),
            if (_error != null) ...[const SizedBox(height: 16), _ErrorBanner(message: _error!)],
            const SizedBox(height: 24),
            FilledButton.icon(onPressed: editable && !_saving ? _save : null,
              icon: _saving ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.save_outlined),
              label: Text(_saving ? 'Enregistrement...' : 'Enregistrer')),
          ]),
        )),
      ),
    );
  }
}
