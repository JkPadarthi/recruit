"""Resend webhooks — the only way we learn an address was never real.

A signup inserts the row first and then mails the code, so a typo like
`akash@vitstudent.ac.in` creates an account that can never be verified and would sit in
the users table forever. Resend already knows the mail bounced; this endpoint is how that
knowledge gets back into the database.

Signature is Svix-style: base64(hmac_sha256(secret, "id.timestamp.body")). Rejecting bad
signatures matters more than usual here — the payload can delete accounts.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import logging
import time

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import delete, select

from .config import settings
from .models import FcmToken, PasswordReset, PushSubscription, User, UserId

log = logging.getLogger(__name__)
router = APIRouter()

TOLERANCE_S = 300  # Svix's own default; a replayed old payload is not interesting to us


def verify(secret: str, headers, body: bytes) -> bool:
    """Constant-time check of the svix-* headers against the raw body."""
    msg_id = headers.get("svix-id", "")
    msg_ts = headers.get("svix-timestamp", "")
    signatures = headers.get("svix-signature", "")
    if not (msg_id and msg_ts and signatures):
        return False
    try:
        if abs(time.time() - int(msg_ts)) > TOLERANCE_S:
            return False
    except ValueError:
        return False

    key = base64.b64decode(secret.split("_", 1)[1]) if secret.startswith("whsec_") else secret.encode()
    signed = f"{msg_id}.{msg_ts}.".encode() + body
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()

    for part in signatures.split():
        version, _, candidate = part.partition(",")
        if version == "v1" and hmac.compare_digest(candidate, expected):
            return True
    return False


def _purge(s, user: User) -> None:
    """Remove the account and everything hanging off it."""
    for model in (FcmToken, PushSubscription, PasswordReset, UserId):
        s.execute(delete(model).where(model.user_id == user.id))
    s.delete(user)


@router.post("/api/webhooks/resend")
async def resend_webhook(request: Request):
    secret = settings.resend_webhook_secret
    if not secret:
        # Louder than accepting unsigned deletions of user rows.
        raise HTTPException(503, "webhook secret not configured")

    raw = await request.body()
    if not verify(secret, request.headers, raw):
        log.warning("resend webhook rejected: bad signature")
        raise HTTPException(401, "bad signature")

    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "not json")

    kind = event.get("type", "")
    data = event.get("data") or {}
    recipients = data.get("to") or []
    if isinstance(recipients, str):
        recipients = [recipients]
    bounce = (data.get("bounce") or {})
    hard = str(bounce.get("type", "")).lower() in ("permanent", "hard")

    from .main import db

    removed, flagged = [], []
    with db.session() as s:
        for addr in recipients:
            email = str(addr).strip().lower()
            u = s.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if u is None:
                continue
            if kind == "email.bounced" and hard and not u.email_verified:
                # Never verified, and now we know why: the address does not exist.
                _purge(s, u)
                removed.append(email)
            else:
                # A real account with a broken mailbox: keep it, but say so, because
                # password resets to this address will silently vanish.
                u.email_bounced_at = dt.datetime.now(dt.timezone.utc)
                flagged.append(email)
        s.commit()

    if removed:
        log.warning("bounced address removed (unverified): %s", ", ".join(removed))
    if flagged:
        log.warning("bounce recorded for verified account(s): %s", ", ".join(flagged))
    return {"ok": True, "removed": removed, "flagged": flagged, "type": kind}
