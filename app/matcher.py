"""Match extracted shortlist IDs against registered users and record hits.
Idempotent: re-running on the same (user, shortlist, id) never duplicates a hit.
This is the SOURCE OF TRUTH for "was this user selected?" — never overlapped by
the LLM summarizer."""
from __future__ import annotations

import logging
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .ids import hashing_enabled, hash_id
from .models import Hit, UserId

log = logging.getLogger("recruit.match")


def match_shortlist(db: Session, ingested_id: int, normalized_ids: Iterable[str]) -> list[Hit]:
    """Record a Hit for every registered user whose ID is on the shortlist.
    Idempotent. Returns newly created Hit objects (empty when nothing new)."""
    ids = list(dict.fromkeys(normalized_ids))
    if not ids:
        return []
    # Tracked IDs live as keyed hashes; the codes from the mail are hashed the same way,
    # so matching never needs the plaintext to be stored. On a deployment with no
    # ID_HASH_KEY configured, hash_id() is the identity and the legacy column is used.
    if hashing_enabled():
        user_ids = db.execute(
            select(UserId).where(UserId.code_hash.in_([hash_id(i) for i in ids]))
        ).scalars().all()
    else:
        user_ids = db.execute(
            select(UserId).where(UserId.normalized_id.in_(ids))
        ).scalars().all()

    created: list[Hit] = []
    for uid in user_ids:
        code = uid.code_hash if hashing_enabled() else uid.normalized_id
        dup = db.execute(select(Hit).where(
            Hit.user_id == uid.user_id,
            Hit.ingested_id == ingested_id,
            Hit.normalized_id == code,
        )).scalar_one_or_none()
        if dup:
            continue
        hit = Hit(user_id=uid.user_id, ingested_id=ingested_id, normalized_id=code)
        db.add(hit)
        created.append(hit)
    if created:
        from .metrics import HITS_CREATED
        HITS_CREATED.inc(len(created))
        log.info("match_shortlist hit created: %d | ids=%d", len(created), len(ids))
    db.commit()
    return created