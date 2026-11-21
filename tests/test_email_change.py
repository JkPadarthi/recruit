"""Changing the login email.

The email is both the login identifier and the password-reset destination, so this
endpoint carries more risk than the rest of the profile form: a stolen session must not
be able to move the account somewhere the owner cannot reach.
"""
import dataclasses

import pytest

from app import main as main_module
from app.config import settings


@pytest.mark.asyncio
async def test_a_wrong_password_changes_nothing(client, register):
    await register("old@vit.ac.in", "pw12345")
    r = await client.put("/api/me/email",
                         json={"email": "new@vit.ac.in", "password": "not-the-password"})
    assert r.status_code == 401
    # still the original address
    me = (await client.get("/api/me")).json()
    assert me["email"] == "old@vit.ac.in"


@pytest.mark.asyncio
async def test_the_new_address_is_the_one_you_log_in_with(client, register):
    await register("first@vit.ac.in", "pw12345")
    r = await client.put("/api/me/email",
                         json={"email": "second@vit.ac.in", "password": "pw12345"})
    assert r.status_code == 200, r.text
    assert r.json()["changed"] is True

    old = await client.post("/api/login",
                            json={"email": "first@vit.ac.in", "password": "pw12345"})
    assert old.status_code == 401

    new = await client.post("/api/login",
                            json={"email": "second@vit.ac.in", "password": "pw12345"})
    assert new.status_code == 200


@pytest.mark.asyncio
async def test_an_address_belonging_to_someone_else_is_refused(client, register):
    await register("taken@vit.ac.in", "pw12345")
    await register("mine@vit.ac.in", "pw12345")
    r = await client.put("/api/me/email",
                         json={"email": "taken@vit.ac.in", "password": "pw12345"})
    assert r.status_code == 409
    # and the original owner is untouched
    assert (await client.get("/api/me")).json()["email"] == "mine@vit.ac.in"


@pytest.mark.asyncio
async def test_the_signup_domain_gate_applies_here_too(client, register, monkeypatch):
    """A typo like gmaill.com is the whole reason this exists — it must be caught here."""
    await register("gate@vit.ac.in", "pw12345")
    # Settings is a frozen dataclass — swap the module's binding for a copy instead.
    monkeypatch.setattr(
        main_module, "settings",
        dataclasses.replace(settings, allowed_email_domains=["vit.ac.in"]))
    r = await client.put("/api/me/email",
                         json={"email": "gate@gmail.com", "password": "pw12345"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_resubmitting_the_same_address_is_a_no_op(client, register):
    await register("same@vit.ac.in", "pw12345")
    r = await client.put("/api/me/email",
                         json={"email": "same@vit.ac.in", "password": "pw12345"})
    assert r.status_code == 200
    assert r.json()["changed"] is False


@pytest.mark.asyncio
async def test_a_shapeless_string_is_rejected(client, register):
    await register("shape@vit.ac.in", "pw12345")
    for bad in ("not-an-email", "@vit.ac.in", "x@"):
        r = await client.put("/api/me/email", json={"email": bad, "password": "pw12345"})
        assert r.status_code == 400, bad


@pytest.mark.asyncio
async def test_the_rest_of_the_profile_survives_a_change(client, register):
    await register("keep@vit.ac.in", "pw12345", name="Real Name", branch="AIML")
    await client.put("/api/me/email",
                     json={"email": "kept@vit.ac.in", "password": "pw12345"})
    me = (await client.get("/api/me")).json()
    assert me["email"] == "kept@vit.ac.in"
    assert me["name"] == "Real Name"
    assert me["branch"] == "AIML"
