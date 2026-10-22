part of 'app.dart';

TextStyle _heading(BuildContext context, {double size = 18}) => TextStyle(
  fontSize: size,
  fontWeight: FontWeight.w700,
  height: 1.25,
  color: Theme.of(context).brightness == Brightness.dark ? Colors.white : _navy,
  letterSpacing: 0,
);

void _openCamera(
  BuildContext context,
  AppController controller,
  MobileCamera camera,
) {
  Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) => _CameraScreen(controller: controller, camera: camera),
    ),
  );
}

void _openEvent(
  BuildContext context,
  AppController controller,
  RecentEvent event,
) {
  Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) => _EventScreen(controller: controller, event: event),
    ),
  );
}

class _OverviewTab extends StatelessWidget {
  const _OverviewTab({
    required this.summary,
    required this.controller,
    required this.onCameras,
    required this.onAlerts,
  });
  final AccountSummary summary;
  final AppController controller;
  final VoidCallback onCameras;
  final VoidCallback onAlerts;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final active = summary.activeCameraCount > 0;
    return RefreshIndicator(
      onRefresh: controller.refresh,
      child: ListView(
        key: const PageStorageKey('dashboard-tab'),
        physics: const AlwaysScrollableScrollPhysics(),
        padding: _screenPadding(context),
        children: [
          Text(
            'Bonjour ${summary.username}',
            style: _heading(context, size: 22),
          ),
          const SizedBox(height: 4),
          Text(
            'Gardez un œil sur votre maison.',
            style: TextStyle(fontSize: 14, color: colors.onSurfaceVariant),
          ),
          const SizedBox(height: 14),
          Material(
            color: active ? _green : colors.surfaceContainerHighest,
            borderRadius: BorderRadius.circular(10),
            clipBehavior: Clip.antiAlias,
            child: InkWell(
              onTap: onCameras,
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Row(
                  children: [
                    Icon(
                      Icons.verified_user_outlined,
                      size: 36,
                      color: active ? Colors.white : colors.onSurface,
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            active
                                ? 'Protection active'
                                : 'Surveillance en pause',
                            style: _heading(context).copyWith(
                              color: active ? Colors.white : colors.onSurface,
                            ),
                          ),
                          const SizedBox(height: 2),
                          Text(
                            active
                                ? 'Surveillance activée'
                                : 'Aucune caméra active',
                            style: TextStyle(
                              fontSize: 13,
                              color: active ? Colors.white : colors.onSurface,
                            ),
                          ),
                          const SizedBox(height: 2),
                          Text(
                            '${summary.activeCameraCount} / ${summary.cameraCount} caméras actives',
                            style: TextStyle(
                              fontSize: 11,
                              color: active
                                  ? Colors.white
                                  : colors.onSurfaceVariant,
                            ),
                          ),
                        ],
                      ),
                    ),
                    Icon(
                      Icons.chevron_right,
                      size: 20,
                      color: active ? Colors.white : colors.onSurface,
                    ),
                  ],
                ),
              ),
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              _SummaryItem(
                icon: Icons.home_outlined,
                value: '${summary.houseCount}',
                label: 'Maisons',
              ),
              _SummaryItem(
                icon: Icons.videocam_outlined,
                value: '${summary.cameraCount}',
                label: 'Caméras',
                onTap: onCameras,
              ),
              _SummaryItem(
                icon: Icons.notifications_none,
                value: '${summary.eventCount}',
                label: 'Événements',
                onTap: onAlerts,
              ),
            ],
          ),
          if (controller.errorMessage != null) ...[
            const SizedBox(height: 8),
            _ErrorBanner(message: controller.errorMessage!),
          ],
          const SizedBox(height: 12),
          _SectionLink(title: 'Mes caméras', onTap: onCameras),
          const SizedBox(height: 6),
          if (summary.cameras.isEmpty)
            const _InfoBanner(
              icon: Icons.videocam_off_outlined,
              text: 'Aucune caméra associée à votre compte.',
            )
          else
            _CameraGrid(
              cameras: summary.cameras.take(2).toList(),
              controller: controller,
            ),
          const SizedBox(height: 14),
          _SectionLink(title: 'Activité récente', onTap: onAlerts),
          const SizedBox(height: 6),
          if (summary.recentEvents.isEmpty)
            const _EmptyEvents()
          else
            ...summary.recentEvents
                .take(3)
                .map(
                  (event) => Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: _EventCard(
                      event: event,
                      onTap: () => _openEvent(context, controller, event),
                    ),
                  ),
                ),
        ],
      ),
    );
  }
}

