"""Email verification.

Why this exists: signup used to trust the address you typed. With the site posted
publicly, that meant anyone could register as `someone.else@vitstudent.ac.in`, receive
that person's shortlists, and lock the real owner out of their own account.

Design notes:
  * A 6-digit code, not a link. Links get clicked from previews, scanned by mail
    security, and land in the wrong browser; a code is typed where it was requested.
  * Stored as a hash — the DB must never hold a usable code.
  * 30 minutes, 5 attempts, one send per minute. Entropy is only 10^6, so the attempt
    ceiling IS the security boundary.
  * Same answer whether or not the address exists (no account-enumeration oracle).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
import re
import secrets

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from . import mailer
from .config import settings
from .models import User
from .security import make_session_token

log = logging.getLogger(__name__)
router = APIRouter()

CODE_TTL_MIN = 30
MAX_ATTEMPTS = 5
RESEND_COOLDOWN_S = 60


def _db():
    from .main import db  # lazy: main imports this module
    return db


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_code(email: str, code: str) -> str:
    return hashlib.sha256(f"{email.strip().lower()}:{code}".encode()).hexdigest()


def _body(code: str, email: str) -> tuple[str, str]:
    text = (
        f"Your {settings.brand_name} verification code is {code}\n\n"
        f"Type it in the app or on the site to finish signing up as {email}.\n"
        f"The code expires in {CODE_TTL_MIN} minutes and can be used once.\n\n"
        "If you did not ask for this, ignore it — the address will not be activated\n"
        "and no account gets access without the code.\n"
    )
    html = (
        f'<div style="font-family:system-ui,sans-serif;font-size:15px;line-height:1.55">'
        f'<p>Your <strong>{settings.brand_name}</strong> verification code:</p>'
        f'<p style="font-size:30px;font-weight:700;letter-spacing:6px;margin:18px 0">{code}</p>'
        f"<p>Type it in to finish signing up as {email}. It expires in "
        f"{CODE_TTL_MIN} minutes and works once.</p>"
        f'<p style="color:#667">If you did not ask for this, ignore this mail.</p></div>'
    )
    return text, html


def issue(s, user: User, *, force: bool = False) -> bool:
    """Create a code and mail it. Returns False when rate-limited.

    Mutates and commits `user`; the caller must not be in the middle of another
    write to the same row (the reset flow taught us that autoflush will bite).
    """
    now = _now()
    last = _aware(user.verify_last_sent)
    if not force and last and (now - last).total_seconds() < RESEND_COOLDOWN_S:
        return False

    code = new_code()
    user.verify_code_hash = hash_code(user.email, code)
    user.verify_expires_at = now + dt.timedelta(minutes=CODE_TTL_MIN)
    user.verify_attempts = 0
    user.verify_last_sent = now
    s.commit()

    text, html = _body(code, user.email)
    try:
        # mailer.send returns False (it does not raise) when SMTP is unconfigured or the
        # server refuses — reporting "sent" on False is how a user ends up waiting for a
        # code that was never sent.
        ok = mailer.send(user.email, f"Your {settings.brand_name} code: {code}", text, html)
    except Exception as exc:  # noqa: BLE001
        log.warning("verification mail raised for user %s: %s", user.id, exc)
        return False
    if not ok:
        log.warning("verification mail NOT sent for user %s", user.id)
        return False
    log.info("verification code sent to user %s", user.id)
    return True


class EmailIn(BaseModel):
    email: str


class CodeIn(BaseModel):
    email: str
    code: str


@router.post("/api/verify/start")
def start(body: EmailIn):
    """(Re)send a code. Identical answer for unknown or already-verified addresses."""
    email = (body.email or "").strip().lower()
    answer = {"ok": True, "message": "If that address needs a code, it is on its way."}
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return answer
    with _db().session() as s:
        u = s.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if u is None or u.email_verified:
            return answer
        if not issue(s, u):
            return {"ok": True, "message": "A code was sent moments ago — check your inbox."}
    return answer


@router.post("/api/verify/confirm")
def confirm(body: CodeIn, response: Response):
    email = (body.email or "").strip().lower()
    code = (body.code or "").strip()
    if not re.fullmatch(r"\d{6}", code):
        raise HTTPException(400, "That is not a six-digit code.")

    with _db().session() as s:
        u = s.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if u is None:
            raise HTTPException(400, "That code does not match. Check it and try again.")
        if u.email_verified:
            return {"verified": True, "email": u.email, "already": True}

        expires = _aware(u.verify_expires_at)
        if not u.verify_code_hash or not expires or expires < _now():
            raise HTTPException(400, "That code has expired. Send a new one.")

        if u.verify_attempts >= MAX_ATTEMPTS:
            raise HTTPException(429, "Too many attempts. Send a new code.")

        if not secrets.compare_digest(u.verify_code_hash, hash_code(u.email, code)):
            u.verify_attempts += 1
            s.commit()
            left = max(0, MAX_ATTEMPTS - u.verify_attempts)
            raise HTTPException(400, f"That code does not match. {left} tries left.")

        u.email_verified = 1
        u.verify_code_hash = ""
        u.verify_expires_at = None
        u.verify_attempts = 0
        s.commit()
        log.info("email verified for user %s", u.id)

        # Sign them in: they just proved they own the address, and it saves a second
        # round-trip through the login form.
        response.set_cookie(settings.session_cookie_name,
                            make_session_token(u.id, u.session_epoch or 0),
                            httponly=True, samesite="lax",
                            secure=settings.session_secure,
                            max_age=settings.session_max_age_sec)
        return {"verified": True, "email": u.email, "id": u.id, "admin": bool(u.is_admin)}
