// Typed views of the API payloads. Every field is defensive: the server has
// shipped this shape for months, but a missing key must never crash a list.

class Hit {
  Hit({
    required this.id,
    required this.ingestedId,
    required this.read,
    required this.firstSeenAt,
    required this.subject,
    required this.kind,
    required this.company,
    required this.slot,
    this.summary,
    this.registerId,
  });

  final int id;
  final int ingestedId;
  final bool read;
  final String firstSeenAt;
  final String subject;
  final String kind;
  final String company;
  final String slot;             // the student's own sheet row
  final Map<String, dynamic>? summary;
  final String? registerId;

  static Hit fromJson(Map<String, dynamic> j) => Hit(
        id: (j['id'] as num?)?.toInt() ?? 0,
        ingestedId: (j['ingested_id'] as num?)?.toInt() ?? 0,
        read: j['read'] == true,
        firstSeenAt: '${j['first_seen_at'] ?? ''}',
        subject: '${j['subject'] ?? ''}',
        kind: '${j['kind'] ?? ''}',
        company: '${j['company'] ?? ''}',
        slot: '${j['slot'] ?? ''}',
        summary: j['summary'] is Map<String, dynamic>
            ? j['summary'] as Map<String, dynamic>
            : null,
        registerId: j['normalized_id'] as String?,
      );

  /// "ApplicationNo.: HCLTFP2461546 · Skill Stack: ... · Date & Time: ..."
  /// The card shows the pieces, not the raw row.
  List<MapEntry<String, String>> get slotParts {
    final out = <MapEntry<String, String>>[];
    for (final seg in slot.split('·')) {
      final t = seg.trim();
      if (t.isEmpty) continue;
      final i = t.indexOf(': ');
      if (i > 0) {
        out.add(MapEntry(t.substring(0, i).trim(), t.substring(i + 2).trim()));
      } else {
        out.add(MapEntry('', t));
      }
    }
    return out;
  }

  String get dateLine => _pick('date');
  String get venueLine => _pick('venue');

  /// First value whose label contains [needle]; '' when absent.
  /// (Dart core has no firstOrNull and this does not justify a package.)
  String _pick(String needle) {
    for (final e in slotParts) {
      if (e.key.toLowerCase().contains(needle)) return e.value;
    }
    return '';
  }
}

class Mail {
  Mail({
    required this.id,
    required this.subject,
    required this.from,
    required this.date,
    required this.kind,
    required this.summary,
    required this.mySlots,
    required this.links,
    required this.summaryStatus,
  });

  final int id;
  final String subject;
  final String from;
  final String date;
  final String kind;
  final Map<String, dynamic>? summary;
  final Map<String, dynamic> mySlots;
  final List<dynamic> links;
  final String summaryStatus;

  static Mail fromJson(Map<String, dynamic> j) => Mail(
        id: (j['id'] as num?)?.toInt() ?? 0,
        subject: '${j['subject'] ?? ''}',
        from: '${j['from'] ?? ''}',
        date: '${j['date'] ?? ''}',
        kind: '${j['kind'] ?? ''}',
        summary: j['summary'] is Map<String, dynamic>
            ? j['summary'] as Map<String, dynamic>
            : null,
        mySlots: j['my_slots'] is Map<String, dynamic>
            ? j['my_slots'] as Map<String, dynamic>
            : const {},
        links: j['links'] is List ? j['links'] as List<dynamic> : const [],
        summaryStatus: '${j['summary_status'] ?? ''}',
      );

  /// The summary paragraph for the feed card, or '' when there isn't one yet.
  String get summaryText {
    final s = summary;
    if (s == null) return '';
    final cat = '${s['category'] ?? ''}'.trim();
    final role = '${s['role'] ?? ''}'.trim();
    final pkg = '${s['package'] ?? ''}'.trim();
    final parts = [if (cat.isNotEmpty) cat, if (role.isNotEmpty) role, if (pkg.isNotEmpty) pkg];
    return parts.join(' · ');
  }

  /// This user's own rows from the sheet, one per code they hold.
  List<MapEntry<String, String>> get mySlotList =>
      mySlots.entries.map((e) => MapEntry(e.key, '${e.value}')).toList();
}
