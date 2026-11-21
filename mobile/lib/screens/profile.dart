import 'package:flutter/foundation.dart' show kDebugMode;
import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../notify.dart';
import '../theme.dart';

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
      ((_me['ids'] as List<dynamic>?) ?? const []).map((e) => e as Map<String, dynamic>).toList();

  /// The API speaks in database codes; people read "B.Tech".
  String _divisionLabel(String raw) => switch (raw.trim().toLowerCase()) {
        '' => '',
        'bt' => 'B.Tech',
        'mba' => 'MBA',
        'mca' => 'MCA',
        _ => raw.toUpperCase(),
      };

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
      if (!mounted) return;
      setState(() => _note = r['added'] == true
          ? 'Added ${r['normalized_id']}'
              '${backfilled is int && backfilled > 0 ? " — recovered $backfilled older hit(s)" : ""}'
          : '${r['normalized_id']} is already on your account');
      _idController.clear();
      await _refreshMe();
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _note = e.status == 422
          ? 'That does not look like a register ID'
          : 'Server said ${e.status}');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final email = '${_me['email'] ?? ''}';
    final branch = '${_me['branch'] ?? ''}';
    final division = _divisionLabel('${_me['division'] ?? ''}');
    final subtitle = [branch, division].where((e) => e.isNotEmpty).join(' · ');

    return ListView(
      padding: const EdgeInsets.fromLTRB(14, 14, 14, 28),
      children: [
        Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: R.page),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // identity
                Container(
                  decoration: R.card(),
                  padding: const EdgeInsets.all(13),
                  child: Row(
                    children: [
                      Container(
                        width: 40,
                        height: 40,
                        alignment: Alignment.center,
                        decoration: BoxDecoration(
                          color: R.saffronSoft,
                          shape: BoxShape.circle,
                          border: Border.all(color: const Color(0x4DF4B33D)),
                        ),
                        child: Text(
                          email.isNotEmpty ? email[0].toUpperCase() : '?',
                          style: R.brand.copyWith(fontSize: 17, color: R.saffron),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(email, style: R.subject, overflow: TextOverflow.ellipsis),
                            if (subtitle.isNotEmpty) ...[
                              const SizedBox(height: 2),
                              Text(subtitle, style: R.meta),
                            ],
                          ],
                        ),
                      ),
                      TextButton(
                        onPressed: widget.onSignOut,
                        style: TextButton.styleFrom(foregroundColor: R.ink3),
                        child: const Text('Sign out', style: R.meta),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 18),
                _section('Your register IDs'),
                Container(
                  decoration: R.card(),
                  child: Column(
                    children: [
                      for (final id in _ids)
                        Padding(
                          padding: const EdgeInsets.fromLTRB(13, 11, 13, 0),
                          child: Row(
                            children: [
                              const Icon(Icons.badge_outlined, size: 15, color: R.ink3),
                              const SizedBox(width: 8),
                              Text('${id['register_id'] ?? id['normalized_id'] ?? ''}',
                                  style: R.code),
                            ],
                          ),
                        ),
                      Padding(
                        padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
                        child: Row(
                          children: [
                            Expanded(
                              child: TextField(
                                controller: _idController,
                                textCapitalization: TextCapitalization.characters,
                                style: R.small.copyWith(color: R.ink),
                                cursorColor: R.saffron,
                                decoration: InputDecoration(
                                  isDense: true,
                                  hintText: 'Add NEO ID or register number',
                                  hintStyle: R.meta,
                                  filled: true,
                                  fillColor: R.surface2,
                                  contentPadding:
                                      const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
                                  border: OutlineInputBorder(
                                    borderRadius: BorderRadius.circular(R.rS),
                                    borderSide: BorderSide.none,
                                  ),
                                ),
                                onSubmitted: (_) => _addId(),
                              ),
                            ),
                            const SizedBox(width: 8),
                            SizedBox(
                              width: 44,
                              height: 40,
                              child: FilledButton(
                                onPressed: _busy ? null : _addId,
                                style: FilledButton.styleFrom(
                                  padding: EdgeInsets.zero,
                                  backgroundColor: R.saffron,
                                  foregroundColor: R.saffronInk,
                                ),
                                child: const Icon(Icons.add_rounded, size: 20),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
                if (_note != null) ...[
                  const SizedBox(height: 10),
                  Container(
                    padding: const EdgeInsets.all(11),
                    decoration: R.card(soft: true),
                    child: Text(_note!, style: R.small),
                  ),
                ],
                // Everything below is a developer affordance: harmless in a debug
                // build, noise in a release one. kDebugMode strips it from release.
                if (kDebugMode) ...[
                  const SizedBox(height: 18),
                  _section('Diagnostics (debug only)'),
                  Container(
                    decoration: R.card(),
                    child: Column(
                      children: [
                        _row(Icons.notifications_active_outlined,
                            'Allow notifications and exact alarms',
                            'Android asks separately for "Alarms & reminders"',
                            _askPermissions),
                        const Divider(),
                        _row(Icons.bolt_outlined, 'Test: alarm in 1 minute',
                            'Then lock the phone and wait', _testAlarm),
                        const Divider(),
                        _row(Icons.notification_add_outlined, 'Test: notification now',
                            null, _testNotification),
                      ],
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _section(String text) => Padding(
        padding: const EdgeInsets.only(bottom: 8, left: 2),
        child: Text(text, style: R.meta.copyWith(fontWeight: FontWeight.w700, letterSpacing: 0.3)),
      );

  Widget _row(IconData icon, String title, String? subtitle, Future<void> Function() tap) =>
      InkWell(
        onTap: () async {
          await tap();
          if (mounted) setState(() {});
        },
        child: Padding(
          padding: const EdgeInsets.fromLTRB(13, 12, 13, 12),
          child: Row(
            children: [
              Icon(icon, size: 17, color: R.ink3),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: R.small.copyWith(color: R.ink)),
                    if (subtitle != null) ...[
                      const SizedBox(height: 2),
                      Text(subtitle, style: R.meta),
                    ],
                  ],
                ),
              ),
              const Icon(Icons.chevron_right_rounded, size: 18, color: R.ink3),
            ],
          ),
        ),
      );

  // ---------------------------------------------------------- debug actions
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
}