class _HousesTab extends StatefulWidget {
  const _HousesTab({required this.controller, required this.summary});

  final AppController controller;
  final AccountSummary summary;

  @override
  State<_HousesTab> createState() => _HousesTabState();
}

class _HousesTabState extends State<_HousesTab> {
  late Future<List<MobileHouse>> _houses;

  Future<void> _openSettings(Widget screen) async {
    await Navigator.of(context).push<void>(MaterialPageRoute(builder: (_) => screen));
    if (mounted) {
      try { await _refresh(); } catch (_) { /* Existing list error handles reload failures. */ }
    }
  }

  Future<void> _openHouseForm([MobileHouse? house]) async {
    final saved = await Navigator.of(context).push<bool>(MaterialPageRoute(
      builder: (_) => house == null
          ? HouseCreateScreen(controller: widget.controller)
          : HouseEditScreen(controller: widget.controller, house: house),
    ));
    if (saved != true || !mounted) return;
    try { await _refresh(); } catch (_) { /* FutureBuilder displays the load error. */ }
  }

  @override
  void initState() {
    super.initState();
    _houses = widget.controller.loadHouses();
  }

  Future<void> _refresh() async {
    final next = widget.controller.loadHouses();
    setState(() {
      _houses = next;
    });
    await Future.wait([widget.controller.refresh(), next]);
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView(
        key: const PageStorageKey('houses-tab'),
        physics: const AlwaysScrollableScrollPhysics(),
        padding: _screenPadding(context),
        children: [
          const _ScreenTitle(
            eyebrow: 'Espaces protégés',
            title: 'Maisons',
            description: 'Vos maisons, rôles et caméras associées.',
          ),
          Align(alignment: Alignment.centerRight, child: Wrap(children: [
            IconButton(tooltip: 'Invitations', icon: const Icon(Icons.mail_outline),
              onPressed: () => _openSettings(InvitationsScreen(controller: widget.controller))),
            IconButton(
            tooltip: 'Ajouter une maison', icon: const Icon(Icons.add_home_outlined),
            onPressed: () => _openHouseForm(),
          )])),
          const SizedBox(height: 14),
          FutureBuilder<List<MobileHouse>>(
            future: _houses,
            builder: (context, snapshot) {
              if (snapshot.hasError) {
                return const _ErrorBanner(
                  message: 'Impossible de charger les maisons.',
                );
              }
              if (!snapshot.hasData) {
                return const Center(child: CircularProgressIndicator());
              }
              if (snapshot.data!.isEmpty) {
                return const _InfoBanner(
                  icon: Icons.apartment_outlined,
                  text: 'Aucune maison associée à votre compte.',
                );
              }
              return Column(
                children: snapshot.data!
                    .map(
                      (house) => Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: _HouseTile(
                          house: house,
                          onEdit: house.role == 'owner' ? () => _openHouseForm(house) : null,
                          onSchedule: () => _openSettings(HouseScheduleScreen(controller: widget.controller, house: house)),
                          onMembers: house.role == 'owner' ? () => _openSettings(HouseMembersScreen(controller: widget.controller, house: house)) : null,
                          cameraCount: widget.summary.cameras.where((camera) {
                            return camera.houseId == house.id ||
                                (camera.houseId == null &&
                                    camera.houseName == house.name);
                          }).length,
                        ),
                      ),
                    )
                    .toList(),
              );
            },
          ),
        ],
      ),
    );
  }
}

class _HouseTile extends StatelessWidget {
  const _HouseTile({required this.house, required this.cameraCount, required this.onSchedule, this.onEdit, this.onMembers});

  final MobileHouse house;
  final int cameraCount;
  final VoidCallback? onEdit;
  final VoidCallback onSchedule;
  final VoidCallback? onMembers;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final role = switch (house.role) {
      'owner' => 'Propriétaire',
      'family' => 'Membre de la famille',
      'guest' => 'Invité',
      _ => 'Membre',
    };
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: colors.outlineVariant),
        boxShadow: [_cardShadow(context)],
      ),
      child: Row(
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: colors.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(8),
            ),
            child: Icon(
              Icons.apartment_outlined,
              color: colors.onSurface,
              size: 20,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  house.name,
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  '$role · ${house.timezone}',
                  style: TextStyle(color: colors.onSurfaceVariant),
                ),
                const SizedBox(height: 2),
                Text(
                  '$cameraCount ${cameraCount > 1 ? 'caméras' : 'caméra'}',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
          ),
          PopupMenuButton<String>(tooltip: 'Reglages de la maison',
            onSelected: (value) {
              if (value == 'schedule') onSchedule();
              if (value == 'members') onMembers?.call();
              if (value == 'edit') onEdit?.call();
            }, itemBuilder: (_) => [
              const PopupMenuItem(value: 'schedule', child: Text('Horaires de surveillance')),
              if (onMembers != null) const PopupMenuItem(value: 'members', child: Text('Membres')),
              if (onEdit != null) const PopupMenuItem(value: 'edit', child: Text('Modifier la maison')),
            ]),
        ],
      ),
    );
  }
}

