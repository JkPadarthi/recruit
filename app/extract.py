"""ID discovery + mail classification (deterministic; proven from the watchman).
Extracts every register ID / shortlist code from text + spreadsheet cells, and
classifies a mail as shortlist vs announcement."""
from __future__ import annotations

import csv
import re

from .util import looks_like_id, normalize_id

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


def extract_ids_from_csv(path) -> set[str]:
    out: set[str] = set()
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.reader(f):
            for cell in row:
                out |= extract_ids(str(cell))
    return out


def extract_ids_from_xlsx(path) -> set[str]:
    from openpyxl import load_workbook
    out: set[str] = set()
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                for cell in row:
                    if cell is None:
                        continue
                    out |= extract_ids(str(cell))
    finally:
        wb.close()
    return out


def extract_ids_from_xls(path) -> set[str]:
    import xlrd
    out: set[str] = set()
    wb = xlrd.open_workbook(path)
    for sh in wb.sheets():
        for r in range(sh.nrows):
            for cell in sh.row_values(r):
                out |= extract_ids(str(cell))
    return out


def extract_ids_from_spreadsheet(path) -> set[str]:
    lower = path.lower()
    if lower.endswith(".xlsx"):
        return extract_ids_from_xlsx(path)
    if lower.endswith(".xls"):
        return extract_ids_from_xls(path)
    if lower.endswith(".csv"):
        return extract_ids_from_csv(path)
    return set()


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