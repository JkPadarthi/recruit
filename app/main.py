"""Recruit — FastAPI app. Friends-only placement shortlist alerts."""
from __future__ import annotations

import json
import os
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
from .security import (decode_session, hash_password, make_session_token,
                       verify_password, verify_session_token)
from .util import normalize_id

log = logging.getLogger(__name__)

# Uvicorn configures its own loggers; ours inherit the root default of WARNING, which
# swallowed every "reset mail accepted/failed" line. Reset events must leave a trace.
logging.getLogger("app").setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())

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
from .apk import router as apk_router  # noqa: E402
app.include_router(apk_router)
from .reset import router as reset_router  # noqa: E402
app.include_router(reset_router)
from .verify import router as verify_router  # noqa: E402
app.include_router(verify_router)
from .bounces import router as bounces_router  # noqa: E402
app.include_router(bounces_router)


def _current_user(request: Request, s: Session) -> User:
    data = decode_session(request.cookies.get(settings.session_cookie_name, ""))
    if not data:
        raise HTTPException(401, "not authenticated")
    u = s.get(User, int(data.get("uid", -1)))
    if u is None:
        raise HTTPException(401, "user not found")
    # A password reset bumps the epoch, which invalidates every older cookie.
    if int(data.get("ep", 0)) != int(u.session_epoch or 0):
        raise HTTPException(401, "session expired — sign in again")
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
class EmailIn(BaseModel):
    email: str
    password: str          # current password: the email IS the login identifier


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


# ---- retired hostnames ------------------------------------------------------
# Anyone with the old address bookmarked, or an app installed before the move, lands
# here. Browsers get a page that explains it; API calls get a 308 to the new host so an
# old client's requests still reach a real server (its cookie will not travel, which is
# correct — the user signs in again on the new address).
RETIRED_HOSTS = ("98487840.xyz",)
CANONICAL_URL = "https://recruit.jaswanth.me"


def _is_retired(host_header: str) -> bool:
    host = (host_header or "").split(":")[0].strip().lower()
    return any(host == h or host.endswith("." + h) for h in RETIRED_HOSTS)


@app.middleware("http")
async def retired_host_moved(request: Request, call_next):
    if not _is_retired(request.headers.get("host", "")):
        return await call_next(request)

    path = request.url.path
    target = CANONICAL_URL + path + (f"?{request.url.query}" if request.url.query else "")
    wants_html = "text/html" in request.headers.get("accept", "")

    if request.method in ("GET", "HEAD") and wants_html and not path.startswith("/api/"):
        from .web import templates
        return templates.TemplateResponse(
            request, "moved.html",
            {"brand": settings.brand_name, "new_url": CANONICAL_URL,
             "new_domain": CANONICAL_URL.split("//", 1)[1]},
        )
    # 308 keeps the method and body, so an old client's POST is not silently turned
    # into a GET (which is what a 301 would do).
    return RedirectResponse(target, status_code=308)


# ---- the verification gate --------------------------------------------------
# An unverified account may sign in and read /api/me (it needs to know its own state),
# but nothing else. The list is a prefix allowlist on purpose: a new data endpoint is
# protected by default, which is the failure mode you want.
# NOTE: /api/me is an EXACT match, not a prefix. "/api/me" as a prefix also exempts
# /api/me/ids and /api/me/profile — i.e. it hands an unverified account the very thing
# verification exists to protect. A test pins this.
_VERIFY_EXEMPT_EXACT = {
    "/api/login", "/api/register", "/api/logout", "/api/me",
    "/api/status", "/api/app", "/api/health",
}
_VERIFY_EXEMPT_PREFIX = ("/api/verify/", "/api/password/", "/api/push/fcm/unregister",
                         "/api/webhooks/")


