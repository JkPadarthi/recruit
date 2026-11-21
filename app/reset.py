"""Forgotten passwords: request a link, spend it, and the admin fallback.

Design, and why it looks like this:

  * A link is 60 minutes and single use. It is stored only as a SHA-256 hash, so a
    leaked database is not a stack of working password links.
  * `/api/password/forgot` answers identically whether or not the address exists.
    Otherwise it is an oracle for "who is on Recruit", which for a 12-person app is
    literally a friends list.
  * One request per account per 10 minutes. Without it, the endpoint is a free way to
    make our SMTP sender spam someone.
  * Spending a link bumps `session_epoch`, which invalidates every cookie issued
    before the reset — a changed password must not leave old sessions alive.
  * When SMTP is not configured the request still records, and the admin panel can
    hand out the link instead. That keeps resets working on a box with no mailer.
"""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select

from . import mailer
from .config import settings
from .models import PasswordReset, User
from .security import hash_password, hash_reset_token, new_reset_token

log = logging.getLogger(__name__)


def _db():
    """The app's one DB holder, fetched lazily.

    It lives in main.py, and main imports this router at import time — importing it
    back at module level would be a cycle. Tests swap engine/session_factory on that
    same object, so there must be exactly one.
    """
    from .main import db
    return db
router = APIRouter(tags=["reset"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

TOKEN_TTL_MIN = 60
RATE_LIMIT_MIN = 10
MIN_PASSWORD = 8


class ForgotIn(BaseModel):
    email: str


class ResetIn(BaseModel):
    token: str
    password: str


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    """SQLite hands back naive datetimes; compare them as UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def _issue(s, user: User) -> str:
    """Create a fresh link for `user` and return the RAW token (never stored)."""
    raw = new_reset_token()

    # Retire older links BEFORE inserting the new one. Querying after s.add() lets
    # SQLAlchemy autoflush the new row into the result set and expire the link we are
    # about to hand out — which looks exactly like "this link is not valid".
    for old in s.execute(
        select(PasswordReset).where(
            PasswordReset.user_id == user.id,
            PasswordReset.used_at.is_(None),
            PasswordReset.token_hash != "",
        )
    ).scalars():
        old.used_at = _now()
    s.flush()

    s.add(PasswordReset(
        user_id=user.id,
        token_hash=hash_reset_token(raw),
        expires_at=_now() + dt.timedelta(minutes=TOKEN_TTL_MIN),
    ))
    s.commit()
    return raw


def _reset_url(raw: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}/reset?t={raw}"


def _mail_body(url: str) -> tuple[str, str]:
    text = f"""Someone asked to reset the password for your Recruit account.

{url}

The link works once and expires in {TOKEN_TTL_MIN} minutes.

If this wasn't you, ignore this mail — nothing has changed and your password
still works. Nobody can use this link without opening it.
"""
    html = f"""<div style="font-family:system-ui,-apple-system,'Segoe UI',sans-serif;
                       max-width:520px;margin:0 auto;padding:28px 24px;color:#0E1715">
  <p style="font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#8a7d63;margin:0 0 18px">
    {settings.brand_name}
  </p>
  <h1 style="font-size:21px;margin:0 0 12px">Reset your password</h1>
  <p style="line-height:1.6;margin:0 0 22px;color:#3b4744">
    Someone asked to reset the password for your Recruit account. Tap the button to
    choose a new one. It works once and expires in {TOKEN_TTL_MIN} minutes.
  </p>
  <p style="margin:0 0 26px">
    <a href="{url}" style="display:inline-block;background:#F4B33D;color:#1C1405;
       font-weight:600;text-decoration:none;padding:13px 22px;border-radius:10px">
      Choose a new password
    </a>
  </p>
  <p style="font-size:13px;line-height:1.6;color:#74847d;margin:0">
    If this wasn't you, ignore this mail — nothing has changed, and your password
    still works. Nobody can use this link without opening it.
  </p>
</div>"""
    return text, html


# ------------------------------------------------------------------- pages
@router.get("/forgot", response_class=HTMLResponse)
def forgot_page(request: Request):
    return templates.TemplateResponse(
        request, "forgot.html",
        {"brand": settings.brand_name, "email_ready": mailer.enabled()},
    )


@router.get("/reset", response_class=HTMLResponse)
def reset_page(request: Request, t: str = ""):
    """Render the form only for a token that already looks redeemable.

    Checking here as well as on submit is the difference between "pick a new
    password" and "you typed twice, then learned the link was dead".
    """
    ok, reason = _token_state(t)
    return templates.TemplateResponse(
        request, "reset.html",
        {"brand": settings.brand_name, "token": t, "ok": ok, "reason": reason},
    )


def _token_state(raw: str) -> tuple[bool, str]:
    if not raw:
        return False, "This link is missing its code."
    with _db().session() as s:
        row = s.execute(
            select(PasswordReset).where(PasswordReset.token_hash == hash_reset_token(raw))
        ).scalar_one_or_none()
        if row is None:
            return False, "This link is not valid. Ask for a new one."
        if row.used_at is not None:
            return False, "This link has already been used. Ask for a new one."
        exp = _aware(row.expires_at)
        if exp is None or exp < _now():
            return False, "This link has expired. Ask for a new one."
    return True, ""


# --------------------------------------------------------------------- api
@router.post("/api/password/forgot")
def forgot(body: ForgotIn):
    """Always the same answer. Never reveals whether the address is registered."""
    answer = {"ok": True,
              "message": "If that address has an account, a reset link is on its way.",
              "email_configured": mailer.enabled()}
    email = (body.email or "").strip().lower()
    if not email or "@" not in email:
        return answer

    with _db().session() as s:
        u = s.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if u is None:
            log.info("reset requested for unknown address %s", email)
            return answer

        recent = s.execute(
            select(PasswordReset)
            .where(PasswordReset.user_id == u.id)
            .order_by(PasswordReset.created_at.desc())
        ).scalars().first()
        created = _aware(recent.created_at) if recent else None
        if created and (_now() - created) < dt.timedelta(minutes=RATE_LIMIT_MIN):
            log.info("reset request for %s ignored (rate limit)", email)
            return answer

        # Record the request even without SMTP: the admin panel lists these and can
        # issue the link by hand.
        raw = _issue(s, u) if mailer.enabled() else ""
        if not raw:
            s.add(PasswordReset(user_id=u.id, token_hash=""))
            s.commit()

    if raw:
        text, html = _mail_body(_reset_url(raw))
        sent = mailer.send(u.email, f"Reset your {settings.brand_name} password", text, html)
        if not sent:
            # Mail failed: leave the request visible to the admin instead of the user
            # waiting forever for a link that is not coming.
            with _db().session() as s:
                s.add(PasswordReset(user_id=u.id, token_hash=""))
                s.commit()
            log.warning("reset mail to %s failed; queued for the admin", email)
    return answer


@router.post("/api/password/reset")
def reset(body: ResetIn):
    token = (body.token or "").strip()
    password = body.password or ""
    if len(password) < MIN_PASSWORD:
        raise HTTPException(400, f"Use at least {MIN_PASSWORD} characters.")

    with _db().session() as s:
        row = s.execute(
            select(PasswordReset).where(PasswordReset.token_hash == hash_reset_token(token))
        ).scalar_one_or_none()
        if row is None or row.used_at is not None:
            raise HTTPException(400, "This link is not valid any more.")
        exp = _aware(row.expires_at)
        if exp is None or exp < _now():
            raise HTTPException(400, "This link has expired.")

        u = s.get(User, row.user_id)
        if u is None:
            raise HTTPException(400, "This link is not valid any more.")

        u.password_hash = hash_password(password)
        # Log out everywhere: every cookie carries the old epoch.
        u.session_epoch = int(u.session_epoch or 0) + 1
        row.used_at = _now()
        for other in s.execute(
            select(PasswordReset).where(
                PasswordReset.user_id == u.id,
                PasswordReset.used_at.is_(None),
            )
        ).scalars():
            other.used_at = _now()
        s.commit()
        log.info("password reset completed for user %s", u.id)
    return {"ok": True}


# ------------------------------------------------------- admin fallback
class ResetLinkOut(BaseModel):
    url: str
    email: str
    expires_in_min: int


@router.get("/api/admin/password-requests")
def admin_requests(request: Request):
    """Requests nobody has answered yet (no link issued by mail)."""
    from .main import _current_admin
    with _db().session() as s:
        _current_admin(request, s)
        rows = s.execute(
            select(PasswordReset)
            .where(PasswordReset.token_hash == "", PasswordReset.used_at.is_(None))
            .order_by(PasswordReset.created_at.desc())
        ).scalars().all()
        out = []
        for r in rows:
            u = s.get(User, r.user_id)
            created = _aware(r.created_at)
            age_min = int((_now() - created).total_seconds() // 60) if created else 0
            out.append({"id": r.id, "user_id": r.user_id,
                        "email": u.email if u else "?", "age_min": age_min})
        return {"requests": out}


@router.post("/api/admin/users/{user_id}/reset-link")
def admin_reset_link(user_id: int, request: Request):
    """Hand the admin a link to forward, when mail is off or the mail bounced."""
    from .main import _current_admin
    with _db().session() as s:
        _current_admin(request, s)
        u = s.get(User, user_id)
        if u is None:
            raise HTTPException(404, "no such user")
        raw = _issue(s, u)
        # The request that prompted this is now answered.
        for r in s.execute(
            select(PasswordReset).where(
                PasswordReset.user_id == u.id,
                PasswordReset.token_hash == "",
                PasswordReset.used_at.is_(None),
            )
        ).scalars():
            r.used_at = _now()
        s.commit()
        email = u.email
    return {"url": _reset_url(raw), "email": email, "expires_in_min": TOKEN_TTL_MIN}