class _SummaryItem extends StatelessWidget {
  const _SummaryItem({
    required this.icon,
    required this.value,
    required this.label,
    this.onTap,
  });
  final IconData icon;
  final String value;
  final String label;
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) => Expanded(
    child: InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Column(
          children: [
            Icon(
              icon,
              color: Theme.of(context).colorScheme.onSurface,
              size: 20,
            ),
            const SizedBox(height: 3),
            Text(
              value,
              style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
            ),
            Text(label, style: const TextStyle(fontSize: 11)),
          ],
        ),
      ),
    ),
  );
}

class _SectionLink extends StatelessWidget {
  const _SectionLink({required this.title, required this.onTap});
  final String title;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => Row(
    children: [
      Expanded(child: Text(title, style: _heading(context, size: 16))),
      TextButton(
        onPressed: onTap,
        child: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [Text('Voir tout'), Icon(Icons.chevron_right, size: 16)],
        ),
      ),
    ],
  );
}

class _CameraGrid extends StatelessWidget {
  const _CameraGrid({required this.cameras, required this.controller});
  final List<MobileCamera> cameras;
  final AppController controller;
  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final columns = MediaQuery.textScalerOf(context).scale(14) > 20
          ? 1
          : constraints.maxWidth >= 700
          ? 3
          : constraints.maxWidth < 240
          ? 1
          : 2;
      final width = (constraints.maxWidth - (columns - 1) * 8) / columns;
      return Wrap(
        spacing: 8,
        runSpacing: 8,
        children: cameras
            .map(
              (camera) => SizedBox(
                width: width,
                child: Material(
                  color: Theme.of(context).colorScheme.surface,
                  borderRadius: BorderRadius.circular(10),
                  clipBehavior: Clip.antiAlias,
                  child: InkWell(
                    onTap: () => _openCamera(context, controller, camera),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        _CapturePreview(
                          controller: controller,
                          eventId: camera.captureEventId,
                          ratio: 1.6,
                          compact: true,
                        ),
                        Padding(
                          padding: const EdgeInsets.fromLTRB(10, 8, 4, 10),
                          child: Row(
                            children: [
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      camera.name,
                                      maxLines: 2,
                                      overflow: TextOverflow.ellipsis,
                                      style: const TextStyle(
                                        fontWeight: FontWeight.w700,
                                      ),
                                    ),
                                    const SizedBox(height: 2),
                                    _CameraState(camera: camera),
                                  ],
                                ),
                              ),
                              IconButton(
                                tooltip: 'Détails de ${camera.name}',
                                icon: const Icon(Icons.more_vert, size: 18),
                                onPressed: () =>
                                    _openCamera(context, controller, camera),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            )
            .toList(),
      );
    },
  );
}

class _CameraState extends StatelessWidget {
  const _CameraState({required this.camera});
  final MobileCamera camera;
  @override
  Widget build(BuildContext context) {
    final color = camera.active
        ? Theme.of(context).colorScheme.primary
        : Theme.of(context).colorScheme.onSurfaceVariant;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(Icons.circle, size: 8, color: color),
        const SizedBox(width: 5),
        Flexible(
          child: Text(
            camera.active ? 'Surveillance active' : 'En pause',
            style: TextStyle(fontSize: 11, color: color),
          ),
        ),
      ],
    );
  }
}

class _CapturePreview extends StatefulWidget {
  const _CapturePreview({
    required this.controller,
    required this.eventId,
    this.ratio = 1.25,
    this.compact = false,
  });
  final AppController controller;
  final String? eventId;
  final double ratio;
  final bool compact;
  @override
  State<_CapturePreview> createState() => _CapturePreviewState();
}

