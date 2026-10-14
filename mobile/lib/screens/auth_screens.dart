part of '../app.dart';

class _BootScreen extends StatelessWidget {
  const _BootScreen({super.key});

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(
      child: Center(
        child: Semantics(
          label: 'Chargement de Sentinelle Maison',
          child: CircularProgressIndicator(),
        ),
      ),
    ),
  );
}

class LoginScreen extends StatefulWidget {
  const LoginScreen({
    super.key,
    required this.controller,
    required this.openExternalPage,
  });

  final AppController controller;
  final ExternalPageOpener openExternalPage;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _baseUrl;
  late final TextEditingController _identifier;
  late final TextEditingController _deviceName;
  final _password = TextEditingController();
  bool _obscurePassword = true;

  @override
  void initState() {
    super.initState();
    final defaults = widget.controller.defaults;
    _baseUrl = TextEditingController(text: defaults?.baseUrl ?? '');
    _identifier = TextEditingController(text: defaults?.identifier ?? '');
    _deviceName = TextEditingController(
      text: defaults?.deviceName ?? 'Navigateur web',
    );
  }

  @override
  void dispose() {
    _baseUrl.dispose();
    _identifier.dispose();
    _deviceName.dispose();
    _password.dispose();
    super.dispose();
  }

  Uri? _publicUri(String path) {
    final raw = _baseUrl.text.trim();
    if (raw.isEmpty) return null;
    final base = Uri.tryParse(raw.replaceFirst(RegExp(r'/+$'), ''));
    if (base == null || !base.hasScheme) return null;
    return base.resolve(path);
  }

  Future<void> _openPublicPage(String path) async {
    final uri = _publicUri(path);
    if (uri == null) return;
    final opened = await widget.openExternalPage(uri);
    if (!opened && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Impossible d’ouvrir la page.')),
      );
    }
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    await widget.controller.requestMfa(
      baseUrl: _baseUrl.text,
      identifier: _identifier.text,
      password: _password.text,
      deviceName: _deviceName.text,
    );
  }

  @override
  Widget build(BuildContext context) {
    return _PageShell(
      child: Form(
        key: _formKey,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const _BrandHeader(
              title: 'Connexion',
              subtitle: 'Accédez à vos maisons surveillées.',
            ),
            const SizedBox(height: 18),
            _FieldLabel('E-mail ou nom d’utilisateur'),
            TextFormField(
              key: const Key('identifierField'),
              controller: _identifier,
              textInputAction: TextInputAction.next,
              autofillHints: const [AutofillHints.username],
              validator: (value) => value == null || value.trim().isEmpty
                  ? 'Saisissez votre identifiant.'
                  : null,
            ),
            const SizedBox(height: 12),
            _FieldLabel('Mot de passe'),
            TextFormField(
              key: const Key('passwordField'),
              controller: _password,
              obscureText: _obscurePassword,
              textInputAction: TextInputAction.done,
              autofillHints: const [AutofillHints.password],
              onFieldSubmitted: (_) => _submit(),
              decoration: InputDecoration(
                suffixIcon: IconButton(
                  tooltip: _obscurePassword
                      ? 'Afficher le mot de passe'
                      : 'Masquer le mot de passe',
                  onPressed: () =>
                      setState(() => _obscurePassword = !_obscurePassword),
                  icon: Icon(
                    _obscurePassword
                        ? Icons.visibility_outlined
                        : Icons.visibility_off_outlined,
                  ),
                ),
              ),
              validator: (value) => value == null || value.isEmpty
                  ? 'Saisissez votre mot de passe.'
                  : null,
            ),
            const SizedBox(height: 6),
            Wrap(
              spacing: 8,
              runSpacing: 4,
              alignment: WrapAlignment.spaceBetween,
              children: [
                TextButton(
                  key: const Key('forgotPasswordButton'),
                  onPressed: () => _openPublicPage('/mot-de-passe-oublie/'),
                  child: const Text('Mot de passe oublié ?'),
                ),
                TextButton(
                  key: const Key('createAccountButton'),
                  onPressed: () => _openPublicPage('/inscription/'),
                  child: const Text('Créer un compte'),
                ),
              ],
            ),
            if (widget.controller.errorMessage != null) ...[
              const SizedBox(height: 8),
              _ErrorBanner(message: widget.controller.errorMessage!),
            ],
            const SizedBox(height: 14),
            FilledButton.icon(
              key: const Key('loginButton'),
              onPressed: widget.controller.busy ? null : _submit,
              icon: widget.controller.busy
                  ? const SizedBox.square(
                      dimension: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.login_rounded),
              label: Text(
                widget.controller.busy ? 'Connexion…' : 'Se connecter',
              ),
            ),
            const SizedBox(height: 14),
            const _PrivacyNote(),
          ],
        ),
      ),
    );
  }
}

class MfaScreen extends StatefulWidget {
  const MfaScreen({super.key, required this.controller});

  final AppController controller;

  @override
  State<MfaScreen> createState() => _MfaScreenState();
}

class _MfaScreenState extends State<MfaScreen> {
  final _code = TextEditingController();

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  Future<void> _submit() => widget.controller.verifyMfa(_code.text);

  @override
  Widget build(BuildContext context) {
    final challenge = widget.controller.challenge;
    return _PageShell(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const _BrandHeader(
            title: 'Entrez votre code MFA',
            subtitle: 'Validez la connexion sur cet appareil.',
          ),
          const SizedBox(height: 16),
          _InfoBanner(
            icon: Icons.mark_email_unread_outlined,
            text: challenge == null
                ? 'Un code de sécurité est requis.'
                : 'Code envoyé à ${challenge.maskedEmail}.',
          ),
          const SizedBox(height: 14),
          _FieldLabel('Code MFA'),
          TextField(
            key: const Key('mfaCodeField'),
            controller: _code,
            keyboardType: TextInputType.number,
            textInputAction: TextInputAction.done,
            onSubmitted: (_) => _submit(),
          ),
          if (widget.controller.errorMessage != null) ...[
            const SizedBox(height: 8),
            _ErrorBanner(message: widget.controller.errorMessage!),
          ],
          const SizedBox(height: 14),
          FilledButton.icon(
            key: const Key('verifyButton'),
            onPressed: widget.controller.busy ? null : _submit,
            icon: const Icon(Icons.verified_user_outlined),
            label: Text(widget.controller.busy ? 'Vérification…' : 'Vérifier'),
          ),
          const SizedBox(height: 8),
          TextButton(
            onPressed: widget.controller.busy
                ? null
                : widget.controller.backToLogin,
            child: const Text('Retour à la connexion'),
          ),
        ],
      ),
    );
  }
}

class OfflineScreen extends StatelessWidget {
  const OfflineScreen({super.key, required this.controller});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    return _PageShell(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const _Logo(),
          const SizedBox(height: 28),
          Icon(
            Icons.wifi_off_rounded,
            size: 44,
            color: Theme.of(context).colorScheme.primary,
          ),
          const SizedBox(height: 16),
          Text(
            'Serveur inaccessible',
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 8),
          Text(
            controller.errorMessage ??
                'Vérifiez la connexion locale puis réessayez.',
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 18),
          FilledButton.icon(
            onPressed: controller.refresh,
            icon: const Icon(Icons.refresh_rounded),
            label: const Text('Réessayer'),
          ),
          TextButton(
            onPressed: controller.forgetLocalSession,
            child: const Text('Se reconnecter'),
          ),
        ],
      ),
    );
  }
}
