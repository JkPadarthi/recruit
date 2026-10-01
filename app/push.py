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


def url_kind(url: str) -> str:
    """Classify a mail URL as 'test' (assessment/exam link) or 'register'
    (apply/join/signup) or 'other'. Keyword-based — conservative."""
    u = url.lower()
    if any(k in u for k in (
        "mettl", "authenticatekey", "testlink", "/test", "exambrowser",
        "assessment", "proctor", "examray", "online-test", "skill-assessment",
        "test-panel", "testimport", "testinvite", "/exam", "amplifire")):
        return "test"
    if any(k in u for k in (
        "register", "signup", "/apply", "/join", "enroll", "application",
        "careers", "hiring", "applynow", "forms", "jobapply", "candidate")):
        return "register"
    return "other"


def notify_targeted(db: Session, ingest, matched_user_ids: set[int], has_ids: bool) -> None:
    """Notify per the required policy. A user gets a push when ANY of:
      1. their ID is in the mail (matched shortlist)  -> just that user
      2. the mail has a REGISTRATION link             -> EVERYONE
      3. the mail has a TEST link:
           - IDs present  -> only the matched user(s)
           - no IDs       -> EVERYONE
    """
    if not ingest or not vapid_enabled():
        return
    links = []
    try:
        links = json.loads(ingest.links or "[]") or []
    except Exception:
        links = []
    kinds = {url_kind(u) for u in links}
    has_test = "test" in kinds
    has_reg = "register" in kinds

    # decide recipient scope
    notify_all_users = has_reg or (has_test and not has_ids)
    subs = db.execute(
        select(PushSubscription).where(PushSubscription.platform == "web")
    ).scalars().all()
    if notify_all_users:
        target = subs
    else:
        target = [s for s in subs if s.user_id in matched_user_ids]
    if not target:
        return

    subject = ingest.subject or "a placement update"
    has_link = bool(links)
    body = subject
    if has_link:
        body = f"{subject}\n🔗 has an attached link — open the feed"

    for sub in target:
        if sub.user_id in matched_user_ids:
            payload = {"title": "✅ You're on the list", "body": body}
        elif has_test:
            payload = {"title": "🧪 Test link available", "body": body}
        elif has_reg:
            payload = {"title": "📝 Registration open", "body": body}
        elif ingest.kind == "shortlist":
            payload = {"title": "📋 New shortlist", "body": body}
        else:
            payload = {"title": "📢 New announcement", "body": body}
        send_to_subscription(sub, payload)