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


@pytest.mark.asyncio
async def test_the_old_host_gets_a_page_that_says_we_moved(client):
    r = await client.get("/", headers={"Host": "recruit.98487840.xyz", "Accept": "text/html"})
    assert r.status_code == 200
    assert "moved" in r.text.lower()
    assert "recruit.jaswanth.me" in r.text


@pytest.mark.asyncio
async def test_the_old_host_308s_api_calls(client):
    """A 308 keeps the method — a 301 would turn a POST into a GET and lose the body."""
    r = await client.get("/api/hits", follow_redirects=False,
                         headers={"Host": "recruit.98487840.xyz", "Accept": "application/json"})
    assert r.status_code == 308
    assert r.headers["location"] == "https://recruit.jaswanth.me/api/hits"


@pytest.mark.asyncio
async def test_the_canonical_host_is_left_alone(client):
    r = await client.get("/", headers={"Host": "recruit.jaswanth.me", "Accept": "text/html"})
    assert r.status_code == 200
    assert "landing-hero" in r.text