class _CapturePreviewState extends State<_CapturePreview> {
  Future<Uint8List>? _image;
  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(_CapturePreview oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.eventId != widget.eventId) _load();
  }

  void _load() {
    _image = widget.eventId == null
        ? null
        : widget.controller.monitoring?.loadCapture(widget.eventId!);
  }

  Widget _placeholder(String text, IconData icon) => ColoredBox(
    color: Theme.of(context).colorScheme.surfaceContainerHighest,
    child: Center(
      child: Padding(
        padding: const EdgeInsets.all(8),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              icon,
              size: widget.compact ? 24 : 40,
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
            const SizedBox(height: 6),
            Text(
              text,
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: widget.compact ? 11 : 13),
            ),
          ],
        ),
      ),
    ),
  );
  @override
  Widget build(BuildContext context) => ClipRRect(
    borderRadius: BorderRadius.circular(10),
    child: AspectRatio(
      aspectRatio: widget.ratio,
      child: _image == null
          ? _placeholder('Aucune capture', Icons.videocam_outlined)
          : FutureBuilder<Uint8List>(
              future: _image,
              builder: (context, snapshot) {
                if (snapshot.hasError) {
                  return _placeholder(
                    'Capture indisponible',
                    Icons.broken_image_outlined,
                  );
                }
                if (!snapshot.hasData) {
                  return const Center(child: CircularProgressIndicator());
                }
                return Stack(
                  fit: StackFit.expand,
                  children: [
                    Image.memory(
                      snapshot.data!,
                      fit: BoxFit.contain,
                      semanticLabel: 'Capture de la caméra',
                      errorBuilder: (_, _, _) => _placeholder(
                        'Image illisible',
                        Icons.broken_image_outlined,
                      ),
                    ),
                    Positioned(
                      top: 10,
                      left: 10,
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 8,
                          vertical: 4,
                        ),
                        decoration: BoxDecoration(
                          color: const Color(0xDD0F172A),
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: const Text(
                          'CAPTURE',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 10,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                    ),
                  ],
                );
              },
            ),
    ),
  );
}

class _CamerasTab extends StatefulWidget {
  const _CamerasTab({required this.controller});
  final AppController controller;
  @override
  State<_CamerasTab> createState() => _CamerasTabState();
}

class _CamerasTabState extends State<_CamerasTab> {
  int _filter = 0;

  Future<void> _addCamera() async {
    final saved = await Navigator.of(context).push<String>(MaterialPageRoute(
      builder: (_) => CameraFormScreen(controller: widget.controller),
    ));
    if (saved != null && mounted) await widget.controller.refresh();
  }
  @override
  Widget build(BuildContext context) {
    final cameras = widget.controller.summary!.cameras
        .where((c) => _filter == 0 || c.active == (_filter == 1))
        .toList();
    return RefreshIndicator(
      onRefresh: widget.controller.refresh,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: _screenPadding(context),
        children: [
          Row(children: [
            Expanded(child: Text('Mes caméras', style: _heading(context, size: 20))),
            IconButton(tooltip: 'Ajouter une caméra',
              onPressed: widget.controller.usingCachedData ? null : _addCamera,
              icon: const Icon(Icons.add)),
          ]),
          const SizedBox(height: 6),
          Text('${widget.controller.summary!.cameraCount} caméras associées'),
          const SizedBox(height: 14),
          SegmentedButton<int>(
            showSelectedIcon: false,
            expandedInsets: EdgeInsets.zero,
            style: const ButtonStyle(
              minimumSize: WidgetStatePropertyAll(Size(0, 48)),
              padding: WidgetStatePropertyAll(
                EdgeInsets.symmetric(horizontal: 4),
              ),
              visualDensity: VisualDensity(horizontal: -4, vertical: -2),
              textStyle: WidgetStatePropertyAll(TextStyle(fontSize: 11)),
            ),
            segments: const [
              ButtonSegment(
                value: 0,
                icon: Icon(Icons.home_outlined, size: 18),
                label: Text('Toutes', maxLines: 1, softWrap: false),
              ),
              ButtonSegment(
                value: 1,
                icon: Icon(Icons.shield_outlined, size: 18),
                label: Text('Actives', maxLines: 1, softWrap: false),
              ),
              ButtonSegment(
                value: 2,
                icon: Icon(Icons.pause_circle_outline, size: 18),
                label: Text('En pause', maxLines: 1, softWrap: false),
              ),
            ],
            selected: {_filter},
            onSelectionChanged: (value) =>
                setState(() => _filter = value.first),
          ),
          const SizedBox(height: 14),
          if (cameras.isEmpty)
            const _InfoBanner(
              icon: Icons.videocam_off_outlined,
              text: 'Aucune caméra dans cette sélection.',
            )
          else
            _CameraGrid(cameras: cameras, controller: widget.controller),
        ],
      ),
    );
  }
}

