part of '../app.dart';

class NotificationEventScreen extends StatefulWidget {
  const NotificationEventScreen({
    super.key,
    required this.controller,
    required this.eventId,
  });
  final AppController controller;
  final String eventId;

  @override
  State<NotificationEventScreen> createState() =>
      _NotificationEventScreenState();
}

class _NotificationEventScreenState extends State<NotificationEventScreen> {
  RecentEvent? _event;
  Object? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
      _event = null;
    });
    try {
      final event = await widget.controller.loadEvent(widget.eventId);
      if (mounted) setState(() => _event = event);
    } catch (error) {
      if (mounted) setState(() => _error = error);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: widget.controller,
    builder: (context, _) {
      final authenticated = widget.controller.phase == AppPhase.signedIn;
      if (authenticated && _event != null) {
        return _EventScreen(controller: widget.controller, event: _event!);
      }
      final loading = authenticated && _loading;
      return Scaffold(
        appBar: AppBar(title: const Text('Alerte')),
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: loading
                ? const CircularProgressIndicator()
                : Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        !authenticated
                            ? 'Connectez-vous pour consulter cette alerte.'
                            : _error is NetworkFailure
                            ? 'Serveur inaccessible. Verifiez votre connexion.'
                            : 'Alerte indisponible ou acces retire.',
                        textAlign: TextAlign.center,
                      ),
                      if (authenticated) ...[
                        const SizedBox(height: 16),
                        FilledButton.icon(
                          onPressed: _load,
                          icon: const Icon(Icons.refresh),
                          label: const Text('Reessayer'),
                        ),
                      ],
                    ],
                  ),
          ),
        ),
      );
    },
  );
}
