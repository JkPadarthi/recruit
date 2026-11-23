"""Tracked IDs are stored as a keyed hash, never as text.

A NEO ID is short — 8 characters from a small alphabet — so a plain SHA-256 would be
brute-forced back to the original on a laptop in minutes. The key is what makes the hash
useless to anyone who walks off with the database.

Consequences, stated plainly because they are permanent:

* **Losing `ID_HASH_KEY` loses the ability to match anything.** The 34 tracked IDs become
  un-matchable noise and every user has to re-add theirs. Back the key up with the DB.
* Nothing can display a tracked ID again — not the profile, not the admin page, not us.
  The UI shows a position ("ID 1") and a count instead.
* `entries` (the raw CDC spreadsheets) is deliberately NOT hashed: those rows belong to
  every student in the college, not to our users. So a code can still be found there by
  anyone holding the file. Hashing `user_ids` protects the table that says *who is
  watching what*, not the mail archive itself.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging

from .config import settings

log = logging.getLogger("recruit.ids")

_warned = False


def _key() -> bytes | None:
    raw = (getattr(settings, "id_hash_key", "") or "").strip()
    if not raw:
        return None
    try:
        return base64.b64decode(raw)
    except Exception:
        # Accept a bare string too: a wrong key is worse than a clear one, but a
        # configured key must never silently fall back to plaintext.
        return raw.encode()


def hashing_enabled() -> bool:
    global _warned
    ok = _key() is not None
    if not ok and not _warned:
        _warned = True
        log.warning("ID_HASH_KEY is not set — tracked IDs are stored in PLAINTEXT. "
                    "Set it before the next deploy; the migration requires it.")
    return ok


def hash_id(normalized: str) -> str:
    """HMAC-SHA256 of an already-normalized ID, hex. Falls back to the input unchanged
    only when no key is configured, so a half-migrated deployment still matches."""
    key = _key()
    if key is None:
        return normalized
    return hmac.new(key, normalized.encode(), hashlib.sha256).hexdigest()


def stored(normalized: str) -> str:
    """What goes into `user_ids.code_hash` / `hits.normalized_id` for this code."""
    return hash_id(normalized)


def label(index: int) -> str:
    """The only thing the UI may say about a hash: which slot it is."""
    return f"ID {index}"