class _CameraScreen extends StatefulWidget {
  const _CameraScreen({required this.controller, required this.camera});
  final AppController controller;
  final MobileCamera camera;
  @override
  State<_CameraScreen> createState() => _CameraScreenState();
}

class _CameraScreenState extends State<_CameraScreen> {
  Future<void> _pairCamera() async {
    await Navigator.of(context).push<void>(MaterialPageRoute(
      builder: (_) => CameraPairingScreen(controller: widget.controller, camera: widget.camera),
    ));
    if (mounted) await widget.controller.refresh();
  }
  String? _renamed;

  Future<void> _renameCamera() async {
    final name = await Navigator.of(context).push<String>(MaterialPageRoute(
      builder: (_) => CameraFormScreen(controller: widget.controller, camera: widget.camera, initialName: _renamed),
    ));
    if (name != null && mounted) {
      setState(() => _renamed = name);
      await widget.controller.refresh();
    }
  }
  late bool _active;
  bool? _appliedActive;
  DateTime? _appliedAt;
  bool _busy = false;
  String? _error;
  final List<RecentEvent> _events = [];
  bool _eventsLoading = true;
  bool _eventsLoadingMore = false;
  bool _eventsHasMore = false;
  int _eventsPage = 0;
  String? _eventsError;
  @override
  void initState() {
    super.initState();
    _active = widget.camera.active;
    _appliedActive = widget.camera.appliedActive;
    _appliedAt = widget.camera.appliedAt;
    if (widget.controller.usingCachedData) {
      _events.addAll(
        widget.controller.summary!.recentEvents.where(
          (event) => event.cameraId == widget.camera.id,
        ),
      );
      _eventsLoading = false;
    } else {
      _loadEvents(reset: true);
    }
  }

  Future<void> _loadEvents({bool reset = false}) async {
    if (_eventsLoadingMore) return;
    setState(() {
      _eventsError = null;
      if (reset) {
        _eventsLoading = true;
      } else {
        _eventsLoadingMore = true;
      }
    });
    try {
      final result = await widget.controller.loadEvents(
        cameraId: widget.camera.id,
        page: reset ? 1 : _eventsPage + 1,
      );
      if (!mounted) return;
      setState(() {
        if (reset) _events.clear();
        _events.addAll(result.items);
        _eventsPage = result.page;
        _eventsHasMore = result.hasNext;
      });
    } on ApiFailure catch (error) {
      if (mounted) setState(() => _eventsError = error.message);
    } finally {
      if (mounted) {
        setState(() {
          _eventsLoading = false;
          _eventsLoadingMore = false;
        });
      }
    }
  }

