"""`/api/hits` must hand the client a deadline it can trust.

The app arms its own T-90 alarm. Before this, it could only do that from a push payload,
so a shortlist whose push never arrived had no alarm at all. The server is the only side
that parses the sheet's "(2.30 pm)", so it publishes the parsed instant and the client
never guesses.
"""
import datetime as dt

import pytest

from app.main import db
from app.models import Entry, Hit, Ingested, User


def _seed(email: str, slot: str, subject: str = "HCL Tech Online Test 23-11-2026"):
    """One ingested mail + the student's row + the hit that points at them."""
    with db.session() as s:
        u = s.query(User).filter(User.email == email).one()
        ing = Ingested(msg_uid="13049", folder="INBOX", subject=subject,
                       from_addr="cdc@vit.ac.in", date="21-11-2026",
                       kind="shortlist", outcome="shortlist")
        s.add(ing)
        s.flush()
        # Write the rows the way ingest does now: keyed hashes, no plaintext.
        from app.ids import hash_id
        code = hash_id("K3I6O4I8")
        s.add(Entry(ingested_id=ing.id, code_hash=code, normalized_id="", original="",
                    slot=slot))
        s.add(Hit(user_id=u.id, ingested_id=ing.id, normalized_id=code))
        s.commit()
        return ing.id


@pytest.mark.asyncio
async def test_a_hit_carries_its_deadline_as_an_instant(client, register):
    await register("when@vit.ac.in", "pw12345")
    _seed("when@vit.ac.in",
          "ApplicationNo.: HCLTFP2461546 · Reporting venue: PRP 713 · "
          "Date & Time: 23-11-2026 (2.30 pm)")

    r = await client.get("/api/hits")
    assert r.status_code == 200, r.text
    hit = r.json()["hits"][0]
    when = hit["when_iso"]
    assert when, "the client has nothing to arm an alarm with"
    parsed = dt.datetime.fromisoformat(when)
    # 2.30 pm IST on 23-11-2026
    assert (parsed.year, parsed.month, parsed.day) == (2026, 11, 23)
    assert parsed.hour in (14, 9)  # 14:30 local, or 09:00Z if it says UTC


@pytest.mark.asyncio
async def test_a_row_without_a_readable_time_sends_an_empty_deadline(client, register):
    """Better an empty string than an invented alarm time."""
    await register("notime@vit.ac.in", "pw12345")
    _seed("notime@vit.ac.in", "ApplicationNo.: ABC123 · Reporting venue: PRP 713")

    r = await client.get("/api/hits")
    assert r.json()["hits"][0]["when_iso"] == ""


@pytest.mark.asyncio
async def test_the_deadline_matches_what_the_calendar_file_says(client, register):
    """One parse, two consumers (the .ics and the app) — they must not disagree."""
    await register("agree@vit.ac.in", "pw12345")
    _seed("agree@vit.ac.in",
          "Reporting venue: PRP 713 · Date & Time: 23-11-2026 (2.30 pm)")

    hit = (await client.get("/api/hits")).json()["hits"][0]
    ics = await client.get(f"/api/hits/{hit['id']}/ics")
    assert ics.status_code == 200
    assert "DTSTART:20261123T090000Z" in ics.text
    assert dt.datetime.fromisoformat(hit["when_iso"]).astimezone(
        dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") == "20261123T090000Z"
