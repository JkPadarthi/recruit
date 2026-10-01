"""Web Push (VAPID) emitter — notifies a student's devices when a Hit fires.

Decision 7: push carries ONLY the subject line (length-safe); the full LLM
summary + details live on the dashboard. Covers iOS+Android via the installed
PWA. No-op when VAPID keys aren't configured (dev/fixtures safe)."""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Hit, PushSubscription

log = logging.getLogger("recruit.push")


def vapid_private_key_arg() -> str | None:
    k = settings.vapid_private_key
    if not k:
        return None
    if "BEGIN" in k:  # PEM contents, not a path -> materialise
        p = Path("secrets/vapid_private.pem")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(k)
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
        return str(p)
    return k


def vapid_enabled() -> bool:
    return bool(settings.vapid_public_key and settings.vapid_private_key)


def send_to_subscription(sub: PushSubscription, payload: dict) -> bool:
    """Best-effort deliver one Web Push. Never raises upward. Returns success."""
    if not vapid_enabled():
        return False
    from urllib.parse import urlparse

    from pywebpush import WebPushException, webpush
    try:
        aud = "https://" + (urlparse(sub.endpoint).netloc or "web.push.apple.com")
        webpush(
            subscription_info={"endpoint": sub.endpoint,
                               "keys": json.loads(sub.keys_json or "{}")},
            data=json.dumps(payload),
            vapid_private_key=vapid_private_key_arg(),
            vapid_claims={"sub": settings.vapid_subject, "aud": aud,
                          "iat": int(time.time())},
            ttl=86400, timeout=10,
        )
        log.info("push OK -> user %s endpoint %s", sub.user_id, sub.endpoint[:40])
        return True
    except WebPushException as e:
        if getattr(e, "response", None) and e.response.status_code in (404, 410):
            log.warning("push endpoint dead (%s) user %s", e.response.status_code, sub.user_id)
        else:
            log.warning("push failed user %s: %s", sub.user_id, e)
        return False
    except Exception as e:
        log.warning("push error user %s: %s", sub.user_id, e)
        return False


def notify_hits(db: Session, hits: list[Hit]) -> None:
    """Push one message per new hit — SUBJECT ONLY in the body."""
    if not hits or not vapid_enabled():
        return
    user_ids = sorted({h.user_id for h in hits})
    subs = db.execute(
        select(PushSubscription).where(
            PushSubscription.user_id.in_(user_ids),
            PushSubscription.platform == "web",
        )
    ).scalars().all()
    if not subs:
        return
    by_user: dict[int, list[PushSubscription]] = {}
    for sub in subs:
        by_user.setdefault(sub.user_id, []).append(sub)
    for hit in hits:
        ing = hit.ingested
        subject = ing.subject if ing else "a placement shortlist"
        payload = {"title": "✅ You're on the list", "body": subject}
        for sub in by_user.get(hit.user_id, []):
            send_to_subscription(sub, payload)