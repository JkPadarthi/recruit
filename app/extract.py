"""ID discovery + mail classification (deterministic; proven from the watchman).
Extracts every register ID / shortlist code from text + spreadsheet cells, and
classifies a mail as shortlist vs announcement."""
from __future__ import annotations

import csv
import datetime as dt
import re

from .util import looks_like_id, normalize_id

# Reporting times are ALWAYS IST: VIT is in Vellore and the sheets are local.
_IST = dt.timezone(dt.timedelta(hours=5, minutes=30), "IST")
_SLOT_DATE_RE = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b")
# '2:30 pm' / '2.30 pm' / '10:00am' — a 24h value with no am/pm is not a slot time.
_SLOT_TIME_RE = re.compile(r"\b(\d{1,2})[.:](\d{2})\s*([ap])\.?\s*m\b", re.IGNORECASE)

_TOKEN_RE = re.compile(r"[A-Z0-9]{4,16}")
# a URL (scheme, www, or bare host) — its path/query slugs must never be read as IDs
_URL_RE = re.compile(
    r"(?:https?://|www\.)[^\s\"'<>]+", re.IGNORECASE
)
RESULT_KEYWORDS = ["shortlist", "selection list", "selected list",
                   "selected students", "final list"]

# --- Final-outcome detection -------------------------------------------------
# Distinguishes a FINAL selection/offer (student got in) from a bare shortlist
# (still in the running). Drives the celebratory notification vs the plain one.
# Conservative on purpose: a mail that merely opens with "Congratulations" but
# only says "shortlisted" must NOT be celebrated as a win.
_SELECTION_PHRASES = (
    "selection list", "selected list", "selected students", "selected candidates",
    "list of selected", "final list", "final selection",
    "you have been selected", "you've been selected", "you are selected",
    "have been selected", "has been selected", "been selected",
    "offer letter", "you have been placed", "has been placed", "been placed",
)


def detect_outcome(subject: str, body: str, extracted: set[str] | None = None,
                   has_spreadsheet: bool = False) -> str:
    """'selection' when the mail announces a FINAL result (selected/offered),
    else 'shortlist'. Only meaningful for mails already classified as a result."""
    text = f"{subject} {body}".lower()
    if any(p in text for p in _SELECTION_PHRASES):
        return "selection"
    return "shortlist"


SPREADSHEET_EXTS = (".xlsx", ".xls", ".csv")


def extract_ids(text: str) -> set[str]:
    if not text:
        return set()
    # drop URLs first so path/query slugs (e.g. /authenticateKey/a3gsbg4oao)
    # can't be mis-read as register IDs or shortlist codes
    text = _URL_RE.sub(" ", text)
    found: set[str] = set()
    for tok in _TOKEN_RE.findall(text.upper()):
        n = normalize_id(tok)
        if looks_like_id(n):
            found.add(n)
    return found


# Capture the real scheme URLs; use a broader matcher than _URL_RE so bare
# top-level URLs survive when preceded by punctuation/parens.
_LINK_RE = re.compile(r"https?://[^\s\"'<>\)]+", re.IGNORECASE)


def extract_urls(text: str) -> list[str]:
    """Return the unique http(s) URLs present in the mail body (test/apply/register links)."""
    if not text:
        return []
    seen: list[str] = []
    for m in _LINK_RE.findall(text):
        url = m.rstrip(".,;:!\u2026")
        if url and url not in seen:
            seen.append(url)
    return seen