  Future<void> _setActive(bool value) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.controller.monitoring!.setMonitoring(
        widget.camera.id,
        value,
      );
      if (!mounted) return;
      setState(() => _active = value);
      await widget.controller.refresh();
      MobileCamera? refreshed;
      for (final camera in widget.controller.summary?.cameras ?? const []) {
        if (camera.id == widget.camera.id) {
          refreshed = camera;
          break;
        }
      }
      final current = refreshed;
      if (mounted && current != null) {
        setState(() {
          _appliedActive = current.appliedActive;
          _appliedAt = current.appliedAt;
        });
      }
    } on ApiFailure catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _fullscreen() => Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) => Scaffold(
        appBar: AppBar(title: Text(widget.camera.name)),
        body: Center(
          child: InteractiveViewer(
            child: _CapturePreview(
              controller: widget.controller,
              eventId: widget.camera.captureEventId,
              ratio: 1,
            ),
          ),
        ),
      ),
    ),
  );
  @override
  Widget build(BuildContext context) {
    final camera = widget.camera;
    return Scaffold(
      appBar: AppBar(
        centerTitle: true,
        title: Column(
          children: [
            Text(
              'Caméra · ${_renamed ?? camera.name}',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: _heading(context, size: 18),
            ),
            Text(
              _active ? 'Activation demandée' : 'Arrêt demandé',
              style: const TextStyle(fontSize: 11),
            ),
          ],
        ),
      ),
      bottomNavigationBar: _DetailNavigation(
        controller: widget.controller,
        index: 2,
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 720),
          child: ListView(
            padding: _screenPadding(context),
            children: [
              _CapturePreview(
                controller: widget.controller,
                eventId: camera.captureEventId,
              ),
              const SizedBox(height: 8),
              if (camera.canControl)
                Align(alignment: Alignment.centerRight, child: IconButton(
                  tooltip: 'Renommer la caméra',
                  onPressed: _busy || widget.controller.usingCachedData ? null : _renameCamera,
                  icon: const Icon(Icons.edit_outlined),
                )),
              if (camera.canControl && camera.pairingStatus == 'unpaired')
                TextButton.icon(onPressed: widget.controller.usingCachedData ? null : _pairCamera,
                  icon: const Icon(Icons.link), label: const Text('Appairer la caméra')),
              TextButton.icon(onPressed: widget.controller.usingCachedData ? null : () =>
                Navigator.of(context).push<void>(MaterialPageRoute(builder: (_) =>
                  CameraPreferencesScreen(controller: widget.controller, camera: camera))),
                icon: const Icon(Icons.notifications_outlined), label: const Text('Mes notifications')),
              Text(
                'Dernière capture · ${camera.houseName}',
                style: TextStyle(
                  fontSize: 11,
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ),
              const SizedBox(height: 12),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const _CameraTool(
                    icon: Icons.volume_off_outlined,
                    label: 'Son',
                    tooltip: 'Audio non disponible',
                  ),
                  _CameraTool(
                    icon: Icons.photo_camera_outlined,
                    label: 'Capture',
                    tooltip: 'Consulter la dernière capture',
                    onTap: camera.captureEventId == null ? null : _fullscreen,
                  ),
                  _CameraTool(
                    icon: Icons.fullscreen,
                    label: 'Agrandir',
                    tooltip: 'Agrandir la capture',
                    onTap: camera.captureEventId == null ? null : _fullscreen,
                  ),
                  _CameraTool(
                    icon: _active ? Icons.pause : Icons.play_arrow_outlined,
                    label: _active ? 'Pause' : 'Activer',
                    tooltip: 'Modifier la surveillance',
                    onTap:
                        _busy ||
                            !camera.canControl ||
                            widget.controller.monitoring == null
                        ? null
                        : () => _setActive(!_active),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Text(
                'Détection intelligente',
                style: _heading(context, size: 18),
              ),
              const SizedBox(height: 6),
              SwitchListTile.adaptive(
                contentPadding: EdgeInsets.zero,
                secondary: const Icon(Icons.directions_walk),
                title: const Text('Surveillance'),
                subtitle: Text(
                  _busy
                      ? 'Envoi de la demande…'
                      : _active
                      ? 'État demandé : active'
                      : 'État demandé : en pause',
                ),
                value: _active,
                onChanged:
                    _busy ||
                        !camera.canControl ||
                        widget.controller.monitoring == null
                    ? null
                    : _setActive,
              ),
              const Divider(height: 1),
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: Icon(
                  _appliedActive == _active
                      ? Icons.check_circle_outline
                      : Icons.sync_rounded,
                ),
                title: const Text('État appliqué par la passerelle'),
                subtitle: Text(_appliedStateLabel()),
              ),
              const Divider(height: 1),
              const ListTile(
                contentPadding: EdgeInsets.zero,
                leading: Icon(Icons.notifications_none),
                title: Text('Notifications'),
                subtitle: Text('Consultables dans l’onglet Alertes'),
                trailing: Icon(Icons.info_outline, size: 20),
              ),
              if (_error != null) _ErrorBanner(message: _error!),
              const SizedBox(height: 12),
              Text('Dernières détections', style: _heading(context, size: 18)),
              const SizedBox(height: 6),
              if (_eventsError != null) ...[
                _ErrorBanner(message: _eventsError!),
                const SizedBox(height: 8),
              ],
              if (_eventsLoading)
                const Center(child: CircularProgressIndicator())
              else if (_events.isEmpty)
                const _EmptyEvents()
              else
                ..._events.map(
                  (event) => Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: _EventCard(
                      event: event,
                      onTap: () =>
                          _openEvent(context, widget.controller, event),
                    ),
                  ),
                ),
              if (_eventsHasMore) ...[
                const SizedBox(height: 4),
                OutlinedButton.icon(
                  onPressed: _eventsLoadingMore ? null : () => _loadEvents(),
                  icon: _eventsLoadingMore
                      ? const SizedBox.square(
                          dimension: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.expand_more_rounded),
                  label: const Text('Charger plus'),
                ),
              ],
              const SizedBox(height: 12),
              const _InfoBanner(
                icon: Icons.lock_outline,
                text:
                    'Captures d’événements uniquement. Aucun flux vidéo permanent vers le serveur.',
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _appliedStateLabel() {
    final applied = _appliedActive;
    if (applied == null) {
      return 'Aucun accusé reçu de la passerelle.';
    }
    final state = applied ? 'Active' : 'En pause';
    final suffix = _appliedAt == null ? '' : ' · ${_formatDate(_appliedAt)}';
    if (applied != _active) {
      return '$state$suffix · nouvelle demande en attente';
    }
    return '$state$suffix';
  }
}

class _CameraTool extends StatelessWidget {
  const _CameraTool({
    required this.icon,
    required this.label,
    required this.tooltip,
    this.onTap,
  });
  final IconData icon;
  final String label;
  final String tooltip;
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) => Expanded(
    child: Column(
      children: [
        IconButton.filledTonal(
          tooltip: tooltip,
          onPressed: onTap,
          icon: Icon(icon),
          style: IconButton.styleFrom(
            minimumSize: const Size(56, 48),
            foregroundColor: Theme.of(context).colorScheme.onSurface,
            backgroundColor: Theme.of(
              context,
            ).colorScheme.surfaceContainerHighest,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(8),
            ),
          ),
        ),
        const SizedBox(height: 2),
        Text(
          label,
          textAlign: TextAlign.center,
          style: const TextStyle(fontSize: 11),
        ),
      ],
    ),
  );
}

class _EventCard extends StatelessWidget {
  const _EventCard({required this.event, this.onTap});
  final RecentEvent event;
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final urgent = event.priorityLevel >= 80;
    final color = colors.onSurface;
    return Material(
      color: colors.surface,
      borderRadius: BorderRadius.circular(8),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(10),
          child: Row(
            children: [
              CircleAvatar(
                radius: 18,
                backgroundColor: color.withValues(alpha: 0.10),
                child: Icon(_eventIcon(event.type), color: color, size: 18),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      event.hasProbableWeapon ? 'Personne détectée avec port d’arme probable' : _eventTitle(event.type),
                      style: const TextStyle(
                        fontWeight: FontWeight.w700,
                        fontSize: 13,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '${event.cameraName} · ${_formatDate(event.observedAt)}',
                      style: TextStyle(
                        fontSize: 11,
                        color: colors.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Wrap(
                      spacing: 8,
                      runSpacing: 4,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        _PriorityPill(
                          label: event.priorityLabel,
                          urgent: urgent,
                        ),
                        if (event.confidence != null)
                          Text(
                            '${(event.confidence! * 100).round()} %',
                            style: TextStyle(
                              fontSize: 11,
                              color: colors.onSurfaceVariant,
                            ),
                          ),
                        if (event.isKnownPresence)
                          const Text(
                            'Présence connue · notification silencieuse',
                            style: TextStyle(fontSize: 11),
                          )
                        else if (event.grouped)
                          const Text(
                            'Notification silencieuse',
                            style: TextStyle(fontSize: 11),
                          ),
                        if (event.status != 'new')
                          Text(
                            event.status == 'false_alarm'
                                ? 'Fausse alerte'
                                : 'Confirmée',
                            style: const TextStyle(fontSize: 11),
                          ),
                      ],
                    ),
                  ],
                ),
              ),
              if (onTap != null) const Icon(Icons.chevron_right, size: 20),
            ],
          ),
        ),
      ),
    );
  }
}

