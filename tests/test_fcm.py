"""Native push: the deadline a phone can actually keep.

Two things are asserted here that matter more than the HTTP plumbing:
  1. a student's own sheet row becomes a real ISO timestamp (used for local alarms)
  2. the FCM fan-out is independent of web push — a phone-only user still gets it
"""
CDC_FROM = "vitianscdc2027@vitstudent.ac.in"


# ---- the deadline parser ---------------------------------------------------
def test_sheet_row_becomes_an_iso_deadline():
    from app.extract import slot_deadline
    assert slot_deadline("Date & Time: 23-11-2026 (2.30 pm) · Reporting venue: PRP 713") \
        == "2026-11-23T14:30:00+05:30"
    # already-compacted form (what /api/hits returns) parses identically
    assert slot_deadline("23-11-2026 (2:30 pm) · PRP 713") == "2026-11-23T14:30:00+05:30"
    # 12-hour edge cases
    assert slot_deadline("Date & Time: 01-01-2027 (12.15 pm)") == "2027-01-01T12:15:00+05:30"
    assert slot_deadline("Date & Time: 01-01-2027 (12.15 am)") == "2027-01-01T00:15:00+05:30"
    assert slot_deadline("Date & Time: 05-12-2026 (10.00 am)") == "2026-12-05T10:00:00+05:30"


def test_no_deadline_is_better_than_a_guessed_one():
    """A wrong alarm is worse than no alarm: date-only rows must yield nothing."""
    from app.extract import slot_deadline
    assert slot_deadline("23-11-2026") == ""
    assert slot_deadline("Reporting venue: PRP 713") == ""
    assert slot_deadline("") == ""
    assert slot_deadline("31-02-2026 (2.00 pm)") == ""      # impossible date


# ---- token registration ----------------------------------------------------
async def test_a_phone_registers_its_token(client, register):
    await register()
    r = await client.post("/api/push/fcm", json={"token": "tok-abc", "platform": "android"})
    assert r.status_code == 200 and r.json()["registered"] is True
    # idempotent
    r2 = await client.post("/api/push/fcm", json={"token": "tok-abc"})
    assert r2.status_code == 200


async def test_registration_requires_a_session(client):
    r = await client.post("/api/push/fcm", json={"token": "tok-anon"})
    assert r.status_code == 401


async def test_the_same_token_can_only_belong_to_one_account(client, register):
    """Handing a phone to a friend must move the token, not duplicate delivery."""
    from app.main import db as module_db
    from app.models import FcmToken
    from sqlalchemy import select

    await register(email="a@vitstudent.ac.in")
    await client.post("/api/push/fcm", json={"token": "shared-tok"})
    await client.post("/api/logout")
    await register(email="b@vitstudent.ac.in")
    r = await client.post("/api/push/fcm", json={"token": "shared-tok"})
    assert r.json()["moved_from_other_account"] is True

    with module_db.session() as s:
        rows = s.execute(select(FcmToken).where(FcmToken.token == "shared-tok")).scalars().all()
        assert len(rows) == 1


# ---- fan-out ---------------------------------------------------------------
async def test_fcm_gets_the_deadline_even_without_vapid(client, register, monkeypatch):
    """Web push keys are blank in tests; the native path must still carry the slot."""
    import app.fcm as fcm_mod
    from app.main import db as module_db
    import app.ingest as ing_mod
    from tests.test_slots import _mail_with_xlsx, ROWS

    await register()
    await client.post("/api/me/ids", json={"register_id": "K3I6O4I8"})
    await client.post("/api/push/fcm", json={"token": "tok-deadline"})

    captured: dict = {}
    monkeypatch.setattr(fcm_mod, "enabled", lambda: True)
    monkeypatch.setattr(fcm_mod, "send", lambda db, per_user: captured.update(per_user) or
                        {"sent": len(per_user), "failed": 0, "pruned": 0})

    with module_db.session() as s:
        ing_mod.process_message(_mail_with_xlsx(ROWS), "9800", s)

    assert captured, "FCM fan-out never ran"
    payload = next(iter(captured.values()))
    assert payload["when_iso"] == "2026-11-23T14:30:00+05:30"
    assert "PRP 713" in payload["body"]
    assert payload["url"] == "/dashboard#hits"
    assert payload["event"].lower().startswith("hcl")


async def test_unregister_removes_only_this_token(client, register):
    from app.main import db as module_db
    from app.models import FcmToken
    from sqlalchemy import select

    await register()
    await client.post("/api/push/fcm", json={"token": "t1"})
    await client.post("/api/push/fcm", json={"token": "t2"})
    r = await client.post("/api/push/fcm/unregister", json={"token": "t1"})
    assert r.json()["unregistered"] is True
    with module_db.session() as s:
        left = [x.token for x in s.execute(select(FcmToken)).scalars().all()]
    assert left == ["t2"]


async def test_admin_test_push_reports_both_transports(client, register, monkeypatch):
    """An operator diagnostic must not claim 'sent: 0' while the app is reachable."""
    import app.fcm as fcm_mod
    from app.main import db as module_db
    from app.models import User
    from sqlalchemy import select

    await register(email="admin@vit.ac.in")
    with module_db.session() as s:
        u = s.execute(select(User).where(User.email == "admin@vit.ac.in")).scalar_one()
        u.is_admin = True
        s.commit()
        admin_id = u.id

    captured = {}
    monkeypatch.setattr(fcm_mod, "enabled", lambda: True)
    monkeypatch.setattr(fcm_mod, "send", lambda db, per_user: captured.update(per_user) or
                        {"sent": 1, "failed": 0, "pruned": 0})

    r = await client.post("/api/admin/test-push",
                          json={"user_id": admin_id, "title": "t", "body": "b"})
    assert r.status_code == 200
    body = r.json()
    assert body["native"]["sent"] == 1
    assert captured and body["user_id"] in captured


async def test_admin_endpoints_reject_non_admins(client, register):
    await register(email="student@vit.ac.in")
    assert (await client.get("/api/admin/stats")).status_code == 403
    assert (await client.post("/api/admin/poll")).status_code == 403



def test_styling_only_appears_in_the_android_block():
    """message.notification takes title/body only.

    Putting icon/color there makes FCM reject the whole message with
    'Invalid JSON payload received. Unknown name "icon" at message.notification',
    and the push silently never ships.
    """
    from app.fcm import build_payload

    payload = build_payload("tok", {"title": "HCL Tech", "body": "2:30 pm - PRP 713",
                                    "tag": "recruit-983", "url": "/dashboard#hits"})
    common = payload["message"]["notification"]
    android = payload["message"]["android"]["notification"]

    assert set(common) == {"title", "body"}, common
    assert android["icon"] == "ic_stat_recruit"
    assert android["color"] == "#F4B33D"
    assert android["channel_id"] == "recruit_updates"
    assert android["notification_priority"] == "PRIORITY_HIGH"
    assert android["tag"] == "recruit-983"
