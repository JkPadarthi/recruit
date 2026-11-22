"""Signup must prove the address before it can receive anyone's shortlists.

Threat being closed: with the site public, anyone could register as
`someone.else@vitstudent.ac.in`, get that person's hits pushed to their own phone, and
leave the real owner unable to sign up.
"""
import datetime as dt

import pytest
from sqlalchemy import select

from app import verify as verify_mod
from app.main import db
from app.models import User


@pytest.fixture
def fixed_code(monkeypatch):
    monkeypatch.setattr(verify_mod, "new_code", lambda: "424242")
    return "424242"


def _user(email: str) -> User:
    with db.session() as s:
        return s.execute(select(User).where(User.email == email)).scalar_one()


@pytest.mark.asyncio
async def test_a_fresh_account_can_log_in_but_sees_no_data(client, register, fixed_code):
    """The gate: signed in, but everything except /api/me is closed."""
    await client.post("/api/register", json={"email": "new@vit.ac.in", "password": "pw12345"})
    r = await client.post("/api/login", json={"email": "new@vit.ac.in", "password": "pw12345"})
    assert r.status_code == 200
    assert r.json()["verified"] is False

    assert (await client.get("/api/me")).status_code == 200      # must know its own state
    blocked = await client.get("/api/hits")
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "email_unverified"
    assert (await client.get("/api/mails")).status_code == 403
    assert (await client.post("/api/me/ids", json={"register_id": "23BAI0021"})).status_code == 403


@pytest.mark.asyncio
async def test_the_right_code_opens_the_door(client, fixed_code):
    await client.post("/api/register", json={"email": "code@vit.ac.in", "password": "pw12345"})
    r = await client.post("/api/verify/confirm", json={"email": "code@vit.ac.in", "code": "424242"})
    assert r.status_code == 200, r.text
    assert r.json()["verified"] is True

    # confirming signs them in, so the client does not need a second round-trip
    assert (await client.get("/api/hits")).status_code == 200
    assert _user("code@vit.ac.in").email_verified == 1


@pytest.mark.asyncio
async def test_a_wrong_code_counts_down_and_then_locks(client, fixed_code):
    await client.post("/api/register", json={"email": "wrong@vit.ac.in", "password": "pw12345"})
    for i in range(verify_mod.MAX_ATTEMPTS):
        r = await client.post("/api/verify/confirm",
                              json={"email": "wrong@vit.ac.in", "code": "000000"})
        assert r.status_code == 400
        assert f"{verify_mod.MAX_ATTEMPTS - i - 1} tries left" in r.json()["detail"]

    # ceiling reached: even the right code is refused now
    r = await client.post("/api/verify/confirm",
                          json={"email": "wrong@vit.ac.in", "code": fixed_code})
    assert r.status_code == 429
    assert _user("wrong@vit.ac.in").email_verified == 0


@pytest.mark.asyncio
async def test_an_expired_code_is_refused(client, fixed_code):
    await client.post("/api/register", json={"email": "old@vit.ac.in", "password": "pw12345"})
    with db.session() as s:
        u = s.execute(select(User).where(User.email == "old@vit.ac.in")).scalar_one()
        u.verify_expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
        s.commit()

    r = await client.post("/api/verify/confirm",
                          json={"email": "old@vit.ac.in", "code": fixed_code})
    assert r.status_code == 400
    assert "expired" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_the_code_is_not_stored_in_the_clear(client, fixed_code):
    await client.post("/api/register", json={"email": "hash@vit.ac.in", "password": "pw12345"})
    u = _user("hash@vit.ac.in")
    assert u.verify_code_hash and u.verify_code_hash != fixed_code
    assert len(u.verify_code_hash) == 64  # sha256 hex


@pytest.mark.asyncio
async def test_an_unknown_address_gets_the_same_answer(client):
    """No oracle: a stranger cannot learn which addresses have accounts."""
    r = await client.post("/api/verify/start", json={"email": "nobody@vit.ac.in"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert "on its way" in r.json()["message"]


@pytest.mark.asyncio
async def test_resending_too_soon_is_refused_quietly(client, fixed_code):
    await client.post("/api/register", json={"email": "again@vit.ac.in", "password": "pw12345"})
    r = await client.post("/api/verify/start", json={"email": "again@vit.ac.in"})
    assert r.status_code == 200
    assert "moments ago" in r.json()["message"]


@pytest.mark.asyncio
async def test_a_verified_account_passes_straight_through(client, register):
    """Everyone who signed up before this existed must not be locked out."""
    await register("trusted@vit.ac.in", "pw12345")
    with db.session() as s:
        u = s.execute(select(User).where(User.email == "trusted@vit.ac.in")).scalar_one()
        u.email_verified = 1
        s.commit()
    assert (await client.get("/api/hits")).status_code == 200


@pytest.mark.asyncio
async def test_a_broken_mailer_does_not_lose_the_signup(client, monkeypatch):
    """SMTP down means code_sent False, not a 500 and a lost account."""
    monkeypatch.setattr(verify_mod.mailer, "send", lambda *a, **k: False)
    r = await client.post("/api/register",
                          json={"email": "mailfail@vit.ac.in", "password": "pw12345"})
    assert r.status_code == 200, r.text
    assert r.json()["code_sent"] is False
    assert _user("mailfail@vit.ac.in") is not None


@pytest.mark.asyncio
async def test_the_register_domain_gate_still_comes_first(client, monkeypatch):
    from app import main as main_module
    import dataclasses
    monkeypatch.setattr(main_module, "settings",
                        dataclasses.replace(main_module.settings,
                                            allowed_email_domains=["vit.ac.in"]))
    r = await client.post("/api/register",
                          json={"email": "stranger@gmail.com", "password": "pw12345"})
    assert r.status_code == 403
