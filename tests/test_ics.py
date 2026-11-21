"""The .ics reminder — the only one an iPhone can keep for free.

Asserts the two things that would make it silently useless: a timezone that shifts
the event by 5:30, and an alarm that is not actually 90 minutes before reporting.
"""
import pytest
from sqlalchemy import select

from app.ics import build_ics
from app.main import db as module_db
from app.models import Entry, Hit, Ingested, User


def test_ten_thirty_ist_becomes_nine_utc():
    body = build_ics(uid="recruit-1", title="HCL Tech Online Test",
                     when_iso="2026-11-23T14:30:00+05:30", location="PRP 713")
    assert "DTSTART:20261123T090000Z" in body
    assert "DTEND:20261123T100000Z" in body          # one hour slot
    assert "TRIGGER:-PT90M" in body                  # T-90, same as the push
    assert "LOCATION:PRP 713" in body


def test_crlf_and_no_bare_newlines():
    """Some calendar clients silently reject an LF-only calendar."""
    body = build_ics(uid="u", title="t", when_iso="2026-11-23T14:30:00+05:30")
    assert body.endswith("\r\n")
    assert "\r\n" in body
    assert "\n" not in body.replace("\r\n", "")


def test_commas_and_semicolons_are_escaped():
    body = build_ics(uid="u", title="HCL, Tech; Ltd", when_iso="2026-11-23T14:30:00+05:30")
    assert "SUMMARY:HCL\\, Tech\\; Ltd" in body


def test_long_description_is_folded():
    body = build_ics(uid="u", title="t", when_iso="2026-11-23T14:30:00+05:30",
                     description="x" * 300)
    assert all(len(line) <= 75 for line in body.split("\r\n"))


def _seed_hit(slot: str) -> int:
    with module_db.session() as s:
        u = s.execute(select(User)).scalars().first()
        ing = Ingested(msg_uid="13049", subject="HCL Schedule 23rd November 2026",
                       kind="shortlist")
        s.add(ing)
        s.commit()
        s.add(Entry(ingested_id=ing.id, normalized_id="K3I6O4I8", slot=slot))
        h = Hit(user_id=u.id, ingested_id=ing.id, normalized_id="K3I6O4I8")
        s.add(h)
        s.commit()
        return h.id


@pytest.mark.asyncio
async def test_owner_gets_a_calendar(client, register):
    await register()
    hit_id = _seed_hit("Date & Time: 23-11-2026 (2.30 pm) · Reporting venue: PRP 713")

    r = await client.get(f"/api/hits/{hit_id}/ics")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/calendar")
    assert "attachment" in r.headers["content-disposition"]
    assert "DTSTART:20261123T090000Z" in r.text
    assert "TRIGGER:-PT90M" in r.text
    assert "LOCATION:PRP 713" in r.text


@pytest.mark.asyncio
async def test_another_users_hit_is_a_404_not_a_403(client, register):
    """404 on purpose: a 403 would confirm the hit exists."""
    await register(email="owner@vit.ac.in")
    hit_id = _seed_hit("Date & Time: 23-11-2026 (2.30 pm) · Reporting venue: PRP 713")

    await register(email="nosy@vit.ac.in")
    r = await client.get(f"/api/hits/{hit_id}/ics")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_row_without_a_time_refuses_rather_than_guessing(client, register):
    await register()
    hit_id = _seed_hit("Reporting venue: PRP 713")   # no date, no time

    r = await client.get(f"/api/hits/{hit_id}/ics")
    assert r.status_code == 409
    assert "no readable date" in r.text
