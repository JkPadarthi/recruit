"""Web Push (VAPID) emitter — notifies a student's devices when a Hit fires.

Decision 7 (revised): push carries the subject line plus ONE slot line — the
date/venue/time from the student's own shortlist row ('📍 23-11-2026 (2.30 pm) ·
PRP 713') — because the subject alone says "23rd & 24th, 2.15 PM" and a student
cannot act on that. The full LLM summary + links stay on the dashboard. Covers
iOS+Android via the installed PWA. No-op when VAPID keys aren't configured."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .extract import slot_headline
from .models import Entry, Hit, PushSubscription, UserId

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
            # RFC 8030 urgency. Without it the push is NORMAL priority and Android
            # Doze is entitled to hold it until the next maintenance window —
            # measured live: a shortlist push landed 3h34m late on a dozing phone.
            # "high" tells the push service to wake the device now.
            headers={"Urgency": "high"},
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
    (apply/join/signup) or 'other'. Keyword-based — conservative.

    NOTE: never treat a bare `forms.gle` short domain as a "register" link —
    a Google Form on a *targeted* shortlist mail is just the next round's form,
    not an open registration drive. Only keyword-bearing paths/long URLs count.
    """
    u = url.lower()
    # A bare `forms.gle` short link is the next round's form, not an open
    # application drive — never treat it as "register".
    if u.startswith("https://forms.gle/") or u.startswith("http://forms.gle/"):
        return "other"
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


def _slots_for_users(db: Session, ingested_id: int, user_ids: set[int]) -> dict[int, str]:
    """{user_id: raw spreadsheet row context} for each matched user's own code."""
    if not user_ids:
        return {}
    from .ids import hashing_enabled, hash_id
    rows = db.execute(select(Entry).where(
        Entry.ingested_id == ingested_id, Entry.slot != "")).scalars().all()
    if not rows:
        return {}
    # entries keep the raw sheet text (that is every student's data, not ours), so when
    # our own IDs are hashed the comparison has to happen here: hash each row of this
    # mail once (at most a few hundred) and look the user's hash up in that map.
    if hashing_enabled():
        # A row written before the migration has a hash-less plaintext code; hash it here
        # so a half-migrated database still resolves slots instead of silently dropping.
        slots = {(e.code_hash or hash_id(e.normalized_id)): e.slot
                 for e in rows if e.code_hash or e.normalized_id}
        key_col = UserId.code_hash
    else:
        slots = {e.normalized_id: e.slot for e in rows}
        key_col = UserId.normalized_id
    if not slots:
        return {}
    out: dict[int, str] = {}
    for uid, code in db.execute(
            select(UserId.user_id, key_col).where(UserId.user_id.in_(user_ids))):
        ctx = slots.get(code)
        if ctx:
            out.setdefault(uid, ctx)
    return out


def notify_targeted(db: Session, ingest, matched_user_ids: set[int], has_ids: bool) -> None:
    """Notify per the required policy. A user gets a push when ANY of:
      1. their ID is in the mail (matched shortlist)  -> just that user
      2. the mail has a REGISTRATION link             -> EVERYONE
      3. the mail has a TEST link:
           - IDs present  -> only the matched user(s)
           - no IDs       -> EVERYONE
    """
    if not ingest:
        return
    if not settings.push_enabled:
        # Global silence: no web push, no FCM, no locally-armed nudge. Hits still get
        # stored, so nothing is lost — the switch only stops the buzz.
        log.info("notifications disabled globally (PUSH_ENABLED=0); ingest id=%s not sent",
                 ingest.id)
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
    # POLICY: broadcast a link (register OR test) to ALL users ONLY when the
    # mail has no register IDs. When IDs ARE present, the mail is a *targeted*
    # shortlist (e.g. "Citi next round" with 73 IDs) — its links are for the
    # matched students, not everyone. Return matched users in that case.
    notify_all_users = (has_reg or has_test) and not has_ids
    all_subs = db.execute(
        select(PushSubscription).where(PushSubscription.platform == "web")
    ).scalars().all()

    # Who qualifies by audience (branch/division), computed from USERS so the
    # Android path works for people who never enabled browser push.
    qualified_ids = {
        uid for uid, u in users.items()
        if audience_matches(aud, u.division or "", u.branch or "")
    }
    recipient_ids = qualified_ids if notify_all_users else (qualified_ids & matched_user_ids)
    if not recipient_ids:
        return
    target = [s for s in all_subs if s.user_id in recipient_ids]

    # Defensive: rows ingested before the CRLF fix still carry folded subjects.
    subject = re.sub(r"\s+", " ", ingest.subject or "").strip() or "a placement update"
    has_link = bool(links)
    link_line = "\n🔗 has an attached link — open the feed" if has_link else ""
    body = f"{subject}{link_line}"
    # WHERE/WHEN for the students who are actually ON the list — their own row.
    slot_by_user = _slots_for_users(db, ingest.id, recipient_ids)

    # FINAL selection (offer / selected) gets a celebration, not the flat
    # "on the list" line. Company pulled from the summary when available.
    is_selection = getattr(ingest, "outcome", "") == "selection"
    # The summary is computed AFTER the push now, so it may be empty here — read
    # the company off the subject as a fallback so the celebration still names it.
    from .extract import company_from_subject, event_kind, slot_deadline
    company = _company_from_summary(ingest) or company_from_subject(subject)
    selection_title = (f"🎉🎊 CONGRATULATIONS — you got selected for {company}!"
                       if company else
                       "🎉🎊 CONGRATULATIONS — you got selected!")

    # ONE payload per user, then fan out to every transport that user has.
    per_user: dict[int, dict[str, str]] = {}
    tag = f"recruit-{ingest.id}"

    def _title_for(uid: int) -> str:
        if uid in matched_user_ids:
            return selection_title if is_selection else "✅ You're on the list"
        if has_test:
            return "🧪 Test link available"
        if has_reg:
            return "📝 Registration open"
        if ingest.kind == "shortlist":
            return "📋 New shortlist"
        return "📢 New announcement"

    for uid in recipient_ids:
        # A matched student gets ONE line built from their own row:
        # "HCL Tech Online Test on 23-11-2026 (2:30 pm) - PRP 713".
        # The subject is NOT repeated: it advertises the day's earliest session
        # and reads like a paragraph on a phone lock screen.
        slot = slot_by_user.get(uid, "")
        user_body = slot_headline(slot, company, subject) if slot else body
        when_iso = slot_deadline(slot) if slot else ""
        per_user[uid] = {
            "title": _title_for(uid),
            "body": user_body,
            "tag": tag,
            "url": "/dashboard#hits",
            "when_iso": when_iso,
            # Alarm label the app can show 90 min before: "HCL Tech Online Test".
            "event": " ".join(x for x in (company, event_kind(subject)) if x).strip() or subject[:60],
        }

    # Transport 1: Web Push (instant when the browser is alive).
    if vapid_enabled():
        for sub in target:
            data = per_user.get(sub.user_id)
            if not data:
                continue
            send_to_subscription(sub, {"title": data["title"], "body": data["body"],
                                       "tag": data["tag"], "url": data["url"]})

    # Transport 2: FCM to the native shell (system-delivered; survives Doze).
    # No-op when no service account is configured.
    from . import fcm
    if fcm.enabled():
        stats = fcm.send(db, per_user)
        if stats["sent"] or stats["failed"] or stats["pruned"]:
            log.info("fcm: %s", stats)
