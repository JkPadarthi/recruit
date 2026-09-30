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


def make_session_token(user_id: int) -> str:
    body = json.dumps({"uid": user_id, "exp": int(time.time()) + settings.session_max_age_sec},
                      separators=(",", ":"))
    sig = _sign(body.encode()).hex()
    return f"{body.encode().hex()}.{sig}"


def verify_session_token(token: str) -> int | None:
    """Return user_id if token valid + unexpired, else None."""
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
        return int(data.get("uid", -1))
    except Exception:
        return None