class _EventScreen extends StatefulWidget {
  const _EventScreen({required this.controller, required this.event});
  final AppController controller;
  final RecentEvent event;
  @override
  State<_EventScreen> createState() => _EventScreenState();
}

class _EventScreenState extends State<_EventScreen> {
  late RecentEvent _event;
  bool _busy = false;
  String? _error;
  @override
  void initState() {
    super.initState();
    _event = widget.event;
  }

  Future<void> _decide(String decision) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(
          decision == 'confirmed'
              ? 'Confirmer cette intrusion ?'
              : 'Classer comme fausse alerte ?',
        ),
        content: const Text(
          'Cette décision sera enregistrée pour tous les membres autorisés.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Annuler'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Confirmer'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final result = await widget.controller.monitoring!.decideEvent(
        _event.id,
        decision,
      );
      if (!mounted) return;
      setState(() => _event = result);
      await widget.controller.refresh();
    } on ApiFailure catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final cameras =
        widget.controller.summary?.cameras
            .where((c) => c.id == _event.cameraId)
            .toList() ??
        [];
    final canDecide =
        !_busy &&
        _event.canControl &&
        _event.status == 'new' &&
        !_event.isKnownPresence &&
        widget.controller.monitoring != null;
    return Scaffold(
      appBar: AppBar(
        centerTitle: true,
        title: Text('Détail de l’alerte', style: _heading(context, size: 18)),
      ),
      bottomNavigationBar: _DetailNavigation(
        controller: widget.controller,
        index: 3,
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 720),
          child: ListView(
            padding: _screenPadding(context),
            children: [
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: colors.surfaceContainerHighest,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Row(
                  children: [
                    CircleAvatar(
                      backgroundColor: colors.surfaceContainerHighest,
                      child: Icon(
                        _eventIcon(_event.type),
                        color: colors.onSurface,
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            _event.hasProbableWeapon ? 'Personne détectée avec port d’arme probable' : _eventTitle(_event.type),
                            style: _heading(
                              context,
                              size: 18,
                            ).copyWith(color: colors.onSurface),
                          ),
                          const SizedBox(height: 3),
                          Text(
                            '${_event.cameraName} · ${_formatDate(_event.observedAt)}',
                            style: const TextStyle(fontSize: 12),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 12),
              _CapturePreview(
                controller: widget.controller,
                eventId: _event.hasCapture ? _event.id : null,
                ratio: 1.2,
              ),
              const SizedBox(height: 14),
              Text(
                _event.isKnownPresence
                    ? 'Présence volontaire reconnue'
                    : _event.status == 'new'
                    ? 'Vérifiez la situation'
                    : _event.status == 'false_alarm'
                    ? 'Fausse alerte'
                    : 'Intrusion confirmée',
                textAlign: TextAlign.center,
                style: _heading(context),
              ),
              const SizedBox(height: 8),
              Text(
                _event.reason.isNotEmpty
                    ? _event.reason
                    : 'Une détection a été enregistrée par ${_event.cameraName}.',
                textAlign: TextAlign.center,
                style: TextStyle(color: colors.onSurfaceVariant),
              ),
              const SizedBox(height: 12),
              Wrap(
                alignment: WrapAlignment.center,
                spacing: 12,
                children: [
                  _PriorityPill(
                    label: _event.priorityLabel,
                    urgent: _event.priorityLevel >= 80,
                  ),
                  if (_event.confidence != null)
                    Text('Confiance ${(100 * _event.confidence!).round()} %'),
                  if (_event.isKnownPresence)
                    const Text('Notification silencieuse')
                  else if (_event.grouped)
                    const Text('Notification silencieuse'),
                ],
              ),
              const SizedBox(height: 18),
              FilledButton.icon(
                onPressed: cameras.isEmpty
                    ? null
                    : () => _openCamera(
                        context,
                        widget.controller,
                        cameras.first,
                      ),
                icon: const Icon(Icons.videocam_outlined),
                label: const Text('Voir la caméra'),
              ),
              const SizedBox(height: 10),
              OutlinedButton.icon(
                onPressed: canDecide ? () => _decide('confirmed') : null,
                icon: const Icon(Icons.check),
                label: Text(
                  _busy ? 'Enregistrement…' : 'Confirmer l’intrusion',
                ),
              ),
              const SizedBox(height: 8),
              TextButton(
                onPressed: canDecide ? () => _decide('false_alarm') : null,
                child: const Text('Fausse alerte'),
              ),
              if (_error != null) _ErrorBanner(message: _error!),
            ],
          ),
        ),
      ),
    );
  }
}

class _DetailNavigation extends StatelessWidget {
  const _DetailNavigation({required this.controller, required this.index});
  final AppController controller;
  final int index;
  @override
  Widget build(BuildContext context) => NavigationBar(
    selectedIndex: index,
    onDestinationSelected: (value) {
      controller.selectTab(value);
      Navigator.of(context).popUntil((route) => route.isFirst);
    },
    destinations: const [
      NavigationDestination(
        icon: Icon(Icons.home_outlined),
        selectedIcon: Icon(Icons.home),
        label: 'Accueil',
      ),
      NavigationDestination(
        icon: Icon(Icons.apartment_outlined),
        selectedIcon: Icon(Icons.apartment),
        label: 'Maisons',
      ),
      NavigationDestination(
        icon: Icon(Icons.videocam_outlined),
        selectedIcon: Icon(Icons.videocam),
        label: 'Caméras',
      ),
      NavigationDestination(
        icon: Icon(Icons.notifications_none),
        selectedIcon: Icon(Icons.notifications),
        label: 'Alertes',
      ),
      NavigationDestination(
        icon: Icon(Icons.shield_outlined),
        selectedIcon: Icon(Icons.shield),
        label: 'Sécurité',
      ),
    ],
  );
}
