import 'dart:async';

import 'package:material_ui/material_ui.dart';

import '../api.dart';
import '../models.dart';
import 'profile.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({
    super.key,
    required this.api,
    required this.me,
    required this.onSignOut,
  });

  final ApiClient api;
  final Map<String, dynamic> me;
  final Future<void> Function() onSignOut;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _tab = 0;

  @override
  Widget build(BuildContext context) {
    final tabs = [
      HitsTab(api: widget.api),
      FeedTab(api: widget.api),
      ProfileTab(api: widget.api, me: widget.me, onSignOut: widget.onSignOut),
    ];
    return Scaffold(
      appBar: AppBar(
        title: Text(['Hits', 'Placement feed', 'Profile'][_tab]),
        centerTitle: false,
      ),
      body: IndexedStack(index: _tab, children: tabs),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.checklist), label: 'Hits'),
          NavigationDestination(icon: Icon(Icons.newspaper), label: 'Feed'),
          NavigationDestination(icon: Icon(Icons.person_outline), label: 'Profile'),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------- hits
class HitsTab extends StatefulWidget {
  const HitsTab({super.key, required this.api});
  final ApiClient api;

  @override
  State<HitsTab> createState() => _HitsTabState();
}

class _HitsTabState extends State<HitsTab> {
  List<Hit> _hits = const [];
  bool _loading = true;
  String? _error;
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    _load();
    // Same cadence as the web dashboard; the shell also gets pushes, this is the
    // "already looking at the screen" path.
    _poll = Timer.periodic(const Duration(seconds: 20), (_) => _load(silent: true));
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _load({bool silent = false}) async {
    if (!silent) setState(() => _loading = true);
    try {
      final rows = await widget.api.hits();
      if (!mounted) return;
      setState(() {
        _hits = rows.map((e) => Hit.fromJson(e as Map<String, dynamic>)).toList();
        _error = null;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e is ApiException ? 'Server said ${e.status}' : 'Offline';
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading && _hits.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_hits.isEmpty) {
      return RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          children: [
            const SizedBox(height: 120),
            Icon(Icons.inbox_outlined,
                size: 56, color: Theme.of(context).colorScheme.outline),
            const SizedBox(height: 16),
            const Center(child: Text('No shortlists yet')),
            if (_error != null) ...[
              const SizedBox(height: 8),
              Center(child: Text(_error!, style: Theme.of(context).textTheme.bodySmall)),
            ],
          ],
        ),
      );
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView.separated(
        padding: const EdgeInsets.fromLTRB(12, 12, 12, 24),
        itemCount: _hits.length,
        separatorBuilder: (_, _) => const SizedBox(height: 10),
        itemBuilder: (_, i) => _HitCard(hit: _hits[i]),
      ),
    );
  }
}

class _HitCard extends StatelessWidget {
  const _HitCard({required this.hit});
  final Hit hit;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final accent = hit.company.isNotEmpty ? hit.company : 'Shortlist';
    final venue = hit.venueLine;
    final date = hit.dateLine;

    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: scheme.primaryContainer,
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Text(accent,
                      style: TextStyle(
                          fontWeight: FontWeight.w600,
                          fontSize: 13,
                          color: scheme.onPrimaryContainer)),
                ),
                const Spacer(),
                if (date.isNotEmpty)
                  Text(date, style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
                if (!hit.read) ...[
                  const SizedBox(width: 8),
                  Icon(Icons.circle, size: 8, color: scheme.primary),
                ],
              ],
            ),
            const SizedBox(height: 10),
            // The student's own sheet row is the actionable part: where and when.
            if (venue.isNotEmpty)
              Row(
                children: [
                  Icon(Icons.place_outlined, size: 16, color: scheme.primary),
                  const SizedBox(width: 4),
                  Text(venue, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
                ],
              ),
            if (hit.subject.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(hit.subject,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 13, color: scheme.onSurfaceVariant)),
            ],
            if (hit.slotParts.isNotEmpty || hit.summary != null)
              Theme(
                data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
                child: ExpansionTile(
                  tilePadding: EdgeInsets.zero,
                  childrenPadding: const EdgeInsets.only(bottom: 8),
                  title: Text('Details',
                      style: TextStyle(fontSize: 12, color: scheme.primary)),
                  children: [
                    for (final part in hit.slotParts)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 4),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            if (part.key.isNotEmpty)
                              SizedBox(
                                width: 110,
                                child: Text('${part.key}:',
                                    style: TextStyle(
                                        fontSize: 12, color: scheme.onSurfaceVariant)),
                              ),
                            Expanded(
                              child: Text(part.value,
                                  style: const TextStyle(fontSize: 12)),
                            ),
                          ],
                        ),
                      ),
                    if (hit.summary?['category'] != null)
                      Align(
                        alignment: Alignment.centerLeft,
                        child: Text('${hit.summary!['category']}',
                            style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
                      ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------- feed
class FeedTab extends StatefulWidget {
  const FeedTab({super.key, required this.api});
  final ApiClient api;

  @override
  State<FeedTab> createState() => _FeedTabState();
}

class _FeedTabState extends State<FeedTab> {
  List<Mail> _mails = const [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final rows = await widget.api.mails(limit: 50);
      if (!mounted) return;
      setState(() {
        _mails = rows.map((e) => Mail.fromJson(e as Map<String, dynamic>)).toList();
        _loading = false;
      });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading && _mails.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView.separated(
        padding: const EdgeInsets.fromLTRB(12, 12, 12, 24),
        itemCount: _mails.length,
        separatorBuilder: (_, _) => const SizedBox(height: 10),
        itemBuilder: (_, i) => _MailCard(mail: _mails[i]),
      ),
    );
  }
}

class _MailCard extends StatelessWidget {
  const _MailCard({required this.mail});
  final Mail mail;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final summary = mail.summaryText;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Order matters: kind + date, subject, then the summary paragraph,
            // then the yellow "your row" box — same as the web feed.
            Row(
              children: [
                Text(mail.kind.toUpperCase(),
                    style: TextStyle(
                        fontSize: 11,
                        letterSpacing: 0.6,
                        fontWeight: FontWeight.w700,
                        color: scheme.primary)),
                const Spacer(),
                Text(mail.date.split(' ').take(4).join(' '),
                    style: TextStyle(fontSize: 11, color: scheme.onSurfaceVariant)),
              ],
            ),
            const SizedBox(height: 8),
            Text(mail.subject,
                style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
            if (summary.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(summary,
                  style: TextStyle(fontSize: 12.5, color: scheme.onSurfaceVariant)),
            ],
            if (mail.mySlotList.isNotEmpty) ...[
              const SizedBox(height: 10),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: const Color(0x332F2A10),
                  border: Border.all(color: const Color(0xFF6B5B1E)),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final e in mail.mySlotList)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 4),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(e.key,
                                style: const TextStyle(
                                    fontSize: 12, fontWeight: FontWeight.w700)),
                            Text(e.value,
                                style: TextStyle(
                                    fontSize: 11.5, color: scheme.onSurfaceVariant)),
                          ],
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
