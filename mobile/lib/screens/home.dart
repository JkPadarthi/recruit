import 'dart:async';

import 'package:material_ui/material_ui.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api.dart';
import '../models.dart';
import '../notify.dart';
import '../theme.dart';
import 'admin.dart';
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
  final _unread = ValueNotifier<int>(0);

  bool get _isAdmin => widget.me['admin'] == true;

  List<Widget> _tabs() => [
        HitsTab(api: widget.api, unread: _unread,
            myIds: ((widget.me['ids'] as List<dynamic>?) ?? const []).length),
        FeedTab(api: widget.api),
        ProfileTab(api: widget.api, me: widget.me, onSignOut: widget.onSignOut),
        if (_isAdmin)
          AdminScreen(api: widget.api,
              myUserId: (widget.me['id'] as num?)?.toInt() ?? 0),
      ];

  List<NavigationDestination> _destinations() => [
        const NavigationDestination(icon: Icon(Icons.checklist_rounded), label: 'Hits'),
        const NavigationDestination(icon: Icon(Icons.article_outlined), label: 'Feed'),
        const NavigationDestination(icon: Icon(Icons.person_outline), label: 'Profile'),
        if (_isAdmin)
          const NavigationDestination(icon: Icon(Icons.shield_outlined), label: 'Admin'),
      ];

  @override
  void dispose() {
    _unread.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 18,
        title: Row(
          children: [
            const Text('Recruit', style: R.brand),
            const SizedBox(width: 6),
            Container(
              width: 6,
              height: 6,
              decoration: const BoxDecoration(color: R.saffron, shape: BoxShape.circle),
            ),
          ],
        ),
        actions: [
          ValueListenableBuilder<int>(
            valueListenable: _unread,
            builder: (_, n, _) => n == 0
                ? const SizedBox.shrink()
                : Container(
                    margin: const EdgeInsets.only(right: 16),
                    padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
                    decoration: R.pill(bg: R.saffronSoft, border: const Color(0x4DF4B33D)),
                    child: Text('$n new', style: R.meta.copyWith(color: R.saffron)),
                  ),
          ),
        ],
      ),
      body: IndexedStack(index: _tab, children: _tabs()),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: _destinations(),
      ),
    );
  }
}

/// Keeps the reading column at the PWA's 600px and centres it on wide screens.
class _Page extends StatelessWidget {
  const _Page({required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) => Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: R.page),
          child: child,
        ),
      );
}

class _Empty extends StatelessWidget {
  const _Empty({required this.icon, required this.title, this.hint});
  final IconData icon;
  final String title;
  final String? hint;

  @override
  Widget build(BuildContext context) => ListView(
        children: [
          const SizedBox(height: 96),
          Icon(icon, size: 44, color: R.ink3),
          const SizedBox(height: 14),
          Center(child: Text(title, style: R.h1.copyWith(color: R.ink2))),
          if (hint != null) ...[
            const SizedBox(height: 6),
            Center(child: Text(hint!, style: R.meta)),
          ],
        ],
      );
}

// ---------------------------------------------------------------------- hits
class HitsTab extends StatefulWidget {
  const HitsTab({super.key, required this.api, required this.unread, this.myIds = 0});
  final ApiClient api;
  final ValueNotifier<int> unread;
  final int myIds;

  @override
  State<HitsTab> createState() => _HitsTabState();
}

class _HitsTabState extends State<HitsTab> {
  List<Hit> _hits = const [];
  final Set<int> _readNow = {};
  final Set<String> _armed = {};
  bool _loading = true;
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    _load();
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
      final feed = await widget.api.hitsFeed();
      if (!mounted) return;
      setState(() {
        _hits = feed.hits.map((e) => Hit.fromJson(e as Map<String, dynamic>)).toList();
        _loading = false;
      });
      widget.unread.value =
          _hits.where((h) => !h.read && !_readNow.contains(h.id)).length;
      unawaited(_armAlarms(_hits));
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// Arm the T-90/T-30 alarms from the list itself.
  ///
  /// They used to be armed only inside `handlePushData`, which meant a shortlist whose
  /// push never arrived (notifications off at the time, phone dead, or the app installed
  /// after the mail landed) silently had no alarm at all — the one case where the user
  /// finds out 90 minutes late instead of 90 minutes early.
  ///
  /// The tag matches the server's (`recruit-<ingested_id>`), so the alarm ids computed in
  /// scheduleDeadline collide with the push-armed ones and overwrite them instead of
  /// double-buzzing. Re-arming on every 20s poll is therefore harmless, and `_armed`
  /// keeps it cheap.
  Future<void> _armAlarms(List<Hit> hits) async {
    final now = DateTime.now();
    for (final h in hits) {
      if (h.whenIso.isEmpty) continue;
      final at = DateTime.tryParse(h.whenIso);
      if (at == null || !at.isAfter(now)) continue;
      final key = '${h.id}|${h.whenIso}';
      if (_armed.contains(key)) continue;
      _armed.add(key);
      try {
        await Notifier.instance.scheduleDeadline(
          tag: 'recruit-${h.ingestedId}',
          when: at,
          event: [h.company, h.kind].where((x) => x.isNotEmpty).join(' ').trim(),
          body: h.slot,
        );
      } catch (_) {
        // Likely notification permission or exact-alarm permission missing. Forget the
        // key so the next load tries again once the user grants it.
        _armed.remove(key);
      }
    }
  }

