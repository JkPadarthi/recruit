"""The web side of verification: the code page exists, and unverified users are sent to it
rather than shown a dashboard full of empty lists."""
import pytest


@pytest.mark.asyncio
async def test_the_code_page_renders(client):
    r = await client.get("/verify")
    assert r.status_code == 200
    assert "verify-form" in r.text
    assert "six-digit" in r.text.lower()


@pytest.mark.asyncio
async def test_an_unverified_account_is_redirected_off_the_dashboard(client):
    await client.post("/api/register", json={"email": "web@vit.ac.in", "password": "pw12345"})
    login = await client.post("/api/login",
                              json={"email": "web@vit.ac.in", "password": "pw12345"})
    assert login.json()["verified"] is False

    r = await client.get("/dashboard", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/verify"


@pytest.mark.asyncio
async def test_a_verified_account_reaches_the_dashboard(client, register):
    await register("webok@vit.ac.in", "pw12345")
    r = await client.get("/dashboard", follow_redirects=False)
    assert r.status_code == 200
    assert "hits-sec" in r.text