def _cell_text(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _iter_spreadsheet_rows(path) -> list[list[str]]:
    """Every row of a spreadsheet/csv as a list of stripped cell strings."""
    lower = str(path).lower()
    rows: list[list[str]] = []
    if lower.endswith(".xlsx"):
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    rows.append([_cell_text(c) for c in row])
        finally:
            wb.close()
        return rows
    if lower.endswith(".xls"):
        import xlrd
        wb = xlrd.open_workbook(str(path))
        for sh in wb.sheets():
            for r in range(sh.nrows):
                rows.append([_cell_text(c) for c in sh.row_values(r)])
        return rows
    if lower.endswith(".csv"):
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.reader(f):
                rows.append([_cell_text(c) for c in row])
        return rows
    return rows


# A header row names columns ("Neo ID", "Reporting venue", "Date & Time").
# A data row is the thing we must never mistake for one: it carries a code.
_HEADER_TOKENS = ("id", "no", "name", "date", "time", "venue", "stack", "skill",
                  "branch", "course", "roll", "application", "report", "company")
_SERIAL_LABELS = ("s no", "s.no", "sno", "sl no", "sl.no", "serial")


def _looks_like_header(row: list[str]) -> bool:
    cells = [c for c in row if c]
    if len(cells) < 2:
        return False
    if any(extract_ids(c) for c in cells):  # a header never carries a code
        return False
    hits = sum(1 for c in cells if any(t in c.lower() for t in _HEADER_TOKENS))
    return hits >= 2


def _find_header_row(rows: list[list[str]]) -> tuple[int, list[str]]:
    for i, row in enumerate(rows[:5]):
        if _looks_like_header(row):
            return i, row
    return -1, []


def _is_serial(label: str) -> bool:
    low = label.strip().lower()
    return bool(low) and (low.startswith("#") or any(s in low for s in _SERIAL_LABELS))


def _row_context(row: list[str], id_cols: list[int], headers: list[str]) -> str:
    """The slot printed on the same row as a code, label-qualified and capped:
    'ApplicationNo.: HCLTFP2461546 · Skill Stack: Java (CSE/IT/EEE/ECE) ·
     Reporting venue: PRP 713 · Date & Time: 23-11-2026 (2.30 pm)'."""
    parts: list[str] = []
    for i, cell in enumerate(row):
        if i in id_cols or not cell:
            continue
        label = headers[i] if i < len(headers) else ""
        if label and _is_serial(label) and cell.isdigit():
            continue  # row number, not information
        if not label and cell.isdigit() and len(cell) <= 3:
            continue  # bare serial with no header to explain it
        parts.append(f"{label}: {cell}" if label else cell)
    return " · ".join(parts)[:200]


def extract_from_spreadsheet(path) -> tuple[set[str], dict[str, str]]:
    """(every id in the file, {id: row context}) from ONE read of the attachment.

    The row context is the whole point: extract_ids() alone throws the row away,
    so a shortlist code arrived with no idea of when/where that student reports."""
    ids: set[str] = set()
    slots: dict[str, str] = {}
    rows = _iter_spreadsheet_rows(path)
    for row in rows:
        for cell in row:
            ids |= extract_ids(cell)
    hdr_idx, headers = _find_header_row(rows)
    for ri, row in enumerate(rows):
        if ri == hdr_idx:
            continue
        id_cols: list[int] = []
        row_ids: list[str] = []
        for ci, cell in enumerate(row):
            found = extract_ids(cell)
            if found:
                id_cols.append(ci)
                row_ids.extend(sorted(found))
        if not row_ids:
            continue
        ctx = _row_context(row, id_cols, headers)
        if not ctx:
            continue
        for code in row_ids:
            slots.setdefault(code, ctx)  # first row wins on a duplicate code
    return ids, slots


def extract_slots_from_spreadsheet(path) -> dict[str, str]:
    """{id: 'Reporting venue: PRP 713 · Date & Time: 23-11-2026 (2.30 pm)'}."""
    return extract_from_spreadsheet(path)[1]


def extract_ids_from_spreadsheet(path) -> set[str]:
    return extract_from_spreadsheet(path)[0]


# Push-length view of a stored row context: values of the columns that say WHEN
# and WHERE, without the labels. '23-11-2026 (2.30 pm) · PRP 713'
_SLOT_PRIORITY = ("date", "time", "venue", "report", "slot", "session", "hall")


def compact_slot(slot: str, limit: int = 70) -> str:
    """Values of the WHEN/WHERE columns, date before venue, labels dropped."""
    if not slot:
        return ""
    segs = [s.strip() for s in slot.split("·") if s.strip()]
    cands: list[tuple[int, str]] = []
    for seg in segs:
        label, sep, value = seg.partition(": ")
        if sep:
            low = label.lower()
            rank = next((i for i, k in enumerate(_SLOT_PRIORITY) if k in low), None)
            if rank is not None:
                cands.append((rank, value.strip()))
        elif len(seg) <= 24:
            cands.append((len(_SLOT_PRIORITY), seg))
    cands.sort(key=lambda t: t[0])
    picked = [v for _, v in cands[:2] if v] or [segs[0]]
    return " · ".join(picked)[:limit].rstrip()


_WHEN_LABELS = ("date", "time", "session", "day", "timing")
_VENUE_LABELS = ("venue", "report", "hall", "location", "place", "centre", "center")
_SKIP_LABELS = ("birth", "dob", "mobile", "phone", "email", "gender", "degree",
                "candidate", "id", "name", "campus", "specialization")


def _label_has(label: str, keys: tuple[str, ...]) -> bool:
    """Word-boundary match — 'Candidate Id' must not count as a DATE column,
    and 'Date of Birth' is not an exam date."""
    low = label.lower()
    return any(re.search(rf"\b{k}\b", low) for k in keys)


def split_slot(slot: str) -> tuple[str, str]:
    """('23-11-2026 (2.30 pm)', 'PRP 713') from a stored row context.

    ONLY labelled date/time and venue columns count. An unlabelled cell is as
    likely to be a role ("QA"), a candidate number ("20949781") or a stack
    ("CIS") as a date — inventing a slot from those produced nonsense such as
    "Accenture Result on 20949781"."""
    when: list[str] = []
    venue = ""
    for seg in (slot or "").split("·"):
        label, sep, value = seg.partition(": ")
        value = value.strip()
        if not sep or not value:
            continue
        if _label_has(label, _SKIP_LABELS) and not _label_has(label, _VENUE_LABELS):
            continue
        if _label_has(label, _VENUE_LABELS):
            venue = venue or value
        elif _label_has(label, _WHEN_LABELS):
            when.append(value)
    return ", ".join(w for w in when if w and any(c.isdigit() for c in w)), venue


_ISO_DT_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{1,2}):(\d{2})(?::\d{2})?)?")


