part of '../app.dart';

class CameraPairingScreen extends StatefulWidget {
  const CameraPairingScreen({super.key, required this.controller, required this.camera});
  final AppController controller;
  final MobileCamera camera;
  @override
  State<CameraPairingScreen> createState() => _CameraPairingScreenState();
}

class _CameraPairingScreenState extends State<CameraPairingScreen> with WidgetsBindingObserver {
  CameraPairingCode? _code;
  String _status = 'unknown';
  String? _error;
  bool _busy = false;
  bool _checking = false;
  bool _foreground = true;
  int _epoch = 0;
  int _ticks = 0;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _checkStatus();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!_foreground) return;
      if (_code != null) {
        setState(() {
          if (!_code!.expiresAt.isAfter(DateTime.now())) _code = null;
        });
      }
      if (++_ticks % 5 == 0) {
        _checkStatus();
      }
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
    // Never retain a visible pairing secret across backgrounding.
    if (!_foreground) {
      _epoch++;
      setState(() { _code = null; _busy = false; });
    } else {
      _checkStatus();
    }
  }

  Future<void> _checkStatus() async {
    if (_checking || _busy || !_foreground) return;
    _checking = true;
    try {
      final status = await widget.controller.cameraPairing.loadPairingStatus(widget.camera.id);
      if (!mounted || !_foreground) return;
      setState(() {
        if (_status == 'unknown' || status != 'unpaired') _error = null;
        _status = status;
        if (status != 'unpaired') _code = null;
      });
    } catch (error) {
      if (mounted && _foreground) {
        setState(() {
          _code = null;
          _status = 'unknown';
          _error = error is ApiFailure ? error.message : 'Verification impossible.';
        });
      }
    } finally {
      _checking = false;
    }
  }

  Future<void> _generate() async {
    if (_busy || _status != 'unpaired') return;
    final epoch = ++_epoch;
    setState(() { _busy = true; _code = null; _error = null; });
    try {
      final code = await widget.controller.cameraPairing.createPairingCode(widget.camera.id);
      if (mounted && _foreground && epoch == _epoch) {
        setState(() => _code = code.expiresAt.isAfter(DateTime.now()) ? code : null);
      }
    } catch (error) {
      if (mounted && epoch == _epoch) {
        setState(() => _error = error is ApiFailure ? error.message : 'Generation impossible.');
      }
    } finally {
      if (mounted && epoch == _epoch) setState(() => _busy = false);
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    _code = null;
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final code = _code;
    final remaining = code == null ? 0 : code.expiresAt.difference(DateTime.now()).inSeconds.clamp(0, 300);
    final label = switch (_status) {
      'paired' => 'Camera appairee',
      'revoked' => 'Camera revoquee',
      'unpaired' => 'En attente d\'appairage',
      _ => 'Etat indisponible',
    };
    return Scaffold(
      appBar: AppBar(title: const Text('Appairage')),
      body: SafeArea(child: Center(child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 600),
        child: ListView(padding: const EdgeInsets.all(20), children: [
          Text(widget.camera.name, style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 16),
          Text(label),
          if (code != null) ...[
            const SizedBox(height: 24),
            Text(code.code, textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 36, fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            Text('Expiration : ${remaining ~/ 60}:${(remaining % 60).toString().padLeft(2, '0')}',
              textAlign: TextAlign.center),
          ],
          if (_error != null) ...[
            const SizedBox(height: 16), _ErrorBanner(message: _error!),
          ],
          const SizedBox(height: 24),
          if (_status == 'unpaired' && widget.camera.canControl)
            FilledButton.icon(onPressed: _busy ? null : _generate,
              icon: _busy ? const SizedBox(width: 18, height: 18,
                child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.key_outlined),
              label: Text(code == null ? 'Generer un code' : 'Remplacer le code')),
          if (_status == 'unknown')
            TextButton.icon(onPressed: _checkStatus, icon: const Icon(Icons.refresh),
              label: const Text('Reessayer')),
        ]),
      ))),
    );
  }
}
