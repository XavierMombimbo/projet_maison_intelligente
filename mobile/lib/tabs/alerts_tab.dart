part of '../app.dart';

class _AlertsTab extends StatefulWidget {
  const _AlertsTab({required this.summary, required this.controller});

  final AccountSummary summary;
  final AppController controller;

  @override
  State<_AlertsTab> createState() => _AlertsTabState();
}

class _AlertsTabState extends State<_AlertsTab> {
  var _events = <RecentEvent>[];
  var _page = 1;
  var _hasMore = false;
  var _loading = true;
  var _loadingMore = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _events = widget.summary.recentEvents;
    _loadPage(reset: true);
  }

  @override
  void didUpdateWidget(covariant _AlertsTab oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.summary.eventCount != widget.summary.eventCount ||
        oldWidget.summary.recentEvents != widget.summary.recentEvents) {
      _events = widget.summary.recentEvents;
      _loadPage(reset: true);
    }
  }

  Future<void> _loadPage({bool reset = false}) async {
    if (reset) {
      _page = 1;
      setState(() {
        _loading = true;
        _error = null;
      });
    } else {
      setState(() => _loadingMore = true);
    }
    try {
      final page = await widget.controller.loadEvents(page: _page);
      if (!mounted) return;
      setState(() {
        _events = reset ? page.items : [..._events, ...page.items];
        _hasMore = page.hasNext;
        _page = page.page + 1;
      });
    } on ApiFailure catch (error) {
      if (!mounted) return;
      setState(() => _error = error.message);
    } finally {
      if (mounted) {
        setState(() {
          _loading = false;
          _loadingMore = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: () => _loadPage(reset: true),
      child: ListView(
        key: const PageStorageKey('alerts-tab'),
        physics: const AlwaysScrollableScrollPhysics(),
        padding: _screenPadding(context),
        children: [
          const _ScreenTitle(
            eyebrow: 'Alertes',
            title: 'Historique des alertes',
            description: 'Priorités, confiance et décisions récentes.',
          ),
          if (widget.controller.errorMessage != null) ...[
            const SizedBox(height: 8),
            _ErrorBanner(message: widget.controller.errorMessage!),
          ],
          if (_error != null) ...[
            const SizedBox(height: 8),
            _ErrorBanner(message: _error!),
          ],
          const SizedBox(height: 12),
          if (_loading)
            const Center(child: CircularProgressIndicator())
          else if (_events.isEmpty)
            const _EmptyEvents()
          else
            ..._events.map(
              (event) => Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: _EventCard(
                  event: event,
                  onTap: () => _openEvent(context, widget.controller, event),
                ),
              ),
            ),
          if (_hasMore) ...[
            const SizedBox(height: 4),
            OutlinedButton.icon(
              onPressed: _loadingMore ? null : () => _loadPage(),
              icon: _loadingMore
                  ? const SizedBox.square(
                      dimension: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.expand_more_rounded),
              label: const Text('Charger plus'),
            ),
          ],
        ],
      ),
    );
  }
}