  /// The web dashboard has this button and eleven unread dots is exactly when you want
  /// it. Optimistic like the PWA: flip locally, then fire the (idempotent) per-hit calls.
  Future<void> _markAllRead() async {
    final ids = _hits
        .where((h) => !h.read && !_readNow.contains(h.id))
        .map((h) => h.id)
        .toList();
    if (ids.isEmpty) return;
    setState(() => _readNow.addAll(ids));
    widget.unread.value = 0;
    for (final id in ids) {
      unawaited(widget.api.markRead(id).catchError((_) {}));
    }
    await _load(silent: true);
  }

  Future<void> _open(Hit hit) async {
    if (!hit.read && !_readNow.contains(hit.id)) {
      setState(() => _readNow.add(hit.id));
      widget.unread.value = (widget.unread.value - 1).clamp(0, 999);
      unawaited(widget.api.markRead(hit.id).catchError((_) {}));
    }
    if (!mounted) return;
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: R.bg,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(R.rL)),
      ),
      builder: (_) => _HitSheet(hit: hit, icsUrl: widget.api.hitIcsUrl(hit.id)),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_loading && _hits.isEmpty) {
      return const Center(child: CircularProgressIndicator(color: R.saffron));
    }
    if (_hits.isEmpty) {
      return RefreshIndicator(
        color: R.saffron,
        onRefresh: _load,
        child: const _Empty(
          icon: Icons.inbox_outlined,
          title: 'No shortlists yet',
          hint: 'When CDC lists your ID, it lands here.',
        ),
      );
    }
    final unread = _hits.where((h) => !h.read && !_readNow.contains(h.id)).length;
    return _Page(
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 0),
            child: Row(
              children: [
                _statCell('Your hits', '${_hits.length}'),
                const SizedBox(width: 8),
                _statCell('Unread', '$unread'),
                const SizedBox(width: 8),
                _statCell('IDs tracked', '${widget.myIds}'),
              ],
            ),
          ),
          if (unread >= 2)
            Align(
              alignment: Alignment.centerRight,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(0, 2, 8, 0),
                child: TextButton.icon(
                  onPressed: _markAllRead,
                  icon: const Icon(Icons.done_all_rounded, size: 15),
                  style: TextButton.styleFrom(foregroundColor: R.saffron),
                  label: const Text('Mark all read', style: R.meta),
                ),
              ),
            ),
          Expanded(
            child: RefreshIndicator(
              color: R.saffron,
              onRefresh: _load,
              child: ListView.separated(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.fromLTRB(14, 10, 14, 28),
                itemCount: _hits.length,
                separatorBuilder: (_, _) => const SizedBox(height: 9),
                itemBuilder: (_, i) {
                  final h = _hits[i];
                  return _HitCard(
                    hit: h,
                    unread: !h.read && !_readNow.contains(h.id),
                    onTap: () => _open(h),
                  );
                },
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _statCell(String label, String value) => Expanded(
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 9),
          decoration: R.card(soft: true),
          child: Column(
            children: [
              Text(value, style: R.brand.copyWith(fontSize: 17, color: R.saffron)),
              const SizedBox(height: 1),
              Text(label, style: R.meta),
            ],
          ),
        ),
      );
}

class _HitCard extends StatelessWidget {
  const _HitCard({required this.hit, required this.unread, required this.onTap});

