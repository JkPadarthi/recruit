"""Auth, onboarding, hits, and end-to-end ingest → match → hit."""
from tests.conftest import register  # noqa: F401 (fixture)


CDC_MAIL = b"From: vitianscdc2027@vitstudent.ac.in\r\nSubject: Selection List 2027\r\n\r\nHoneywell list: 23BAI0021 and 23BCE0654 are selected.\r\n"


async def _ingest(raw, uid="999"):
    from app.main import db as module_db
    from app.ingest import process_message
    with module_db.session() as s:
        return process_message(raw, uid, s)


async def test_register_login_me(client, register):
    await register()
    r = await client.get("/api/me")
    assert r.status_code == 200
    assert r.json()["email"] == "user@vit.ac.in"


async def test_duplicate_register_rejected(client, register):
    await register()
    r = await client.post("/api/register", json={"email": "user@vit.ac.in", "password": "pw12345"})
    assert r.status_code == 409


async def test_wrong_password(client, register):
    await register()
    r = await client.post("/api/login", json={"email": "user@vit.ac.in", "password": "nope"})
    assert r.status_code == 401


async def test_unauth_me(client):
    assert (await client.get("/api/me")).status_code == 401


async def test_logout_clears_session(client, register):
    await register()
    me = await client.get("/api/me")
    assert me.status_code == 200
    # logout (POST) must clear the cookie and redirect home
    r = await client.post("/api/logout")
    assert r.status_code == 303
    assert r.headers.get("location") == "/"
    # cookie cleared -> subsequent /api/me is 401
    assert (await client.get("/api/me")).status_code == 401


async def test_add_and_list_ids(client, register):
    await register()
    r = await client.post("/api/me/ids", json={"register_id": "23BAI0021"})
    assert r.status_code == 200
    assert r.json()["added"] is True
    me = (await client.get("/api/me")).json()
    assert any(i["normalized_id"] == "23BAI0021" for i in me["ids"])


async def test_add_invalid_id_rejected(client, register):
    await register()
    r = await client.post("/api/me/ids", json={"register_id": "gsdfgsdfg"})
    assert r.status_code == 422


async def test_push_toggle_subscribe_unsubscribe(client, register):
    await register()
    ep = "https://fcm.googleapis.com/fcm/send/NOTIFY_TEST_ENDPOINT_123"
    r = await client.post("/api/push/subscribe", json={"endpoint": ep, "platform": "web"})
    assert r.status_code == 200 and r.json()["subscribed"] is True
    # unsubscribing removes only THIS device, not others
    ep2 = "https://fcm.googleapis.com/fcm/send/NOTIFY_TEST_ENDPOINT_456"
    await client.post("/api/push/subscribe", json={"endpoint": ep2, "platform": "web"})
    r = await client.post("/api/push/unsubscribe", json={"endpoint": ep, "platform": "web"})
    assert r.json()["unsubscribed"] is True
    r2 = await client.post("/api/push/unsubscribe", json={"endpoint": ep, "platform": "web"})
    assert r2.json()["unsubscribed"] is False  # already gone
    # ep2 must still be present
    from app.main import db as module_db
    from app.models import PushSubscription
    from sqlalchemy import select
    with module_db.session() as s:
        remaining = s.execute(select(PushSubscription).where(
            PushSubscription.endpoint.in_([ep, ep2]))).scalars().all()
    assert [x.endpoint for x in remaining] == [ep2]


async def test_delete_id(client, register):
    await register()
    await client.post("/api/me/ids", json={"register_id": "23BAI0021"})
    r = await client.delete("/api/me/ids/23BAI0021")
    assert r.status_code == 200
    me = (await client.get("/api/me")).json()
    assert me["ids"] == []


async def test_end_to_end_hit(client, register):
    await register()
    await client.post("/api/me/ids", json={"register_id": "23BAI0021"})
    kind = await _ingest(CDC_MAIL, "777")
    assert kind == "shortlist"
    hits = (await client.get("/api/hits")).json()
    assert hits["unread"] == 1
    assert hits["hits"][0]["normalized_id"] == "23BAI0021"


async def test_mark_read(client, register):
    await register()
    await client.post("/api/me/ids", json={"register_id": "23BAI0021"})
    await _ingest(CDC_MAIL, "778")
    hits = (await client.get("/api/hits")).json()
    hit_id = hits["hits"][0]["id"]
    r = await client.post(f"/api/hits/{hit_id}/read")
    assert r.status_code == 200
    assert (await client.get("/api/hits")).json()["unread"] == 0


async def test_ignored_non_cdc_sender(client):
    from app.ingest import process_message
    from app.main import db as module_db
    raw = b"From: nptel@iitm.ac.in\r\nSubject: newsletter\r\n\r\nhi\r\n"
    with module_db.session() as s:
        kind = process_message(raw, "123", s)
    assert kind == "ignored"


async def test_match_idempotent(client, register):
    from app.ingest import process_message
    from app.main import db as module_db
    await register()
    await client.post("/api/me/ids", json={"register_id": "23BAI0021"})
    with module_db.session() as s:
        process_message(CDC_MAIL, "779", s)
        process_message(CDC_MAIL, "779", s)  # same uid -> duplicate
    hits = (await client.get("/api/hits")).json()
    assert hits["unread"] == 1


async def test_admin_endpoint_requires_admin(client, register):
    await register()
    assert (await client.get("/api/admin/stats")).status_code == 403
    r = await client.post("/api/admin/test-push", json={"user_id": 1, "body": "x"})
    assert r.status_code == 403


async def test_admin_stats_and_test_push_admin_ok(client, register):
    await register("admin@vit.ac.in", "pw12345")  # admin by ADMIN_EMAIL match
    r = await client.get("/api/admin/stats")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["users"], list) and body["users"][0]["admin"] is True
    uid = body["users"][0]["id"]
    tr = await client.post("/api/admin/test-push", json={"user_id": uid, "title": "t", "body": "b"})
    assert tr.status_code == 200
    assert tr.json()["live_devices"] == 0