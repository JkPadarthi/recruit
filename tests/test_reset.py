"""Forgotten passwords: request, redeem, expire, and log out everywhere.

The four failures that would hurt, in order of nastiness:
  1. a link that still works after being used,
  2. an old session cookie that survives a password change,
  3. an endpoint that reveals which addresses are registered,
  4. a request that silently vanishes because mail is not configured.
"""
import datetime as dt

import pytest
from sqlalchemy import select

from app.main import db as module_db
from app.models import PasswordReset, User
from app.security import make_session_token


def _user(email: str) -> User:
    with module_db.session() as s:
        return s.execute(select(User).where(User.email == email)).scalar_one()


@pytest.mark.asyncio
async def test_unknown_address_gets_the_same_answer(client, register):
    await register(email="known@vit.ac.in")
    r = await client.post("/api/password/forgot", json={"email": "nobody@vit.ac.in"})
    assert r.status_code == 200
    assert "reset link is on its way" in r.json()["message"]
    with module_db.session() as s:
        assert s.execute(select(PasswordReset)).scalars().all() == []


@pytest.mark.asyncio
async def test_request_without_smtp_is_recorded_for_the_admin(client, register):
    await register(email="mailer-off@vit.ac.in")
    r = await client.post("/api/password/forgot", json={"email": "mailer-off@vit.ac.in"})
    assert r.json()["email_configured"] is False
    with module_db.session() as s:
        rows = s.execute(select(PasswordReset)).scalars().all()
    assert len(rows) == 1
    # No link issued: this is the row the admin panel lists.
    assert rows[0].token_hash == ""


@pytest.mark.asyncio
async def test_admin_can_issue_a_link_and_it_works_once(client, register):
    email, _ = await register(email="admin-issued@vit.ac.in")
    uid = _user(email).id
    with module_db.session() as s:
        u = s.get(User, uid)
        u.is_admin = True
        s.commit()

    r = await client.post(f"/api/admin/users/{uid}/reset-link")
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    token = url.split("t=", 1)[1]

    ok = await client.post("/api/password/reset", json={"token": token, "password": "newpass123"})
    assert ok.status_code == 200, ok.text

    # Second use of the same link must fail — this is the whole point of one-time.
    again = await client.post("/api/password/reset", json={"token": token, "password": "another123"})
    assert again.status_code == 400


@pytest.mark.asyncio
async def test_reset_signs_out_existing_sessions(client, register):
    email, old_pw = await register(email="epoch@vit.ac.in")
    uid = _user(email).id
    with module_db.session() as s:
        u = s.get(User, uid)
        u.is_admin = True
        s.commit()

    # A session issued before the reset, at the user's current epoch.
    stale = make_session_token(uid, _user(email).session_epoch or 0)

    url = (await client.post(f"/api/admin/users/{uid}/reset-link")).json()["url"]
    token = url.split("t=", 1)[1]
    assert (await client.post("/api/password/reset",
                              json={"token": token, "password": "brandnew123"})).status_code == 200

    r = await client.get("/api/me", headers={"Cookie": f"recruit_session={stale}"})
    assert r.status_code == 401
    assert "sign in again" in r.text

    # The new password works; the old one does not.
    await client.post("/api/logout")
    assert (await client.post("/api/login",
                              json={"email": email, "password": "brandnew123"})).status_code == 200
    assert (await client.post("/api/login",
                              json={"email": email, "password": old_pw})).status_code == 401


@pytest.mark.asyncio
async def test_expired_link_is_refused(client, register):
    email, _ = await register(email="expired@vit.ac.in")
    uid = _user(email).id
    with module_db.session() as s:
        u = s.get(User, uid)
        u.is_admin = True
        s.commit()
    url = (await client.post(f"/api/admin/users/{uid}/reset-link")).json()["url"]
    token = url.split("t=", 1)[1]

    with module_db.session() as s:
        row = s.execute(select(PasswordReset).where(PasswordReset.token_hash != "")).scalars().first()
        row.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
        s.commit()

    r = await client.post("/api/password/reset", json={"token": token, "password": "whatever123"})
    assert r.status_code == 400
    assert "expired" in r.text


@pytest.mark.asyncio
async def test_short_password_is_refused(client, register):
    email, _ = await register(email="short@vit.ac.in")
    uid = _user(email).id
    with module_db.session() as s:
        u = s.get(User, uid)
        u.is_admin = True
        s.commit()
    token = (await client.post(f"/api/admin/users/{uid}/reset-link")).json()["url"].split("t=", 1)[1]
    r = await client.post("/api/password/reset", json={"token": token, "password": "short"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_mail_path_issues_a_token_when_smtp_is_configured(client, register, monkeypatch):
    """With a mailer, the link goes out by email instead of to the admin panel."""
    import app.reset as reset_mod

    await register(email="mailed@vit.ac.in")
    monkeypatch.setattr(reset_mod.mailer, "enabled", lambda: True)
    sent = {}
    monkeypatch.setattr(reset_mod.mailer, "send",
                        lambda to, subject, text, html="": sent.update(to=to, text=text) or True)

    r = await client.post("/api/password/forgot", json={"email": "mailed@vit.ac.in"})
    assert r.json()["email_configured"] is True
    assert sent["to"] == "mailed@vit.ac.in"
    assert "/reset?t=" in sent["text"]

    with module_db.session() as s:
        row = s.execute(select(PasswordReset)).scalars().first()
    assert row.token_hash != "", "a real token should have been issued"
