// Typed views of the API payloads. Every field is defensive: a missing key must
// never crash a list.

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
    this.whenIso = '',
  });

  final int id;
  final int ingestedId;
  final bool read;
  final String firstSeenAt;
  final String subject;
  final String kind;
  final String company;
  final String slot; // the student's own sheet row

  /// The reporting time as an ISO instant, straight from the server's own parse of the
  /// sheet row. Empty when the row has no readable time — never guess one locally.
  final String whenIso;
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
        whenIso: '${j['when_iso'] ?? ''}',
      );

  /// "ApplicationNo.: HCLTFP2461546 · Skill Stack: … · Venue: …" -> pairs.
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

  static final _dateRe = RegExp(r'\b\d{1,2}-\d{1,2}-\d{4}\b');
  static final _timeRe =
      RegExp(r'\b\d{1,2}[.:]\d{2}\s*[ap]\.?\s*m\b', caseSensitive: false);
  static final _venueRe =
      RegExp(r'(?:Reporting venue|Venue|Location)\s*:\s*([^\u00b7]+)', caseSensitive: false);
  static final _roomRe = RegExp(r'\b(?:PRP|TT|MB|SJT|GDN|SMV|AN)\s?-?\s?\d{2,4}\b');

  /// The date, matched by SHAPE rather than by position.
  ///
  /// An Accenture row carries no "Date & Time" label, and picking the first
  /// labelled segment put an application number on screen where the date
  /// belonged ("26247961"). A value is only a date if it looks like one.
  String get dateLine {
    final d = _dateRe.firstMatch(slot)?.group(0);
    if (d == null) return '';
    final t = _timeRe.firstMatch(slot)?.group(0);
    return t == null ? d : '$d (${t.replaceAll('.', ':')})';
  }

  String get venueLine {
    final labelled = _venueRe.firstMatch(slot)?.group(1)?.trim();
    if (labelled != null && labelled.isNotEmpty) return labelled;
    return _roomRe.firstMatch(slot)?.group(0) ?? '';
  }

  /// The LLM's prose summary — the same string the PWA renders under the subject.
  String get summaryProse => '${summary?['summary'] ?? ''}'.trim();
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

  /// Prose first (what the PWA shows), structured fields only as a fallback.
  String get summaryProse {
    final prose = '${summary?['summary'] ?? ''}'.trim();
    if (prose.isNotEmpty) return prose;
    final s = summary;
    if (s == null) return '';
    final cat = '${s['category'] ?? ''}'.trim();
    final role = '${s['role'] ?? ''}'.trim();
    final pkg = '${s['package'] ?? ''}'.trim();
    return [cat, role, pkg].where((e) => e.isNotEmpty).join(' · ');
  }

  /// This user's own rows from the sheet, one per code they hold.
  List<MapEntry<String, String>> get mySlotList =>
      mySlots.entries.map((e) => MapEntry(e.key, '${e.value}')).toList();

  /// Tappable links from the mail — a test URL or a registration form. Without
  /// these, a "🧪 Test link available" push leads nowhere inside the app.
  List<MailLink> get linkList {
    final out = <MailLink>[];
    for (final raw in links) {
      final url = '$raw'.trim();
      if (url.isEmpty || !url.startsWith('http')) continue;
      out.add(MailLink(url));
    }
    return out;
  }
}

/// A link found in a CDC mail, with a human label derived from its URL.
class MailLink {
  MailLink(this.url);

  final String url;

  String get host {
    final u = Uri.tryParse(url);
    return u?.host ?? url;
  }

  /// "test", "register" or "open" — the same vocabulary the server uses.
  String get kind {
    final low = url.toLowerCase();
    if (low.contains('test') || low.contains('exam') || low.contains('assess')) {
      return 'test';
    }
    if (low.contains('regist') || low.contains('form') || low.contains('apply')) {
      return 'register';
    }
    return 'open';
  }

  String get label => switch (kind) {
        'test' => 'Open test link',
        'register' => 'Register',
        _ => 'Open link',
      };
}