@app.middleware("http")
async def require_verified_email(request: Request, call_next):
    path = request.url.path
    exempt = path in _VERIFY_EXEMPT_EXACT or path.startswith(_VERIFY_EXEMPT_PREFIX)
    if path.startswith("/api/") and not exempt:
        if request.cookies.get(settings.session_cookie_name):
            try:
                with db.session() as s:
                    u = _current_user(request, s)
                    if not u.email_verified:
                        return JSONResponse(
                            {"detail": "Verify your email address first.",
                             "code": "email_unverified",
                             "email": u.email},
                            status_code=403,
                        )
            except HTTPException:
                pass  # bad/expired cookie: let the route answer 401 as before
    return await call_next(request)


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
        # Prove the address before it can receive anyone's shortlists. A mail failure
        # must not lose the signup: the verify screen can resend.
        sent = False
        try:
            from .verify import issue
            sent = issue(s, u, force=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("verification mail on signup failed: %s", exc)
        return {"id": u.id, "email": u.email, "verified": False, "code_sent": sent}


@app.post("/api/login")
def login(body: LoginIn, response: Response):
    with db.session() as s:
        u = s.execute(select(User).where(User.email == body.email.strip().lower())).scalar_one_or_none()
        if not u or not verify_password(body.password, u.password_hash):
            raise HTTPException(401, "invalid credentials")
        response.set_cookie(settings.session_cookie_name,
                            make_session_token(u.id, u.session_epoch or 0),
                            httponly=True, samesite="lax",
                            secure=settings.session_secure, max_age=settings.session_max_age_sec)
        return {"id": u.id, "email": u.email, "admin": u.is_admin,
                "verified": bool(u.email_verified)}


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
        # Tracked IDs are stored as keyed hashes, so they cannot be shown back. The UI
        # gets a position and a stable row id (for deleting), nothing else.
        return {"id": u.id, "email": u.email, "name": u.name, "branch": u.branch,
                "division": u.division, "email_verified": bool(u.email_verified),
                "admin": u.is_admin,
                "ids": [{"id": i.id, "label": f"ID {n}"} for n, i in enumerate(ids, 1)]}


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


@app.put("/api/me/email")
def update_email(body: EmailIn, request: Request):
    """Change the login address.

    Requires the current password: without it, anyone holding a live session (a shared
    laptop, an old cookie) could quietly move the account to their own address and then
    use "forgot password" to take it over. The email is the reset channel, so this is
    exactly the field an attacker would want.

    Domains are re-checked against ALLOWED_EMAIL_DOMAINS — a typo'd address is the
    reason this endpoint exists, and "gmaill.com" must be rejected here too, not only at
    signup.
    """
    new = (body.email or "").strip().lower()
    if "@" not in new or new.startswith("@") or new.endswith("@"):
        raise HTTPException(400, "That does not look like an email address.")

    with db.session() as s:
        u = _current_user(request, s)
        if not verify_password(body.password or "", u.password_hash):
            raise HTTPException(401, "Wrong password.")
        if new == u.email:
            return {"email": u.email, "changed": False}

        if settings.allowed_email_domains:
            dom = new.split("@")[-1]
            if dom not in settings.allowed_email_domains:
                raise HTTPException(
                    403, "Use a college or Gmail address ("
                         + ", ".join(settings.allowed_email_domains) + ").")

        taken = s.execute(select(User).where(User.email == new)).scalar_one_or_none()
        if taken is not None:
            raise HTTPException(409, "Another account already uses that address.")

        old = u.email
        u.email = new
        s.commit()
        log.info("email changed for user %s", u.id)
        return {"email": u.email, "changed": True, "previous": old}


# ---- register-ID onboarding -------------------------------------------------
@app.post("/api/me/ids")
def add_id(body: IdIn, request: Request):
    with db.session() as s:
        u = _current_user(request, s)
        norm = normalize_id(body.register_id)
        from .util import looks_like_id
        if not looks_like_id(norm):
            raise HTTPException(422, f"'{body.register_id}' does not look like a register ID")
        from .ids import hashing_enabled, hash_id
        hashed = hash_id(norm) if hashing_enabled() else ""
        dup_q = (select(UserId).where(UserId.user_id == u.id, UserId.code_hash == hashed)
                 if hashing_enabled() else
                 select(UserId).where(UserId.user_id == u.id, UserId.normalized_id == norm))
        if s.execute(dup_q).scalar_one_or_none():
            return {"added": False, "backfilled": 0}
        # The plaintext columns stay empty: the hash is the only record of the code.
        s.add(UserId(user_id=u.id, register_id="", normalized_id="", code_hash=hashed))
        s.commit()
        # BACKFILL: the matcher otherwise runs only at ingest time, so every mail
        # that arrived before this ID was added is permanently invisible to this
        # user (measured: 75 real shortlist mails silently missed across 5 users,
        # one user 37 of 37). Re-match the mails that actually contain this code.
        backfilled = _backfill_hits_for(s, u.id, norm)
        # No echo of the code: the response is the last place it could leak.
        return {"added": True, "backfilled": backfilled}


def _backfill_hits_for(s: Session, user_id: int, norm: str) -> int:
    """Create the missing hits for one (user, code) pair. Idempotent.

    Only mails whose OWN entries contain this code are touched — the mail is the
    authority, never the user's ID list (passing user codes would fabricate hits).
    Older mail is created as already-read so the unread badge stays about what is
    still actionable; the history is still visible in the hits list.
    """
    from .matcher import match_shortlist
    from .models import Entry

    from .ids import hashing_enabled, hash_id
    lookup = Entry.code_hash if hashing_enabled() else Entry.normalized_id
    value = hash_id(norm) if hashing_enabled() else norm
    ing_ids = [r[0] for r in s.execute(
        select(Entry.ingested_id).where(lookup == value).distinct())]
    if not ing_ids:
        return 0
    from .ids import stored
    key = stored(norm)
    before = s.execute(select(func.count(Hit.id)).where(
        Hit.user_id == user_id, Hit.normalized_id == key)).scalar_one()
    for iid in ing_ids:
        match_shortlist(s, iid, {norm})
    s.commit()
    after = s.execute(select(func.count(Hit.id)).where(
        Hit.user_id == user_id, Hit.normalized_id == key)).scalar_one()
    created = after - before
    if created:
        # Age is judged by the MAIL's timestamp, not the hit's (a backfilled hit is
        # created now): old shortlists are history, not a fresh alarm.
        from datetime import datetime, timedelta, timezone
        cut = datetime.now(timezone.utc) - timedelta(days=14)
        fresh = s.execute(select(Hit).where(
            Hit.user_id == user_id, Hit.normalized_id == key,
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


@app.delete("/api/me/ids/{row_id}")
def delete_id(row_id: int, request: Request):
    """Remove one tracked ID. Keyed by row id: the code itself no longer exists in the
    database, so it cannot be used as the identifier."""
    with db.session() as s:
        u = _current_user(request, s)
        row = s.execute(select(UserId).where(UserId.user_id == u.id,
                                             UserId.id == row_id)).scalar_one_or_none()
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
        from .extract import company_from_subject, pretty_time, slot_deadline
        # one query for every row context we might show (no N+1 per hit)
        slotmap: dict[tuple[int, str], str] = {}
        if hits:
            # hits.normalized_id is the keyed hash of the code, and so is Entry.code_hash:
            # the sheet row is looked up by hash, never by the code itself.
            from .ids import hashing_enabled
            col = Entry.code_hash if hashing_enabled() else Entry.normalized_id
            keys = [h.normalized_id for h in hits]
            ents = s.execute(
                select(Entry).where(
                    Entry.ingested_id.in_([h.ingested_id for h in hits]),
                    col.in_(keys),
                    Entry.slot != "",
                )
            ).scalars().all()
            slotmap = {(e.ingested_id, e.code_hash if hashing_enabled() else e.normalized_id): e.slot
                       for e in ents}
        out = []
        for h in hits:
            ing = s.get(Ingested, h.ingested_id)
            raw_slot = slotmap.get((h.ingested_id, h.normalized_id), "")
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
                # The deadline as an ISO instant, so a client can arm its own alarm
                # instead of re-parsing the sheet's "(2.30 pm)" text. Empty when the
                # row has no readable time — the client must not guess.
                "when_iso": slot_deadline(raw_slot) if raw_slot else "",
                "summary": summary,
            })
        unread = s.execute(
            select(func.count(Hit.id)).where(Hit.user_id == u.id, Hit.read_at.is_(None))
        ).scalar_one()
        return {"hits": out, "unread": unread}


@app.get("/api/hits/{hit_id}/ics")
def hit_calendar(hit_id: int, request: Request):
    """A calendar reminder for ONE shortlist row.

    The free iOS path: an iPhone cannot install our app without a paid Apple account,
    and Safari has no local-alarm API, so an .ics with a VALARM is the only reminder
    it can keep. Owner-only — a 404 for anyone else, so this cannot enumerate hits.

    409 rather than a guessed time when the sheet row has no readable date: a wrong
    alarm is worse than none, and the hit itself is still visible.
    """
    from .extract import company_from_subject, event_kind, slot_deadline, split_slot
    from .ics import build_ics

    with db.session() as s:
        u = _current_user(request, s)
        hit = s.get(Hit, hit_id)
        if hit is None or hit.user_id != u.id:
            raise HTTPException(404, "no such hit")

        from .ids import hashing_enabled
        ent = s.execute(select(Entry).where(
            Entry.ingested_id == hit.ingested_id,
            (Entry.code_hash if hashing_enabled() else Entry.normalized_id) == hit.normalized_id,
            Entry.slot != "",
        )).scalars().first()
        if ent is None:
            raise HTTPException(409, "this shortlist has no sheet row to schedule")

        when = slot_deadline(ent.slot)
        if not when:
            raise HTTPException(409, "that sheet row has no readable date and time")

        ing = s.get(Ingested, hit.ingested_id)
        subject = (ing.subject if ing else "") or ""
        summary = _load_summary(ing) or {}
        company = str(summary.get("company") or "").strip() or company_from_subject(subject)
        kind = event_kind(subject)
        title = " ".join(part for part in (company, kind) if part).strip() or subject[:80] or "CDC shortlist"
        _when, venue = split_slot(ent.slot)
        slot_text = ent.slot

    body = build_ics(
        uid=f"recruit-{hit_id}",
        title=title,
        when_iso=when,
        location=venue or "",
        description=slot_text,
        url="https://recruit.jaswanth.me/dashboard#hits",
    )
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="recruit-{hit_id}.ics"'},
    )


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
        # The tracked codes are hashes, so the feed is keyed by the slot the user knows
        # ("ID 1") instead. Keys used to be the code itself, which leaked it to anyone
        # reading the JSON.
        from .ids import hashing_enabled
        labels = {row.code_hash: f"ID {n}" for n, row in enumerate(u.ids, 1)} \
            if hashing_enabled() else {row.normalized_id: f"ID {n}" for n, row in enumerate(u.ids, 1)}
        slots: dict[int, dict[str, str]] = {}
        if labels and visible:
            col = Entry.code_hash if hashing_enabled() else Entry.normalized_id
            ents = s.execute(
                select(Entry).where(
                    Entry.ingested_id.in_([i.id for i in visible]),
                    col.in_(list(labels)),
                    Entry.slot != "",
                )
            ).scalars().all()
            for e in ents:
                key = e.code_hash if hashing_enabled() else e.normalized_id
                slots.setdefault(e.ingested_id, {})[labels.get(key, "ID")] = pretty_time(e.slot)
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
        if not settings.push_enabled:
            # The admin tool must not be a back door around the master switch.
            raise HTTPException(409, "notifications are disabled globally (PUSH_ENABLED=0)")
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