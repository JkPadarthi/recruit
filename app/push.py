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
        from .metrics import PUSH_SENT
        PUSH_SENT.inc()
        return True
    except WebPushException as e:
        from .metrics import PUSH_FAILED, PUSH_DEAD
        if getattr(e, "response", None) and e.response.status_code in (404, 410):
            log.warning("push endpoint dead (%s) user %s", e.response.status_code, sub.user_id)
            PUSH_DEAD.inc()
        else:
            log.warning("push failed user %s: %s", sub.user_id, e)
            PUSH_FAILED.inc()
        return False
    except Exception as e:
        from .metrics import PUSH_FAILED
        log.warning("push error user %s: %s", sub.user_id, e)
        PUSH_FAILED.inc()
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


def _company_from_summary(ingest) -> str:
    """Best-effort company name from the stored LLM summary (for celebrating)."""
    try:
        s = json.loads(ingest.summary or "{}")
        c = (s.get("company") or "").strip()
        return c
    except Exception:
        return ""


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
    from .extract import audience_matches, parse_audience
    from .models import User
    links = []
    try:
        links = json.loads(ingest.links or "[]") or []
    except Exception:
        links = []
    kinds = {url_kind(u) for u in links}
    has_test = "test" in kinds
    has_reg = "register" in kinds

    # ELIGIBILITY GATE: who is this mail aimed at? Agilisium ("MBA All
    # specializations") must never ping a B.Tech student, etc. Audience
    # computed from the eligible-branches window + subject.
    aud = parse_audience(ingest.eligible_branches or "", ingest.subject or "")
    users = {u.id: u for u in db.execute(select(User)).scalars().all()}

    # decide recipient scope
    notify_all_users = has_reg or (has_test and not has_ids)
    subs = db.execute(
        select(PushSubscription).where(PushSubscription.platform == "web")
    ).scalars().all()
    # pre-filter every candidate by audience BEFORE deciding scope
    qualified = [s for s in subs
                 if audience_matches(aud,
                                     (users.get(s.user_id).division if users.get(s.user_id) else ""),
                                     (users.get(s.user_id).branch if users.get(s.user_id) else ""))]
    if notify_all_users:
        target = qualified
    else:
        target = [s for s in qualified if s.user_id in matched_user_ids]
    if not target:
        return

    subject = ingest.subject or "a placement update"
    has_link = bool(links)
    body = subject
    if has_link:
        body = f"{subject}\n🔗 has an attached link — open the feed"

    # FINAL selection (offer / selected) gets a celebration, not the flat
    # "on the list" line. Company pulled from the summary when available.
    is_selection = getattr(ingest, "outcome", "") == "selection"
    company = _company_from_summary(ingest) if is_selection else ""
    selection_title = (f"🎉🎊 CONGRATULATIONS — you got selected for {company}!"
                       if company else
                       "🎉🎊 CONGRATULATIONS — you got selected!")

    for sub in target:
        if sub.user_id in matched_user_ids:
            if is_selection:
                payload = {"title": selection_title, "body": body}
            else:
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