  final Hit hit;
  final bool unread;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final tint = R.companyColor(hit.company);
    final date = hit.dateLine;
    final venue = hit.venueLine;

    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(R.rM),
      child: Ink(
        decoration: R.card(),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // unread marker: a 3px saffron edge, like the PWA's dot but calmer
            Container(
              width: 3,
              decoration: BoxDecoration(
                color: unread ? R.saffron : Colors.transparent,
                borderRadius: const BorderRadius.horizontal(left: Radius.circular(R.rM)),
              ),
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(12, 11, 13, 11),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
                          decoration: R.pill(
                              bg: tint.withValues(alpha: 0.16),
                              border: tint.withValues(alpha: 0.35)),
                          child: Text(
                            hit.company.isEmpty ? 'Shortlist' : hit.company,
                            style: R.meta.copyWith(color: tint, fontWeight: FontWeight.w700),
                          ),
                        ),
                        const Spacer(),
                        if (date.isNotEmpty) Text(date, style: R.meta),
                      ],
                    ),
                    if (venue.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          const Icon(Icons.place_rounded, size: 15, color: R.saffron),
                          const SizedBox(width: 5),
                          Text(venue, style: R.venue),
                        ],
                      ),
                    ],
                    if (hit.subject.isNotEmpty) ...[
                      const SizedBox(height: 5),
                      Text(hit.subject,
                          maxLines: 2, overflow: TextOverflow.ellipsis, style: R.small),
                    ],
                  ],
                ),
              ),
            ),
            const Padding(
              padding: EdgeInsets.only(right: 10),
              child: Icon(Icons.chevron_right_rounded, size: 20, color: R.ink3),
            ),
          ],
        ),
      ),
    );
  }
}

/// The full payload behind one tap: every labelled field of your own sheet row,
/// then the summary. This replaces the "Details" chevron that hid the point.
class _HitSheet extends StatelessWidget {
  const _HitSheet({required this.hit, required this.icsUrl});
  final Hit hit;
  final String icsUrl;

  @override
  Widget build(BuildContext context) {
    final prose = hit.summaryProse;
    return SafeArea(
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxHeight: MediaQuery.of(context).size.height * 0.82,
          maxWidth: R.page,
        ),
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(18, 10, 18, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Center(
                child: Container(
                  width: 38,
                  height: 4,
                  decoration: BoxDecoration(
                      color: R.surface3, borderRadius: BorderRadius.circular(99)),
                ),
              ),
              const SizedBox(height: 16),
              Text(hit.company.isEmpty ? 'Shortlist' : hit.company,
                  style: R.h1.copyWith(color: R.companyColor(hit.company))),
              if (hit.dateLine.isNotEmpty) ...[
                const SizedBox(height: 4),
                Text(hit.dateLine, style: R.meta),
              ],
              if (hit.subject.isNotEmpty) ...[
                const SizedBox(height: 12),
                Text(hit.subject, style: R.small.copyWith(color: R.ink2)),
              ],
              const SizedBox(height: 16),
              Container(
                padding: const EdgeInsets.all(14),
                decoration: R.amberPanel(),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final part in hit.slotParts)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 7),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            if (part.key.isNotEmpty)
                              SizedBox(
                                width: 108,
                                child: Text(part.key, style: R.meta),
                              ),
                            Expanded(
                              child: Text(part.value,
                                  style: R.small.copyWith(color: R.ink)),
                            ),
                          ],
                        ),
                      ),
                  ],
                ),
              ),
              if (prose.isNotEmpty) ...[
                const SizedBox(height: 16),
                Text(prose, style: R.body),
              ],
              const SizedBox(height: 18),
              Row(
                children: [
                  Text('Your code: ', style: R.meta),
                  Text(hit.registerId ?? '', style: R.code.copyWith(color: R.saffron)),
                ],
              ),
              // Only when the row carries a time: an alarm from a guessed time is
              // worse than none, and the server refuses the same case with a 409.
              if (hit.slot.isNotEmpty) ...[
                const SizedBox(height: 16),
                OutlinedButton.icon(
                  onPressed: () =>
                      launchUrl(Uri.parse(icsUrl), mode: LaunchMode.externalApplication),
                  icon: const Icon(Icons.calendar_month_outlined, size: 17),
                  label: const Text('Add to calendar · remind me 90 min before'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: R.saffron,
                    side: const BorderSide(color: Color(0x4DF4B33D)),
                    textStyle: R.small,
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(R.rS)),
                  ),
                ),
              ],
            ],
          ),
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

/// The PWA groups "selection" under Shortlists; anything that is not a shortlist or an
/// announcement simply is not counted by a chip (it still shows under All).
String _kindGroup(String k) => k == 'selection' ? 'shortlist' : k;

class _FeedTabState extends State<FeedTab> {
  String _filter = 'all';