def _iso_to_slot(m: re.Match) -> str:
    yyyy, mm, dd, hh, mi = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
    if int(yyyy) < 2020:
        return ""     # a date of birth, or an Excel serial misread as a date
    out = f"{dd}-{mm}-{yyyy}"
    if hh and mi and not (int(hh) == 0 and mi == "00"):
        h = int(hh)
        suffix = "am" if h < 12 else "pm"
        out += f" ({h % 12 or 12}:{mi} {suffix})"
    return out


def slot_deadline(slot: str) -> str:
    """ISO-8601 reporting time with the IST offset, from a stored row context.

    '23-11-2026 (2:30 pm) · PRP 713' -> '2026-11-23T14:30:00+05:30'

    Returns "" when the row has no readable date AND time. That is deliberate: a
    phone alarm scheduled from a guessed time is worse than no alarm, and the
    notification still goes out either way.
    """
    when, _venue = split_slot(slot)
    # Stored rows are label-qualified ("Date & Time: ... · Reporting venue: ...")
    # and already-compacted slots are bare ("23-11-2026 (2.30 pm) · PRP 713").
    # split_slot only understands the labelled form, so fall back to the raw text.
    hay = when or (slot or "")
    d = _SLOT_DATE_RE.search(hay)
    if not d:
        return ""
    t = _SLOT_TIME_RE.search(hay)
    if not t:
        return ""
    try:
        day, month, year = int(d.group(1)), int(d.group(2)), int(d.group(3))
        hour, minute = int(t.group(1)), int(t.group(2))
        ampm = t.group(3).lower()
        if ampm == "p" and hour != 12:
            hour += 12
        elif ampm == "a" and hour == 12:
            hour = 0
        return dt.datetime(year, month, day, hour, minute, tzinfo=_IST).isoformat()
    except ValueError:
        return ""


def pretty_time(text: str) -> str:
    """House date style: '2.30 pm' -> '2:30 pm', '2026-11-07 00:00:00' -> '07-11-2026'."""
    text = _ISO_DT_RE.sub(_iso_to_slot, text or "")
    text = re.sub(r"\b(\d{1,2})\.(\d{2})\s*(?=[aApP]\.?[mM])", r"\1:\2 ", text)
    return re.sub(r"\s{2,}", " ", text).strip(" ,")


# What the mail is ABOUT — one short label, never the full subject.
_EVENT_KINDS = (
    (("pre-placement", "pre placement", "ppt"), "Pre-Placement Talk"),
    (("online test", "online assessment"), "Online Test"),
    (("interview",), "Interview"),
    (("registration", "register"), "Registration"),
    (("selection list", "selected", "result"), "Result"),
)


def event_kind(subject: str) -> str:
    low = (subject or "").lower()
    for keys, label in _EVENT_KINDS:
        if any(k in low for k in keys):
            return label
    return ""


# Fallback only: when the LLM summary is missing/deferred there is no company
# field, so read it off the subject the way a human does — strip the CDC's
# noise prefixes, then cut at the first event/boilerplate word.
_SUBJ_NOISE = ("re:", "fwd:", "kind attention", "kind attn", "attention",
               "congratulations", "congrats", "updated", "urgent",
               "final reminder", "reminder", "important")
_SUBJ_CUTS = ("online test", "online assessment", "pre-placement", "pre placement",
              "ppt", "is scheduled", "scheduled", "interview", "registration",
              "selection list", "selected", "shortlist", "next round", "result",
              "process", "applied", "candidates", "students", " is ", " are ",
              "!!", "!", " - ", " – ", ":")


