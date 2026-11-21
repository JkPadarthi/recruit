"""Recruit — FastAPI app. Friends-only placement shortlist alerts."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import DB, Base
from .extract import classify, extract_ids
from .ingest import process_message, poll_once
from .models import AppState, Entry, Hit, Ingested, PushSubscription, User, UserId
from .security import hash_password, make_session_token, verify_password, verify_session_token
from .util import normalize_id

log = logging.getLogger("recruit")

db = DB()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    db.create_all()
    yield


app = FastAPI(title="Recruit", version="0.1.0", lifespan=_lifespan)

# Static + web pages
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
_STATIC_DIR = _Path(__file__).resolve().parent.parent / "static"
_STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

from .web import router as web_router  # noqa: E402
app.include_router(web_router)


def _current_user(request: Request, s: Session) -> User:
    uid = verify_session_token(request.cookies.get(settings.session_cookie_name, ""))
    if uid is None:
        raise HTTPException(401, "not authenticated")
    u = s.get(User, uid)
    if u is None:
        raise HTTPException(401, "user not found")
    return u


def _current_admin(request: Request, s: Session) -> User:
    u = _current_user(request, s)
    if not u.is_admin:
        raise HTTPException(403, "admin only")
    return u


def _client_ip(address: str) -> str:
    return (address or "").split(":")[0]


# ---- schemas ---------------------------------------------------------------
class RegisterIn(BaseModel):
    email: str
    password: str
    name: str = ""
    branch: str = ""
    division: str = ""
class ProfileIn(BaseModel):
    # None = "not sent, keep the current value" (partial update).
    name: str | None = None
    branch: str | None = None
    division: str | None = None
class LoginIn(BaseModel):
    email: str
    password: str
class IdIn(BaseModel):
    register_id: str
class PushIn(BaseModel):
    endpoint: str
    keys: dict = {}
    platform: str = "web"
class FcmIn(BaseModel):
    token: str
    platform: str = "android"


class TestPushIn(BaseModel):
    user_id: int
    title: str = "Recruit"
    body: str = "Test notification"


# ---- lifespan / startup ----------------------------------------------------
@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.create_all()
    yield


app.router.lifespan_context = lifespan  # noqa


# ---- auth ------------------------------------------------------------------
@app.post("/api/register")
def register(body: RegisterIn, request: Request):
    email = body.email.strip().lower()
    # domain gate if configured
    if settings.allowed_email_domains:
        dom = email.split("@")[-1]
        if dom not in settings.allowed_email_domains:
            raise HTTPException(403, "email domain not allowed")
    with db.session() as s:
        if s.execute(select(User).where(User.email == email)).scalar_one_or_none():
            raise HTTPException(409, "email already registered")
        u = User(email=email, password_hash=hash_password(body.password),
                 name=body.name.strip(), branch=body.branch.strip(),
                 division=body.division.strip().lower(),
                 is_admin=(settings.admin_email == email))
        s.add(u)
        s.commit()
        s.refresh(u)
        return {"id": u.id, "email": u.email}


@app.post("/api/login")
def login(body: LoginIn, response: Response):
    with db.session() as s:
        u = s.execute(select(User).where(User.email == body.email.strip().lower())).scalar_one_or_none()
        if not u or not verify_password(body.password, u.password_hash):
            raise HTTPException(401, "invalid credentials")
        response.set_cookie(settings.session_cookie_name, make_session_token(u.id),
                            httponly=True, samesite="lax",
                            secure=settings.session_secure, max_age=settings.session_max_age_sec)
        return {"id": u.id, "email": u.email, "admin": u.is_admin}


@app.post("/api/logout")
def logout():
    resp = RedirectResponse(url="/", status_code=303)
    resp.delete_cookie(settings.session_cookie_name,
                       path="/", httponly=True, samesite="lax",
                       secure=settings.session_secure)
    return resp


@app.get("/api/me")
def me(request: Request):
    with db.session() as s:
        u = _current_user(request, s)
        ids = s.execute(select(UserId).where(UserId.user_id == u.id)).scalars().all()
        return {"id": u.id, "email": u.email, "name": u.name, "branch": u.branch,
                "division": u.division,
                "admin": u.is_admin,
                "ids": [{"register_id": i.register_id, "normalized_id": i.normalized_id} for i in ids]}


@app.put("/api/me/profile")
def update_profile(body: ProfileIn, request: Request):
    """Let a user set/change their name, branch subgroup & division (bt/mba).
    Only fields present in the body change — omitting `name` no longer blanks it."""
    with db.session() as s:
        u = _current_user(request, s)
        if body.name is not None:
            u.name = body.name.strip()
        if body.branch is not None:
            u.branch = body.branch.strip()
        if body.division is not None:
            u.division = body.division.strip().lower()
        s.commit()
        return {"id": u.id, "name": u.name, "branch": u.branch, "division": u.division}


# ---- register-ID onboarding -------------------------------------------------
@app.post("/api/me/ids")
def add_id(body: IdIn, request: Request):
    with db.session() as s:
        u = _current_user(request, s)
        norm = normalize_id(body.register_id)
        from .util import looks_like_id
        if not looks_like_id(norm):
            raise HTTPException(422, f"'{body.register_id}' does not look like a register ID")
        dup = s.execute(select(UserId).where(UserId.user_id == u.id,
                                             UserId.normalized_id == norm)).scalar_one_or_none()
        if dup:
            return {"added": False, "normalized_id": norm, "backfilled": 0}
        s.add(UserId(user_id=u.id, register_id=body.register_id.strip(), normalized_id=norm))
        s.commit()
        # BACKFILL: the matcher otherwise runs only at ingest time, so every mail
        # that arrived before this ID was added is permanently invisible to this
        # user (measured: 75 real shortlist mails silently missed across 5 users,
        # one user 37 of 37). Re-match the mails that actually contain this code.
        backfilled = _backfill_hits_for(s, u.id, norm)
        return {"added": True, "normalized_id": norm, "backfilled": backfilled}


def _backfill_hits_for(s: Session, user_id: int, norm: str) -> int:
    """Create the missing hits for one (user, code) pair. Idempotent.

    Only mails whose OWN entries contain this code are touched — the mail is the
    authority, never the user's ID list (passing user codes would fabricate hits).
    Older mail is created as already-read so the unread badge stays about what is
    still actionable; the history is still visible in the hits list.
    """
    from .matcher import match_shortlist
    from .models import Entry

    ing_ids = [r[0] for r in s.execute(
        select(Entry.ingested_id).where(Entry.normalized_id == norm).distinct())]
    if not ing_ids:
        return 0
    before = s.execute(select(func.count(Hit.id)).where(
        Hit.user_id == user_id, Hit.normalized_id == norm)).scalar_one()
    for iid in ing_ids:
        match_shortlist(s, iid, {norm})
    s.commit()
    after = s.execute(select(func.count(Hit.id)).where(
        Hit.user_id == user_id, Hit.normalized_id == norm)).scalar_one()
    created = after - before
    if created:
        # Age is judged by the MAIL's timestamp, not the hit's (a backfilled hit is
        # created now): old shortlists are history, not a fresh alarm.
        from datetime import datetime, timedelta, timezone
        cut = datetime.now(timezone.utc) - timedelta(days=14)
        fresh = s.execute(select(Hit).where(
            Hit.user_id == user_id, Hit.normalized_id == norm,
            Hit.read_at.is_(None))).scalars().all()
        for h in fresh:
            ing = s.get(Ingested, h.ingested_id)
            ts = ing.created_at if ing and ing.created_at else None
            if ts and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts and ts < cut:
                h.read_at = ts
        s.commit()
    return created


@app.delete("/api/me/ids/{normalized_id}")
def delete_id(normalized_id: str, request: Request):
    with db.session() as s:
        u = _current_user(request, s)
        row = s.execute(select(UserId).where(UserId.user_id == u.id,
                                             UserId.normalized_id == normalize_id(normalized_id))).scalar_one_or_none()
        if not row:
            raise HTTPException(404, "id not found")
        s.delete(row)
        s.commit()
        return {"deleted": True}


# ---- hits ------------------------------------------------------------------
@app.get("/api/hits")
def get_hits(request: Request, unread_only: bool = False):
    with db.session() as s:
        u = _current_user(request, s)
        q = select(Hit).where(Hit.user_id == u.id)
        if unread_only:
            q = q.where(Hit.read_at.is_(None))
        hits = s.execute(q.order_by(Hit.first_seen_at.desc()).limit(200)).scalars().all()
        # house date style on every surface: the sheet writes "(2.30 pm)", we show
        # "(2:30 pm)" so the card, the feed and the push read identically
        from .extract import company_from_subject, pretty_time
        # one query for every row context we might show (no N+1 per hit)
        slotmap: dict[tuple[int, str], str] = {}
        if hits:
            ents = s.execute(
                select(Entry).where(
                    Entry.ingested_id.in_([h.ingested_id for h in hits]),
                    Entry.normalized_id.in_([h.normalized_id for h in hits]),
                    Entry.slot != "",
                )
            ).scalars().all()
            slotmap = {(e.ingested_id, e.normalized_id): e.slot for e in ents}
        out = []
        for h in hits:
            ing = s.get(Ingested, h.ingested_id)
            summary = _load_summary(ing)
            # Company for the card header: the summary's field, else read off the
            # subject, so a deferred-summary row still shows who it is about.
            company = str((summary or {}).get("company") or "").strip()
            if not company and ing:
                company = company_from_subject(ing.subject)
            out.append({
                "id": h.id, "normalized_id": h.normalized_id, "read": h.read_at is not None,
                "first_seen_at": h.first_seen_at.isoformat() if h.first_seen_at else None,
                "subject": ing.subject if ing else "",
                "kind": ing.kind if ing else "",
                "company": company,
                "slot": pretty_time(slotmap.get((h.ingested_id, h.normalized_id), "")),
                "summary": summary,
            })
        unread = s.execute(
            select(func.count(Hit.id)).where(Hit.user_id == u.id, Hit.read_at.is_(None))
        ).scalar_one()
        return {"hits": out, "unread": unread}


@app.post("/api/hits/{hit_id}/read")
def mark_read(hit_id: int, request: Request):
    with db.session() as s:
        u = _current_user(request, s)
        h = s.execute(select(Hit).where(Hit.id == hit_id, Hit.user_id == u.id)).scalar_one_or_none()
        if not h:
            raise HTTPException(404, "hit not found")
        h.read_at = func.now()
        s.commit()
        return {"ok": True}


def _load_summary(ing: Ingested | None) -> dict | None:
    if ing and ing.summary:
        try:
            return json.loads(ing.summary)
        except Exception:
            return None
    return None


def _load_links(ing: Ingested | None) -> list[str]:
    if ing and ing.links:
        try:
            v = json.loads(ing.links)
            return v if isinstance(v, list) else []
        except Exception:
            return []
    return []


# ---- mails feed (dashboard source of truth) ---------------------------------
@app.get("/api/mails")
def get_mails(request: Request, limit: int = 50):
    with db.session() as s:
        u = _current_user(request, s)
        rows = s.execute(select(Ingested).order_by(Ingested.created_at.desc()).limit(limit)).scalars().all()
        # ELIGIBILITY: only surface mails aimed at this user's division/branch.
        from .extract import audience_matches, parse_audience
        visible = [i for i in rows
                   if audience_matches(parse_audience(i.eligible_branches or "", i.subject or ""),
                                       u.division, u.branch)]
        # Per-user slots: ONLY the rows carrying this user's own codes. Sending all
        # 831 rows of a shortlist sheet would triple the feed payload for nothing.
        from .extract import pretty_time
        my_ids = {row.normalized_id for row in u.ids}
        slots: dict[int, dict[str, str]] = {}
        if my_ids and visible:
            ents = s.execute(
                select(Entry).where(
                    Entry.ingested_id.in_([i.id for i in visible]),
                    Entry.normalized_id.in_(my_ids),
                    Entry.slot != "",
                )
            ).scalars().all()
            for e in ents:
                slots.setdefault(e.ingested_id, {})[e.normalized_id] = pretty_time(e.slot)
        return {"mails": [
            {"id": i.id, "subject": i.subject, "from": i.from_addr, "date": i.date,
             "kind": i.kind, "eligible_branches": i.eligible_branches,
             "links": _load_links(i), "summary": _load_summary(i), "summary_status": i.summary_status,
             "my_slots": slots.get(i.id, {})}
            for i in visible
        ]}


# ---- status + manual poll ---------------------------------------------------
def _summary_health() -> list[dict]:
    """LLM rung health, one indirection so tests can stub the probe."""
    from .summarize import chain_health
    return chain_health()


@app.get("/api/status")
def status():
    from . import fcm as fcm_mod
    with db.session() as s:
        st = s.get(AppState, 1)
        counts = {
            "users": s.execute(select(func.count(User.id))).scalar_one(),
            "ingested": s.execute(select(func.count(Ingested.id))).scalar_one(),
            "hits": s.execute(select(func.count(Hit.id))).scalar_one(),
        }
        return {"brand": settings.brand_name, "last_uid": st.last_uid if st else None,
                "last_poll_at": st.last_poll_at.isoformat() if st and st.last_poll_at else None,
                "summarize_enabled": settings.summarize_enabled,
                "fcm_enabled": fcm_mod.enabled(),
                "summary_chain": _summary_health(),
                "summary_providers_usable": sum(1 for r in _summary_health() if r["reachable"]),
                "counts": counts}


@app.get("/health")
def health():
    """Lightweight liveness probe for the compose healthcheck."""
    return {"ok": True}

# Prometheus /metrics — scraped by the homelab Prometheus (job "recruit").
@app.get("/metrics")
def metrics():
    from fastapi.responses import Response
    from .metrics import render
    from prometheus_client import CONTENT_TYPE_LATEST
    return Response(content=render(db), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/admin/poll")
def admin_poll(request: Request):
    with db.session() as s:
        _current_admin(request, s)
    try:
        return poll_once(db)
    except Exception as e:
        log.exception("manual poll failed")
        raise HTTPException(500, f"poll failed: {e}")


@app.get("/api/admin/stats")
def admin_stats(request: Request):
    with db.session() as s:
        _current_admin(request, s)
        users = s.execute(select(User)).scalars().all()
        subs = s.execute(select(PushSubscription)).scalars().all()
        from collections import Counter
        sub_count = Counter(sub.user_id for sub in subs)
        return JSONResponse({
            "users": [{"id": u.id, "email": u.email, "name": u.name, "branch": u.branch,
                       "admin": u.is_admin,
                       "ids": [i.normalized_id for i in u.ids],
                       "devices": sub_count.get(u.id, 0)} for u in users],
            "ingested": s.execute(select(func.count(Ingested.id))).scalar_one(),
            "hits": s.execute(select(func.count(Hit.id))).scalar_one(),
        })


@app.post("/api/admin/test-push")
def admin_test_push(body: TestPushIn, request: Request):
    """Send a test notification to every live device of ONE user (admin only).

    Both transports, deliberately: this used to report only the Web Push half,
    so on a phone with no browser subscription it answered "sent: 0, declined: 1"
    while the native app was perfectly reachable. An operator diagnostic that
    lies is worse than none.
    """
    with db.session() as s:
        _current_admin(request, s)
        subs = s.execute(select(PushSubscription).where(
            PushSubscription.user_id == body.user_id,
            PushSubscription.platform == "web")).scalars().all()
        from .push import send_to_subscription
        sent = dead = 0
        for sub in subs:
            if send_to_subscription(sub, {"title": body.title, "body": body.body}):
                sent += 1
            else:
                dead += 1

        from . import fcm
        native = {"sent": 0, "failed": 0, "pruned": 0}
        if fcm.enabled():
            native = fcm.send(s, {body.user_id: {
                "title": body.title,
                "body": body.body,
                "tag": f"recruit-admin-{body.user_id}",
                "url": "/dashboard#hits",
                "event": body.title,
                "when_iso": "",
            }})
        return {"user_id": body.user_id, "live_devices": len(subs),
                "sent": sent, "declined": dead, "native": native}


# ---- push subscription ------------------------------------------------------
@app.post("/api/push/subscribe")
def push_subscribe(body: PushIn, request: Request):
    with db.session() as s:
        u = _current_user(request, s)
        dup = s.execute(select(PushSubscription).where(
            PushSubscription.user_id == u.id, PushSubscription.endpoint == body.endpoint)).scalar_one_or_none()
        if dup:
            return {"subscribed": True, "existing": True}
        s.add(PushSubscription(user_id=u.id, platform=body.platform,
                               endpoint=body.endpoint, keys_json=json.dumps(body.keys)))
        s.commit()
        return {"subscribed": True}


@app.post("/api/push/fcm")
def push_fcm_register(body: FcmIn, request: Request):
    """The Android shell reports its FCM token here, authenticated by the same
    web session cookie the WebView already holds. No second login."""
    from . import fcm
    with db.session() as s:
        u = _current_user(request, s)
        if not body.token.strip():
            raise HTTPException(400, "empty token")
        moved = fcm.register(s, u.id, body.token, body.platform)
        return {"registered": True, "moved_from_other_account": moved}


@app.post("/api/push/fcm/unregister")
def push_fcm_unregister(body: FcmIn, request: Request):
    """Remove THIS device's token (uninstall/logout). Other devices untouched."""
    from .models import FcmToken
    with db.session() as s:
        u = _current_user(request, s)
        row = s.execute(select(FcmToken).where(
            FcmToken.user_id == u.id, FcmToken.token == body.token)).scalar_one_or_none()
        if row:
            s.delete(row)
            s.commit()
            return {"unregistered": True}
        return {"unregistered": False}


@app.post("/api/push/unsubscribe")
def push_unsubscribe(body: PushIn, request: Request):
    """Remove ONLY this device's subscription (matched by endpoint)."""
    with db.session() as s:
        u = _current_user(request, s)
        row = s.execute(select(PushSubscription).where(
            PushSubscription.user_id == u.id, PushSubscription.endpoint == body.endpoint)).scalar_one_or_none()
        if row:
            s.delete(row)
            s.commit()
            return {"unsubscribed": True}
        return {"unsubscribed": False}


@app.get("/api/push/vapid-key")
def vapid_key():
    return {"public_key": settings.vapid_public_key}