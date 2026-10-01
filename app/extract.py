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