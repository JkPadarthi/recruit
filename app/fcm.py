"""FCM HTTP v1 sender — the reliable notification path.

Web Push hands the message to a browser process Android is free to freeze; that is
why a shortlist could arrive 3.5 hours late. This hands it to Google Play Services,
a *system* component: high-priority messages are delivered during Doze and can even
start an app process Android had killed.

Auth note: HTTP v1 wants an OAuth2 bearer token. Instead of adding google-auth as a
dependency we mint the assertion ourselves (RS256 JWT signed with the service
account key via `cryptography`) and cache the access token until just before it
expires. One less library on a 512 MiB box.

Config: FCM_SERVICE_ACCOUNT = path to the Firebase service-account JSON.
Absent file => feature simply stays off (fcm.enabled() is False), never an error.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Iterable

import urllib.error
import urllib.parse
import urllib.request
from typing import cast

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .models import FcmToken

log = logging.getLogger("recruit.fcm")

_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_TOKEN_URI = "https://oauth2.googleapis.com/token"
_SEND_URI = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"

_cached_token: str = ""
_cached_exp: float = 0.0
_cached_project: str = ""


# ---------------------------------------------------------------- configuration
def _sa_path() -> Path | None:
    raw = (getattr(settings, "fcm_service_account", "") or "").strip()
    if not raw:
        return None
    p = Path(raw)
    return p if p.is_file() else None


def _service_account() -> dict | None:
    p = _sa_path()
    if p is None:
        return None
    try:
        return json.loads(p.read_text())
    except Exception as e:  # malformed JSON should not break ingest
        log.warning("FCM service account unreadable: %s", e)
        return None


def enabled() -> bool:
    return _service_account() is not None


# ------------------------------------------------------------------- token mint
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _access_token() -> tuple[str, str]:
    """(bearer, project_id). Cached in-process; refreshed 60s before expiry."""
    global _cached_token, _cached_exp, _cached_project
    now = time.time()
    if _cached_token and _cached_exp - 60 > now:
        return _cached_token, _cached_project

    sa = _service_account()
    if sa is None:
        raise RuntimeError("FCM service account not configured")

    iat = int(now)
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": sa["client_email"],
        "scope": _SCOPE,
        "aud": sa.get("token_uri", _TOKEN_URI),
        "iat": iat,
        "exp": iat + 3600,
    }
    signing_input = f"{_b64(json.dumps(header, separators=(',', ':')).encode())}." \
                    f"{_b64(json.dumps(claims, separators=(',', ':')).encode())}".encode()

    key = cast(rsa.RSAPrivateKey,
               serialization.load_pem_private_key(sa["private_key"].encode(), password=None))
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    assertion = signing_input.decode() + "." + _b64(signature)

    body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion,
    }).encode()
    req = urllib.request.Request(
        sa.get("token_uri", _TOKEN_URI), data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        payload = json.loads(r.read())

    _cached_token = str(payload["access_token"])
    _cached_exp = now + float(payload.get("expires_in", 3600))
    _cached_project = str(sa["project_id"])
    return _cached_token, _cached_project


# ------------------------------------------------------------------ token store
def register(db: Session, user_id: int, token: str, platform: str = "android") -> bool:
    """Idempotent. A token belongs to exactly one user; re-registering moves it."""
    token = (token or "").strip()
    if not token:
        return False
    row = db.execute(select(FcmToken).where(FcmToken.token == token)).scalar_one_or_none()
    if row:
        if row.user_id == user_id:
            row.platform = platform
            db.commit()
            return False
        row.user_id = user_id      # device handed to another account
        row.platform = platform
        db.commit()
        return True
    db.add(FcmToken(user_id=user_id, token=token, platform=platform))
    try:
        db.commit()
    except IntegrityError:          # concurrent double-register
        db.rollback()
        return False
    return True


def tokens_for(db: Session, user_ids: Iterable[int]) -> dict[int, list[str]]:
    ids = list(user_ids)
    if not ids:
        return {}
    out: dict[int, list[str]] = {}
    for row in db.execute(select(FcmToken).where(FcmToken.user_id.in_(ids))).scalars():
        out.setdefault(row.user_id, []).append(row.token)
    return out


def _drop(db: Session, token: str) -> None:
    db.execute(delete(FcmToken).where(FcmToken.token == token))
    db.commit()


# ----------------------------------------------------------------------- sender
def send(db: Session, per_user: dict[int, dict[str, str]]) -> dict[str, int]:
    """per_user: {user_id: {title, body, tag, url, when_iso, venue, event}}

    Returns {'sent': n, 'failed': n, 'pruned': n}. Never raises: a push failure must
    not roll back an ingest or abort delivery to the other users.
    """
    stats = {"sent": 0, "failed": 0, "pruned": 0}
    if not per_user or not enabled():
        return stats

    try:
        bearer, project = _access_token()
    except Exception as e:
        log.warning("FCM auth failed, skipping native push: %s", e)
        return stats

    by_user = tokens_for(db, per_user.keys())
    for uid, data in per_user.items():
        message_data = {k: str(v) for k, v in data.items() if v is not None and str(v) != ""}
        for token in by_user.get(uid, []):
            body = json.dumps({
                "message": {
                    "token": token,
                    "data": message_data,
                    "android": {"priority": "HIGH", "ttl": "3600s"},
                }
            }).encode()
            req = urllib.request.Request(
                _SEND_URI.format(project=project), data=body,
                headers={
                    "Authorization": f"Bearer {bearer}",
                    "Content-Type": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    r.read()
                stats["sent"] += 1
            except urllib.error.HTTPError as e:
                detail = e.read()[:400].decode(errors="replace")
                stats["failed"] += 1
                # UNREGISTERED / NOT_FOUND == the app was uninstalled: prune it.
                if e.code == 404 or "UNREGISTERED" in detail:
                    _drop(db, token)
                    stats["pruned"] += 1
                else:
                    log.warning("FCM %s for user %s: %s", e.code, uid, detail)
            except Exception as e:
                stats["failed"] += 1
                log.warning("FCM send error for user %s: %s", uid, e)
    return stats
