"""Register-ID normalization + validation. Shared by onboarding and the matcher."""
from __future__ import annotations

import re

_SEP_RE = re.compile(r"[\s\-_.]+")
_REGISTER_ID_RE = re.compile(r"^[0-9]{2}[A-Z]{2,5}[0-9]{4}$")


def normalize_id(raw: str) -> str:
    """Squash separators, uppercase. The ONE canonical ID form."""
    return _SEP_RE.sub("", str(raw or "")).upper()


def _is_code(n: str) -> bool:
    """Shortlist codes are short uppercase alnum with mixed letter<->digit runs
    (K3I6O4I8, V1C2P516). >=2 letters, >=2 digits, >=2 letter<->digit switches
    rejects all-letter noise and footer tokens (QS2026)."""
    if not (6 <= len(n) <= 10 and n.isascii() and n.isalnum()):
        return False
    letters = digits = alternations = 0
    prev = None
    for ch in n:
        if ch.isalpha():
            letters += 1
            cur = "L"
        elif ch.isdigit():
            digits += 1
            cur = "D"
        else:
            return False
        if prev and prev != cur:
            alternations += 1
        prev = cur
    return letters >= 2 and digits >= 2 and alternations >= 2


def looks_like_id(normalized: str) -> bool:
    """True if `normalized` looks like a VIT register ID or a shortlist code."""
    if not normalized:
        return False
    if _REGISTER_ID_RE.match(normalized):
        return True
    return _is_code(normalized)