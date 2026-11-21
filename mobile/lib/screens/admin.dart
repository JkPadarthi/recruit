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
      final s = await widget.api.adminStats();
      if (!mounted) return;
      setState(() {
        _stats = s;
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
