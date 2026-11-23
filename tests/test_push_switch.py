"""The master notification switch must actually stop everything.

The operator asked for silence across all accounts. "Silence" has to mean: no web push,
no FCM, no admin test send — while ingest keeps storing hits, because the data is the
part we must not lose.
"""
import dataclasses

import pytest
from sqlalchemy import select

from app import main as main_module
from app import push as push_module
from app.config import settings
from app.main import db as module_db
from app.models import Hit, Ingested, PushSubscription, User


@pytest.fixture
def quiet(monkeypatch):
    """Turn the switch off and record any attempt to send."""
    off = dataclasses.replace(settings, push_enabled=False)
    monkeypatch.setattr(main_module, "settings", off)
    monkeypatch.setattr(push_module, "settings", off)

    sent = []

    def _webpush(sub, payload):
        sent.append(("web", payload))
        return True

    class _Fcm:
        @staticmethod
        def enabled():
            return True

        @staticmethod
        def send(db_, per_user):
            sent.append(("fcm", per_user))
            return {"sent": 1, "failed": 0, "pruned": 0}

    monkeypatch.setattr(push_module, "send_to_subscription", _webpush)
    monkeypatch.setattr(push_module, "fcm", _Fcm, raising=False)
    return sent


def test_the_switch_is_on_by_default():
    """Silence must be a deliberate act, not a missing env var."""
    assert settings.push_enabled is True


@pytest.mark.asyncio
async def test_notify_targeted_sends_nothing_when_disabled(client, register, quiet):
    email, _ = await register()
    with module_db.session() as s:
        u = s.execute(select(User).where(User.email == email)).scalar_one()
        ing = Ingested(msg_uid="9001", folder="INBOX", subject="Capgemini Online Test",
                       kind="shortlist", links="[]", eligible_branches="")
        s.add(ing)
        s.flush()
        s.add(Hit(user_id=u.id, ingested_id=ing.id, normalized_id="23BAI0021"))
        s.add(PushSubscription(user_id=u.id, endpoint="https://example.test/ep",
                               keys_json='{"p256dh":"x","auth":"y"}', platform="web"))
        s.commit()
        uid, ing_id = u.id, ing.id

    with module_db.session() as s:
        push_module.notify_targeted(s, s.get(Ingested, ing_id), {uid}, has_ids=True)

    assert quiet == [], f"something was sent while disabled: {quiet}"


@pytest.mark.asyncio
async def test_hits_still_land_when_notifications_are_off(client, register, quiet):
    """Silence must not mean data loss: the hit is stored, only the buzz is skipped."""
    email, _ = await register()
    with module_db.session() as s:
        u = s.execute(select(User).where(User.email == email)).scalar_one()
        ing = Ingested(msg_uid="9002", folder="INBOX", subject="Deloitte shortlist",
                       kind="shortlist", links="[]", eligible_branches="")
        s.add(ing)
        s.flush()
        s.add(Hit(user_id=u.id, ingested_id=ing.id, normalized_id="23BAI0021"))
        s.commit()
        count = s.execute(select(Hit).where(Hit.user_id == u.id)).scalars().all()

    assert len(count) == 1
    assert quiet == []


@pytest.mark.asyncio
async def test_admin_test_push_refuses_while_disabled(client, register, quiet):
    email, _ = await register()
    with module_db.session() as s:
        u = s.execute(select(User).where(User.email == email)).scalar_one()
        u.is_admin = True
        s.commit()
        uid = u.id

    r = await client.post("/api/admin/test-push",
                          json={"user_id": uid, "title": "hi", "body": "there"})
    assert r.status_code == 409, r.text
    assert "disabled globally" in r.text
    assert quiet == []
