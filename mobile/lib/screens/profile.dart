import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../notify.dart';

class ProfileTab extends StatefulWidget {
  const ProfileTab({
    super.key,
    required this.api,
    required this.me,
    required this.onSignOut,
  });

  final ApiClient api;
  final Map<String, dynamic> me;
  final Future<void> Function() onSignOut;

  @override
  State<ProfileTab> createState() => _ProfileTabState();
}

class _ProfileTabState extends State<ProfileTab> {
  final _idController = TextEditingController();
  late Map<String, dynamic> _me = Map<String, dynamic>.from(widget.me);
  bool _busy = false;
  String? _note;

  @override
  void dispose() {
    _idController.dispose();
    super.dispose();
  }

  List<Map<String, dynamic>> get _ids =>
      ((_me['ids'] as List<dynamic>?) ?? const [])
          .map((e) => e as Map<String, dynamic>)
          .toList();

  Future<void> _refreshMe() async {
    final me = await widget.api.me();
    if (mounted) setState(() => _me = me);
  }

  Future<void> _addId() async {
    final value = _idController.text.trim();
    if (value.isEmpty) return;
    setState(() {
      _busy = true;
      _note = null;
    });
    try {
      final r = await widget.api.addId(value);
      final backfilled = r['backfilled'];
      setState(() => _note = r['added'] == true
          ? 'Added ${r['normalized_id']}'
              '${backfilled is int && backfilled > 0 ? " — recovered $backfilled older hit(s)" : ""}'
          : '${r['normalized_id']} is already on your account');
      _idController.clear();
      await _refreshMe();
    } on ApiException catch (e) {
      setState(() => _note = e.status == 422
          ? 'That does not look like a register ID'
          : 'Server said ${e.status}');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // ------------------------------------------------------------ developer row
  Future<void> _askPermissions() async {
    final report = await Notifier.instance.requestPermissions();
    if (!mounted) return;
    setState(() => _note = report.replaceAll('\n', ' · '));
  }

  Future<void> _testNotification() async {
    await Notifier.instance.show(
      tag: 'flutter-test',
      title: '✅ Test notification',
      body: 'If you can see this, the channel works.',
    );
  }

  /// 91 minutes out, so the T-90 alarm fires about a minute from now.
  Future<void> _testAlarm() async {
    final when = DateTime.now().add(const Duration(minutes: 91));
    final n = await Notifier.instance.scheduleDeadline(
      tag: 'flutter-test-${DateTime.now().millisecondsSinceEpoch}',
      when: when,
      event: 'DEBUG deadline',
      body: 'Scheduled by the test button',
    );
    if (!mounted) return;
    setState(() => _note = n == 0
        ? 'Nothing scheduled — check exact-alarm permission'
        : 'Armed $n alarm(s); T-90 fires in ~1 min. Lock the phone.');
  }

  Future<void> _showPending() async {
    final pending = await Notifier.instance.pending();
    if (!mounted) return;
    setState(() => _note = pending.isEmpty
        ? 'No alarms armed'
        : pending.map((p) => '${p.title ?? ""} — ${p.body ?? ""}').join('\n'));
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final email = '${_me['email'] ?? ''}';
    final branch = '${_me['branch'] ?? ''}';
    final division = '${_me['division'] ?? ''}';

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Card(
          child: ListTile(
            leading: CircleAvatar(
              backgroundColor: scheme.primaryContainer,
              child: Text(email.isNotEmpty ? email[0].toUpperCase() : '?'),
            ),
            title: Text(email),
            subtitle: Text([branch, division].where((e) => e.isNotEmpty).join(' · ')),
            trailing: TextButton(
              onPressed: widget.onSignOut,
              child: const Text('Sign out'),
            ),
          ),
        ),
        const SizedBox(height: 16),
        Text('Your register IDs', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 8),
        Card(
          child: Column(
            children: [
              for (final id in _ids)
                ListTile(
                  dense: true,
                  leading: const Icon(Icons.badge_outlined, size: 18),
                  title: Text('${id['register_id'] ?? id['normalized_id'] ?? ''}'),
                ),
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 4, 12, 12),
                child: Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _idController,
                        textCapitalization: TextCapitalization.characters,
                        decoration: const InputDecoration(
                          isDense: true,
                          hintText: 'Add NEO ID or register number',
                          border: OutlineInputBorder(),
                        ),
                        onSubmitted: (_) => _addId(),
                      ),
                    ),
                    const SizedBox(width: 8),
                    IconButton.filled(
                      onPressed: _busy ? null : _addId,
                      icon: const Icon(Icons.add),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        Text('Notifications', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 8),
        Card(
          child: Column(
            children: [
              ListTile(
                leading: const Icon(Icons.notifications_active_outlined),
                title: const Text('Allow notifications and exact alarms'),
                subtitle: const Text('Android asks separately for "Alarms & reminders"'),
                onTap: _askPermissions,
              ),
              const Divider(height: 1),
              ListTile(
                leading: const Icon(Icons.bolt_outlined),
                title: const Text('Test: alarm in 1 minute'),
                subtitle: const Text('Then lock the phone and wait'),
                onTap: _testAlarm,
              ),
              const Divider(height: 1),
              ListTile(
                leading: const Icon(Icons.notification_add_outlined),
                title: const Text('Test: notification now'),
                onTap: _testNotification,
              ),
              const Divider(height: 1),
              ListTile(
                leading: const Icon(Icons.schedule_outlined),
                title: const Text('Show armed alarms'),
                onTap: _showPending,
              ),
            ],
          ),
        ),
        if (_note != null) ...[
          const SizedBox(height: 12),
          Card(
            color: scheme.surfaceContainerHighest,
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Text(_note!, style: const TextStyle(fontSize: 12.5)),
            ),
          ),
        ],
      ],
    );
  }
}
