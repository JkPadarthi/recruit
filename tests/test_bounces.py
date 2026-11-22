"""Resend bounce webhooks and the unverified-account broom.

Two failures this covers:
  * a typo'd address (`akash@vitstudent.ac.in`) can never verify, so the row is junk;
  * a bounce is the only evidence we get that an address does not exist.
"""
import base64
import dataclasses
import datetime as dt
import hashlib
import hmac
import json
import time

import pytest
from sqlalchemy import select

from app import bounces, verify as verify_mod
from app.main import db
from app.models import User

SECRET = "whsec_" + base64.b64encode(b"test-signing-key-0123456789").decode()


def _sign(body: bytes, msg_id="msg_1", ts=None):
    ts = str(ts or int(time.time()))
    key = base64.b64decode(SECRET.split("_", 1)[1])
    sig = base64.b64encode(hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    return {"svix-id": msg_id, "svix-timestamp": ts, "svix-signature": f"v1,{sig}",
            "content-type": "application/json"}


@pytest.fixture
def secret(monkeypatch):
    # Settings is a frozen dataclass — swap the module's binding, not the field.
    monkeypatch.setattr(bounces, "settings",
                        dataclasses.replace(bounces.settings, resend_webhook_secret=SECRET))
    return SECRET


def _user(email: str, verified: int) -> None:
    with db.session() as s:
        s.add(User(email=email, password_hash="x", email_verified=verified))
        s.commit()


def _exists(email: str) -> bool:
    with db.session() as s:
        return s.execute(select(User).where(User.email == email)).scalar_one_or_none() is not None


def _payload(email: str, kind="email.bounced", bounce_type="Permanent") -> bytes:
    return json.dumps({"type": kind,
                       "data": {"to": [email], "bounce": {"type": bounce_type}}}).encode()


@pytest.mark.asyncio
async def test_a_hard_bounce_deletes_an_unverified_account(client, secret):
    _user("typo@vit.ac.in", verified=0)
    body = _payload("typo@vit.ac.in")
    r = await client.post("/api/webhooks/resend", content=body, headers=_sign(body))
    assert r.status_code == 200, r.text
    assert r.json()["removed"] == ["typo@vit.ac.in"]
    assert not _exists("typo@vit.ac.in")


@pytest.mark.asyncio
async def test_a_hard_bounce_keeps_a_verified_account_but_flags_it(client, secret):
    """Their shortlists are real; the mailbox is what is broken."""
    _user("real@vit.ac.in", verified=1)
    body = _payload("real@vit.ac.in")
    r = await client.post("/api/webhooks/resend", content=body, headers=_sign(body))
    assert r.status_code == 200
    assert r.json()["flagged"] == ["real@vit.ac.in"]
    assert _exists("real@vit.ac.in")
    with db.session() as s:
        u = s.execute(select(User).where(User.email == "real@vit.ac.in")).scalar_one()
        assert u.email_bounced_at is not None
        assert u.email_verified == 1          # never lock a real user out


@pytest.mark.asyncio
async def test_a_soft_bounce_changes_nothing(client, secret):
    _user("full@vit.ac.in", verified=0)
    body = _payload("full@vit.ac.in", bounce_type="Transient")
    r = await client.post("/api/webhooks/resend", content=body, headers=_sign(body))
    assert r.status_code == 200
    assert r.json()["removed"] == []
    assert _exists("full@vit.ac.in")          # a full mailbox is not a dead address


@pytest.mark.asyncio
async def test_a_forged_signature_is_refused(client, secret):
    _user("victim@vit.ac.in", verified=0)
    body = _payload("victim@vit.ac.in")
    headers = _sign(body)
    headers["svix-signature"] = "v1," + base64.b64encode(b"nope").decode()
    r = await client.post("/api/webhooks/resend", content=body, headers=headers)
    assert r.status_code == 401
    assert _exists("victim@vit.ac.in")        # nothing deleted


@pytest.mark.asyncio
async def test_a_stale_timestamp_is_refused(client, secret):
    _user("old@vit.ac.in", verified=0)
    body = _payload("old@vit.ac.in")
    r = await client.post("/api/webhooks/resend", content=body,
                          headers=_sign(body, ts=int(time.time()) - 3600))
    assert r.status_code == 401
    assert _exists("old@vit.ac.in")


@pytest.mark.asyncio
async def test_without_a_secret_the_endpoint_refuses_to_run(client, monkeypatch):
    """Accepting unsigned deletions of user rows would be worse than failing loudly."""
    monkeypatch.setattr(bounces, "settings",
                        dataclasses.replace(bounces.settings, resend_webhook_secret=""))
    body = _payload("anyone@vit.ac.in")
    r = await client.post("/api/webhooks/resend", content=body,
                          headers={"svix-id": "x", "svix-timestamp": "1", "svix-signature": "v1,x"})
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_the_sweep_only_takes_untouched_rows(client):
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=48)
    with db.session() as s:
        s.add(User(email="stale@vit.ac.in", password_hash="x", email_verified=0, created_at=old))
        s.add(User(email="fresh@vit.ac.in", password_hash="x", email_verified=0))
        s.add(User(email="good@vit.ac.in", password_hash="x", email_verified=1, created_at=old))
        s.commit()

    gone = verify_mod.sweep_unverified(hours=24)
    assert gone == 1
    assert not _exists("stale@vit.ac.in")
    assert _exists("fresh@vit.ac.in")     # too new
    assert _exists("good@vit.ac.in")      # verified


@pytest.mark.asyncio
async def test_a_delivered_event_flags_nothing(client, secret):
    """The endpoint is subscribed to delivered/opened/sent too — those are not bounces."""
    _user("fine@vit.ac.in", verified=1)
    body = json.dumps({"type": "email.delivered", "data": {"to": ["fine@vit.ac.in"]}}).encode()
    r = await client.post("/api/webhooks/resend", content=body, headers=_sign(body))
    assert r.status_code == 200
    assert r.json()["ignored"] == "email.delivered"
    with db.session() as s:
        u = s.execute(select(User).where(User.email == "fine@vit.ac.in")).scalar_one()
        assert u.email_bounced_at is None


@pytest.mark.asyncio
async def test_a_suppressed_address_loses_its_unverified_account(client, secret):
    _user("suppressed@vit.ac.in", verified=0)
    body = json.dumps({"type": "email.suppressed", "data": {"to": ["suppressed@vit.ac.in"]}}).encode()
    r = await client.post("/api/webhooks/resend", content=body, headers=_sign(body))
    assert r.status_code == 200
    assert not _exists("suppressed@vit.ac.in")


@pytest.mark.asyncio
async def test_a_complaint_flags_a_verified_account(client, secret):
    _user("angry@vit.ac.in", verified=1)
    body = json.dumps({"type": "email.complained", "data": {"to": ["angry@vit.ac.in"]}}).encode()
    r = await client.post("/api/webhooks/resend", content=body, headers=_sign(body))
    assert r.status_code == 200
    with db.session() as s:
        u = s.execute(select(User).where(User.email == "angry@vit.ac.in")).scalar_one()
        assert u.email_bounced_at is not None and u.email_verified == 1
