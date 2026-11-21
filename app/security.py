"""Auth helpers: scrypt password hashing + HMAC-signed session cookie."""
from __future__ import annotations

import hashlib
import hmac
import json
import time

from .config import settings


def hash_password(password: str) -> str:
    salt = hashlib.sha256(settings.secret_key.encode()).digest()
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1).hex()


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        return hmac.compare_digest(hash_password(password), stored_hash)
    except Exception:
        return False


def _sign(payload: bytes) -> bytes:
    return hmac.new(settings.secret_key.encode(), payload, hashlib.sha256).digest()


def make_session_token(user_id: int, epoch: int = 0) -> str:
    """`epoch` is the user's session_epoch at issue time.

    Bumping it (a password reset does) makes every previously issued cookie fail
    verification — "log out everywhere" without keeping a session table.
    """
    body = json.dumps(
        {"uid": user_id, "ep": int(epoch), "exp": int(time.time()) + settings.session_max_age_sec},
        separators=(",", ":"),
    )
    sig = _sign(body.encode()).hex()
    return f"{body.encode().hex()}.{sig}"


def decode_session(token: str) -> dict | None:
    """The signed payload, or None. Signature and expiry only — the caller checks
    the epoch against the database, because that is what a reset changes."""
    if not token:
        return None
    try:
        body_hex, sig = token.split(".", 1)
        body = bytes.fromhex(body_hex)
        if not hmac.compare_digest(_sign(body).hex(), sig):
            return None
        data = json.loads(body)
        if data.get("exp", 0) < time.time():
            return None
        return data
    except Exception:
        return None


def verify_session_token(token: str) -> int | None:
    """Return user_id if the token is signed and unexpired, else None.

    Does NOT know about session_epoch — use decode_session + a database check where
    a password may have been reset.
    """
    data = decode_session(token)
    return int(data.get("uid", -1)) if data else None

def new_reset_token() -> str:
    """A one-time URL token. Long and random, because it IS the credential."""
    import secrets
    return secrets.token_urlsafe(32)


def hash_reset_token(raw: str) -> str:
    """Store only this. A stolen database must not yield working reset links."""
    return hashlib.sha256(raw.encode()).hexdigest()