  List<Mail> get _shown => _filter == 'all'
      ? _mails
      : _mails.where((m) => _kindGroup(m.kind) == _filter).toList();
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
      return const Center(child: CircularProgressIndicator(color: R.saffron));
    }
    final shown = _shown;
    return _Page(
      child: Column(
        children: [
          _chips(),
          Expanded(
            child: RefreshIndicator(
              color: R.saffron,
              onRefresh: _load,
              child: shown.isEmpty
                  ? _Empty(
                      icon: Icons.inbox_outlined,
                      title: _mails.isEmpty
                          ? 'Nothing yet'
                          : 'No ${_filter}s in the latest mail',
                      hint: _mails.isEmpty
                          ? 'New CDC mails show up here within a few minutes.'
                          : null,
                    )
                  : ListView.separated(
                      physics: const AlwaysScrollableScrollPhysics(),
                      padding: const EdgeInsets.fromLTRB(14, 8, 14, 28),
                      itemCount: shown.length,
                      separatorBuilder: (_, _) => const SizedBox(height: 9),
                      itemBuilder: (_, i) => _MailCard(mail: shown[i]),
                    ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _chips() {
    final counts = <String, int>{'all': _mails.length, 'shortlist': 0, 'announcement': 0};
    for (final m in _mails) {
      final k = _kindGroup(m.kind);
      if (counts.containsKey(k)) counts[k] = counts[k]! + 1;
    }

    Widget chip(String id, String label) {
      final on = _filter == id;
      final n = counts[id] ?? 0;
      return Padding(
        padding: const EdgeInsets.only(right: 7),
        child: InkWell(
          onTap: () => setState(() => _filter = id),
          borderRadius: BorderRadius.circular(99),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 6),
            decoration: BoxDecoration(
              color: on ? R.saffronSoft : R.surface2,
              borderRadius: BorderRadius.circular(99),
              border: Border.all(color: on ? const Color(0x4DF4B33D) : R.line),
            ),
            child: Text(n > 0 ? '$label $n' : label,
                style: R.meta.copyWith(
                    color: on ? R.saffron : R.ink3,
                    fontWeight: on ? FontWeight.w700 : FontWeight.w500)),
          ),
        ),
      );
    }

    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.fromLTRB(14, 10, 14, 0),
      child: Row(
        children: [
          chip('all', 'All'),
          chip('shortlist', 'Shortlists'),
          chip('announcement', 'Announcements'),
        ],
      ),
    );
  }
}

class _MailCard extends StatefulWidget {
  const _MailCard({required this.mail});
  final Mail mail;

  @override
  State<_MailCard> createState() => _MailCardState();
}

class _MailCardState extends State<_MailCard> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final m = widget.mail;
    final prose = m.summaryProse;
    final links = m.linkList;

    return Container(
      decoration: R.card(),
      padding: const EdgeInsets.fromLTRB(13, 11, 13, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // kind tag + date, exactly the PWA's mail-top
          Row(
            children: [
              Text(m.kind.toUpperCase(),
                  style: R.meta.copyWith(
                      color: R.saffron, fontWeight: FontWeight.w700, letterSpacing: 0.8)),
              const Spacer(),
              Text(_shortDate(m.date), style: R.meta),
            ],
          ),
          const SizedBox(height: 7),
          Text(m.subject, style: R.subject),
          if (prose.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              prose,
              style: R.body,
              maxLines: _expanded ? null : 3,
              overflow: _expanded ? null : TextOverflow.ellipsis,
            ),
            if (prose.length > 150)
              InkWell(
                onTap: () => setState(() => _expanded = !_expanded),
                child: Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(_expanded ? 'Show less' : 'Show more',
                      style: R.meta.copyWith(color: R.saffron)),
                ),
              ),
          ],
          if (m.mySlotList.isNotEmpty) ...[
            const SizedBox(height: 10),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(11),
              decoration: R.amberPanel(),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  for (final e in m.mySlotList) ...[
                    Text(e.key, style: R.code.copyWith(color: R.saffron)),
                    const SizedBox(height: 3),
                    Text(e.value, style: R.small.copyWith(fontSize: 12)),
                    const SizedBox(height: 6),
                  ],
                ],
              ),
            ),
          ],
          if (links.isNotEmpty) ...[
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [for (final l in links) _LinkChip(link: l)],
            ),
          ],
        ],
      ),
    );
  }

  /// "Fri, 20 Nov 2026 20:19:39 +0530" -> "20 Nov 2026"
  String _shortDate(String raw) {
    final parts = raw.split(RegExp(r'\s+'));
    if (parts.length >= 4) return '${parts[1]} ${parts[2]} ${parts[3]}';
    return raw.split(',').first;
  }
}

class _LinkChip extends StatelessWidget {
  const _LinkChip({required this.link});
  final MailLink link;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: () => launchUrl(Uri.parse(link.url), mode: LaunchMode.externalApplication),
      borderRadius: BorderRadius.circular(999),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
        decoration: R.pill(border: R.lineStrong),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              link.kind == 'test'
                  ? Icons.bolt_rounded
                  : link.kind == 'register'
                      ? Icons.edit_document
                      : Icons.link_rounded,
              size: 14,
              color: R.saffron,
            ),
            const SizedBox(width: 6),
            Text(link.label, style: R.meta.copyWith(color: R.ink, fontWeight: FontWeight.w600)),
          ],
        ),
      ),
    );
  }
}
