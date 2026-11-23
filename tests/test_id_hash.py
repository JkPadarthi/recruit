"""No tracked ID may be recoverable from the database or the API.

The operator's requirement was blunt: nobody should be able to see a NEO ID. That means
the codes must not exist as text anywhere — not in `user_ids`, not in `entries` (a CDC
shortlist attachment lists every selected student), not in `hits`, and not in a response.
"""
import base64
import hashlib
import hmac

import pytest
from sqlalchemy import select

from app import ids as ids_module
from app.ids import hash_id, hashing_enabled
from app.main import db as module_db
from app.models import Entry, Hit, Ingested, User, UserId

CODE = "K3I6O4I8"


def _expected(code: str) -> str:
    key = base64.b64decode("dGVzdC1rZXktZm9yLXVuaXQtdGVzdHMtb25seS0zMmI=")
    return hmac.new(key, code.encode(), hashlib.sha256).hexdigest()


def test_hashing_is_active_in_the_suite():
    assert hashing_enabled() is True
    assert hash_id(CODE) == _expected(CODE)
    assert hash_id(CODE) != hash_id("K3I6O4I9")


@pytest.mark.asyncio
async def test_adding_an_id_stores_no_text(client, register):
    await register()
    r = await client.post("/api/me/ids", json={"register_id": CODE})
    assert r.status_code == 200, r.text
    assert "normalized_id" not in r.json(), "the API echoed the code back"

    with module_db.session() as s:
        row = s.execute(select(UserId)).scalar_one()
        assert row.code_hash == _expected(CODE)
        assert row.register_id == "" and row.normalized_id == ""


@pytest.mark.asyncio
async def test_profile_exposes_only_a_position(client, register):
    await register()
    await client.post("/api/me/ids", json={"register_id": CODE})
    me = (await client.get("/api/me")).json()
    assert me["ids"] == [{"id": me["ids"][0]["id"], "label": "ID 1"}]
    blob = str(me)
    assert CODE not in blob and CODE.lower() not in blob


@pytest.mark.asyncio
async def test_matching_works_without_any_plaintext(client, register):
    await register()
    await client.post("/api/me/ids", json={"register_id": CODE})
    with module_db.session() as s:
        ing = Ingested(msg_uid="7001", folder="INBOX", subject="Capgemini shortlist",
                       kind="shortlist", links="[]", eligible_branches="")
        s.add(ing)
        s.flush()
        # entries as the ingest path writes them: hash only
        s.add(Entry(ingested_id=ing.id, code_hash=_expected(CODE), normalized_id="",
                    original="", slot="Venue: PRP 713"))
        s.commit()
        ing_id = ing.id

    from app.matcher import match_shortlist
    with module_db.session() as s:
        hits = match_shortlist(s, ing_id, [CODE])
        assert len(hits) == 1
        assert hits[0].normalized_id == _expected(CODE)
        assert hits[0].normalized_id != CODE


@pytest.mark.asyncio
async def test_delete_is_by_row_id_and_leaves_no_trace(client, register):
    await register()
    await client.post("/api/me/ids", json={"register_id": CODE})
    me = (await client.get("/api/me")).json()
    row_id = me["ids"][0]["id"]
    r = await client.delete(f"/api/me/ids/{row_id}")
    assert r.status_code == 200, r.text
    with module_db.session() as s:
        assert s.execute(select(UserId)).first() is None


@pytest.mark.asyncio
async def test_the_old_code_based_delete_no_longer_works(client, register):
    await register()
    await client.post("/api/me/ids", json={"register_id": CODE})
    r = await client.delete(f"/api/me/ids/{CODE}")
    assert r.status_code in (404, 422)
