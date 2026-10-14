part of '../app.dart';

abstract class _SettingsState<T extends StatefulWidget> extends State<T> {
  AppController get controller;
  String get path;
  Map<String, dynamic>? data;
  String? error;
  bool loading = true;
  bool busy = false;

  @override
  void initState() {
    super.initState();
    reload();
  }

  Future<void> reload() async {
    if (busy) return;
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final result = await controller.settings.loadSettings(path);
      if (mounted) setState(() => data = result);
    } catch (failure) {
      if (mounted) setState(() => error = _failureText(failure));
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<bool> save(Map<String, Object?> body) async {
    if (busy) return false;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = await controller.settings.saveSettings(path, body);
      if (!mounted) return false;
      setState(() => data = result);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('Enregistre.')));
      return true;
    } catch (failure) {
      if (mounted) setState(() => error = _failureText(failure));
      return false;
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Widget page(String title, List<Widget> children) => _SettingsLayout(
    title: title,
    loading: loading,
    busy: busy,
    error: error,
    retry: reload,
    children: data == null ? [] : children,
  );
}

String _failureText(Object failure) => failure is ApiFailure
    ? failure.message
    : 'Operation impossible. Reessayez.';

class _SettingsLayout extends StatelessWidget {
  const _SettingsLayout({
    required this.title,
    required this.children,
    this.error,
    this.loading = false,
    this.busy = false,
    this.retry,
  });
  final String title;
  final List<Widget> children;
  final String? error;
  final bool loading;
  final bool busy;
  final VoidCallback? retry;
  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !busy,
    child: Scaffold(
      appBar: AppBar(
        title: Text(title, maxLines: 1, overflow: TextOverflow.ellipsis),
      ),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: loading
                ? const Center(child: CircularProgressIndicator())
                : ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      if (error != null) ...[
                        _ErrorBanner(message: error!),
                        if (retry != null)
                          TextButton.icon(
                            onPressed: busy ? null : retry,
                            icon: const Icon(Icons.refresh),
                            label: const Text('Reessayer'),
                          ),
                        const SizedBox(height: 12),
                      ],
                      AbsorbPointer(
                        absorbing: busy,
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: children,
                        ),
                      ),
                      if (busy)
                        const Padding(
                          padding: EdgeInsets.all(12),
                          child: LinearProgressIndicator(),
                        ),
                    ],
                  ),
          ),
        ),
      ),
    ),
  );
}

Future<bool> _confirmRemoval(BuildContext context, String title) async =>
    await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Annuler'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Confirmer'),
          ),
        ],
      ),
    ) ??
    false;

String _timeString(TimeOfDay time) =>
    '${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}';

class _TimeSetting extends StatelessWidget {
  const _TimeSetting({
    required this.label,
    required this.value,
    required this.onChanged,
  });
  final String label;
  final String? value;
  final ValueChanged<String>? onChanged;
  @override
  Widget build(BuildContext context) => ListTile(
    contentPadding: EdgeInsets.zero,
    title: Text(label),
    subtitle: Text(
      value == null || value!.isEmpty ? '--:--' : value!.substring(0, 5),
    ),
    trailing: IconButton(
      tooltip: label,
      icon: const Icon(Icons.schedule),
      onPressed: onChanged == null
          ? null
          : () async {
              final parts = (value ?? '08:00').split(':');
              final time = await showTimePicker(
                context: context,
                initialTime: TimeOfDay(
                  hour: int.tryParse(parts.first) ?? 8,
                  minute: parts.length > 1 ? int.tryParse(parts[1]) ?? 0 : 0,
                ),
              );
              if (time != null) onChanged!(_timeString(time));
            },
    ),
  );
}

class _DateSetting extends StatelessWidget {
  const _DateSetting({
    required this.label,
    required this.value,
    required this.onChanged,
  });
  final String label;
  final String value;
  final ValueChanged<String> onChanged;
  @override
  Widget build(BuildContext context) => ListTile(
    contentPadding: EdgeInsets.zero,
    title: Text(label),
    subtitle: Text(value.isEmpty ? '--' : value.replaceFirst('T', ' ')),
    trailing: IconButton(
      tooltip: label,
      icon: const Icon(Icons.calendar_month),
      onPressed: () async {
        final initial = DateTime.tryParse(value) ?? DateTime.now();
        final date = await showDatePicker(
          context: context,
          initialDate: initial,
          firstDate: DateTime(2000),
          lastDate: DateTime(2100),
        );
        if (date == null || !context.mounted) return;
        final time = await showTimePicker(
          context: context,
          initialTime: TimeOfDay.fromDateTime(initial),
        );
        if (time != null) {
          onChanged(
            '${date.year}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}T${_timeString(time)}',
          );
        }
      },
    ),
  );
}
