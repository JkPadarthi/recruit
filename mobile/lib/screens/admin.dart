import 'package:flutter/services.dart' show Clipboard, ClipboardData;
import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../theme.dart';

/// The PWA's admin screen, ported: who is registered, what they watch, how many
/// devices they have, plus the two operator actions (poll now, send a test push).
class AdminScreen extends StatefulWidget {
  const AdminScreen({super.key, required this.api, required this.myUserId});

  final ApiClient api;
  final int myUserId;

  @override
  State<AdminScreen> createState() => _AdminScreenState();
}

class _AdminScreenState extends State<AdminScreen> {
  Map<String, dynamic>? _stats;
  List<Map<String, dynamic>> _requests = const [];
  final Map<int, String> _links = {};      // user_id -> freshly minted link
  bool _loading = true;
  String? _note;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      // Heterogeneous futures, so wait on Object and narrow explicitly.
      final results = await Future.wait<Object>([
        widget.api.adminStats(),
        widget.api.adminResetRequests(),
      ]);
      final s = results[0] as Map<String, dynamic>;
      final reqs = results[1] as List<Map<String, dynamic>>;
      if (!mounted) return;
      setState(() {
        _stats = s;
        _requests = reqs;
        _loading = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _note = e.status == 403 ? 'This account is not an admin.' : 'Server said ${e.status}';
        _loading = false;
      });
    }
  }

  Future<void> _poll() async {
    setState(() => _busy = true);
    try {
      final r = await widget.api.adminPoll();
      if (!mounted) return;
      setState(() => _note = 'Polled: $r');
      await _load();
    } catch (e) {
      if (mounted) setState(() => _note = 'Poll failed: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _makeLinkFor(int userId, String email) async {
    setState(() => _busy = true);
    try {
      final r = await widget.api.adminResetLink(userId);
      final url = '${r['url'] ?? ''}';
      if (!mounted) return;
      setState(() {
        _links[userId] = url;
        _note = 'Link for $email is valid ${r['expires_in_min']} min.';
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _note = e.detail);
    } catch (e) {
      if (mounted) setState(() => _note = 'Could not create a link: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _testPushTo(int userId, String email) async {
    setState(() => _busy = true);
    try {
      final r = await widget.api.adminTestPush(userId);
      if (!mounted) return;
      setState(() => _note =
          'Test to $email: sent to ${r['sent'] ?? 0} of ${r['live_devices'] ?? 0} live device(s).');
    } on ApiException catch (e) {
      if (mounted) setState(() => _note = e.detail);
    } catch (e) {
      if (mounted) setState(() => _note = 'Push failed: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _testPush() async {
    setState(() => _busy = true);
    try {
      final r = await widget.api.adminTestPush(widget.myUserId);
      if (!mounted) return;
      setState(() => _note = 'Test push: $r');
    } catch (e) {
      if (mounted) setState(() => _note = 'Push failed: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading && _stats == null) {
      return const Center(child: CircularProgressIndicator(color: R.saffron));
    }
    final users = ((_stats?['users'] as List<dynamic>?) ?? const [])
        .map((e) => e as Map<String, dynamic>)
        .toList();

    return RefreshIndicator(
      color: R.saffron,
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 28),
        children: [
          Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: R.page),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      _stat('Mails', '${_stats?['ingested'] ?? 0}'),
                      const SizedBox(width: 9),
                      _stat('Hits', '${_stats?['hits'] ?? 0}'),
                      const SizedBox(width: 9),
                      _stat('Users', '${users.length}'),
                    ],
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: _busy ? null : _poll,
                          icon: const Icon(Icons.refresh_rounded, size: 16),
                          label: const Text('Poll CDC now'),
                          style: OutlinedButton.styleFrom(
                            foregroundColor: R.ink,
                            side: const BorderSide(color: R.lineStrong),
                            textStyle: R.small,
                            shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(R.rS)),
                          ),
                        ),
                      ),
                      const SizedBox(width: 9),
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: _busy ? null : _testPush,
                          icon: const Icon(Icons.send_rounded, size: 16),
                          label: const Text('Test push'),
                          style: OutlinedButton.styleFrom(
                            foregroundColor: R.saffron,
                            side: const BorderSide(color: Color(0x4DF4B33D)),
                            textStyle: R.small,
                            shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(R.rS)),
                          ),
                        ),
                      ),
                    ],
                  ),
                  if (_note != null) ...[
                    const SizedBox(height: 10),
                    Container(
                      padding: const EdgeInsets.all(11),
                      decoration: R.card(soft: true),
                      child: Text(_note!, style: R.small),
                    ),
                  ],
                  const SizedBox(height: 18),
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8, left: 2),
                    child: Text('Password resets waiting',
                        style: R.meta.copyWith(fontWeight: FontWeight.w700)),
                  ),
                  if (_requests.isEmpty)
                    Container(
                      padding: const EdgeInsets.all(11),
                      decoration: R.card(soft: true),
                      child: Text('Nobody is waiting on a link.', style: R.meta),
                    )
                  else
                    for (final r in _requests) _requestRow(r),
                  const SizedBox(height: 18),
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8, left: 2),
                    child: Text('Registered accounts',
                        style: R.meta.copyWith(fontWeight: FontWeight.w700)),
                  ),
                  for (final u in users) _userRow(u),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _stat(String label, String value) => Expanded(
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 12),
          decoration: R.card(),
          child: Column(
            children: [
              Text(value, style: R.brand.copyWith(fontSize: 20, color: R.saffron)),
              const SizedBox(height: 2),
              Text(label, style: R.meta),
            ],
          ),
        ),
      );

  Widget _linkBox(String link) => Padding(
        padding: const EdgeInsets.only(top: 6, right: 4),
        child: Row(
          children: [
            Expanded(
              child: SelectableText(link,
                  style: R.code.copyWith(fontSize: 11, color: R.ink2), maxLines: 2),
            ),
            IconButton(
              visualDensity: VisualDensity.compact,
              tooltip: 'Copy link',
              onPressed: () async {
                await Clipboard.setData(ClipboardData(text: link));
                if (mounted) setState(() => _note = 'Link copied.');
              },
              icon: const Icon(Icons.copy_rounded, size: 16, color: R.saffron),
            ),
          ],
        ),
      );

  Widget _requestRow(Map<String, dynamic> r) {
    final userId = (r['user_id'] as num?)?.toInt() ?? 0;
    final age = (r['age_min'] as num?)?.toInt() ?? 0;
    final link = _links[userId];
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.fromLTRB(12, 10, 8, 10),
      decoration: R.card(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text('${r['email'] ?? ''}',
                    style: R.small.copyWith(color: R.ink),
                    overflow: TextOverflow.ellipsis),
              ),
              Text(age < 60 ? '${age}m ago' : '${age ~/ 60}h ago', style: R.meta),
              const SizedBox(width: 4),
              if (link == null)
                TextButton(
                  onPressed: _busy ? null : () => _makeLinkFor(userId, '${r['email'] ?? ''}'),
                  style: TextButton.styleFrom(foregroundColor: R.saffron),
                  child: const Text('Create link', style: R.meta),
                ),
            ],
          ),
          if (link != null) _linkBox(link),
        ],
      ),
    );
  }

  Widget _userRow(Map<String, dynamic> u) {
    final ids = ((u['ids'] as List<dynamic>?) ?? const []).map((e) => '$e').toList();
    final devices = (u['devices'] as num?)?.toInt() ?? 0;
    final admin = u['admin'] == true;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 11),
      decoration: R.card(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text('${u['email'] ?? ''}',
                    style: R.small.copyWith(color: R.ink),
                    overflow: TextOverflow.ellipsis),
              ),
              if (admin)
                Container(
                  margin: const EdgeInsets.only(right: 6),
                  padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
                  decoration: R.pill(bg: R.saffronSoft),
                  child: Text('ADMIN', style: R.meta.copyWith(color: R.saffron, fontSize: 10)),
                ),
              Text('$devices device${devices == 1 ? "" : "s"}', style: R.meta),
            ],
          ),
          const SizedBox(height: 4),
          Row(
            children: [
              TextButton.icon(
                onPressed: _busy || devices == 0
                    ? null
                    : () => _testPushTo((u['id'] as num).toInt(), '${u['email'] ?? ''}'),
                icon: const Icon(Icons.notifications_active_outlined, size: 15),
                style: TextButton.styleFrom(
                    foregroundColor: R.saffron, visualDensity: VisualDensity.compact),
                label: const Text('Test', style: R.meta),
              ),
              TextButton.icon(
                onPressed: _busy
                    ? null
                    : () => _makeLinkFor((u['id'] as num).toInt(), '${u['email'] ?? ''}'),
                icon: const Icon(Icons.key_rounded, size: 15),
                style: TextButton.styleFrom(
                    foregroundColor: R.ink2, visualDensity: VisualDensity.compact),
                label: const Text('Reset', style: R.meta),
              ),
            ],
          ),
          if (_links[(u['id'] as num).toInt()] != null)
            _linkBox(_links[(u['id'] as num).toInt()]!),
          if (ids.isNotEmpty) ...[
            const SizedBox(height: 6),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final id in ids)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: R.pill(bg: R.surface3),
                    child: Text(id, style: R.code.copyWith(fontSize: 11.5)),
                  ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}