def company_from_subject(subject: str) -> str:
    s = re.sub(r"\s+", " ", subject or "").strip()
    for _ in range(4):  # peel stacked prefixes ("Re: Kind Attn: ...")
        low = s.lower()
        nxt = next((n for n in _SUBJ_NOISE if low.startswith(n)), None)
        if not nxt:
            break
        s = s[len(nxt):].lstrip(" :!-,.")
    low = s.lower()
    cuts = [i for i in (low.find(k) for k in _SUBJ_CUTS) if i > 0]
    name = s[:min(cuts)].strip(" :!-,.*") if cuts else s.strip(" :!-,.*")
    return name[:40]


def slot_headline(slot: str, company: str = "", subject: str = "") -> str:
    """The whole notification in one line, built from the student's OWN row:
    'HCL Tech Online Test on 23-11-2026 (2:30 pm) - PRP 713'.

    The mail subject is deliberately NOT used for its text (it advertises the
    day's earliest session and reads like a paragraph); only a short event label
    is borrowed from it. Falls back to the slot alone when the company is unknown.
    """
    if not slot:
        return ""
    when, venue = split_slot(slot)
    when = pretty_time(when)
    if not when and not venue:
        return ""          # not a scheduling row — let the caller use the subject
    if venue and venue.islower() and len(venue) <= 12:
        venue = venue.upper()          # "prp 717" -> "PRP 717"
    head = " ".join(x for x in ((company or company_from_subject(subject)).strip(),
                                event_kind(subject)) if x).strip()
    if when:
        head = f"{head} on {when}".strip() if head else when
    if venue:
        head = f"{head} - {venue}" if head else venue
    return head[:120]


def classify(subject: str, body: str, extracted: set[str], has_spreadsheet: bool) -> str:
    """'shortlist' if the mail carries/embeds a results list; else 'announcement'."""
    if has_spreadsheet:
        return "shortlist"
    text = f"{subject} {body}".lower()
    if any(k in text for k in RESULT_KEYWORDS):
        return "shortlist"
    if extracted:
        return "shortlist"
    return "announcement"


def parse_eligible_branches(body: str) -> str:
    """Return the 'Eligible Branches' window text (fail-open, bounded by next header)."""
    if not body:
        return ""
    i = body.lower().find("eligible branch")
    if i == -1:
        return ""
    win = body[i:i + 400]
    for hdr in ("eligibility criteria", "date of visit", "name of the company",
                "category", "ctc", "stipend", "last date", "website", "location"):
        j = win.lower().find(hdr, 20)
        if j != -1:
            win = win[:j]
            break
    return re.sub(r"\s+", " ", win).strip()


_DIVISION_MBA = ("mba", "school of management", "management studies", "pgdm")
_DIVISION_BT = ("b.tech", "btech", "b tech", "bachelor", "ug ", "undergrad")
# branch/subgroup tokens (case-insensitive), used for finer branch filtering.
_BRANCH_TOKENS = (
    "aiml", "ai and ml", "artificial intelligence", "cse", "computer science",
    "core", "it", "information technology", "information security", "cys",
    "cyber", "eee", "ece", "mech", "mechanical", "civil", "eie", "aids",
)


def parse_audience(branch_text: str, subject: str = "") -> frozenset[str]:
    """Classify who an announcement/shortlist is aimed at, from the 'Eligible
    Branches' window + subject. Returns a set of audience tags:
      'mba'   -> MBA only
      'bt'    -> B.Tech only
      'bt:<branch>' -> B.Tech AND a specific branch/subgroup
      'any'   -> not restricted (empty text / generic "all students")
    Fail-open: an empty/garbled window returns {'any'} so a mail is never
    wrongly withheld from everyone. Callers re-check branch membership."""
    txt = f"{branch_text} {subject}".lower()
    has_mba = any(k in txt for k in _DIVISION_MBA)
    has_bt = any(k in txt for k in _DIVISION_BT)
    # A bare list of UG branch tokens (CSE, AIML, IT, ECE, Core...) with no MBA
    # mention is a B.Tech-targeted mail in VIT CDC context.
    mentions_ug_branch = any(k in txt for k in _BRANCH_TOKENS)
    audience: set[str] = set()
    if has_bt or (mentions_ug_branch and not has_mba):
        audience.add("bt")
    if has_mba:
        audience.add("mba")
    if not audience:
        audience.add("any")
    return frozenset(audience)


def audience_matches(audience: frozenset[str], division: str, branch: str = "") -> bool:
    """Does a user (division 'bt'/'mba', subgroup 'aiml'/'cse', ...) qualify for
    a mail whose parse_audience() = audience? Empty/generic audience = everyone."""
    if not audience or "any" in audience:
        return True
    if division == "mba":
        return "mba" in audience
    # B.Tech user: mail must include 'bt' generally...
    if "bt" not in audience and "mba" in audience:
        return False
    # ...and if it names specific branches without the user's branch, they're out
    return True