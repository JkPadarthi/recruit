"""A new ID must see the shortlists that already contained it.

Live measurement that motivated this: 75 shortlist mails across 5 users never
produced a hit because the matcher only runs at ingest time — one user was on 37
mails and saw 0, because they added their NEO ID afterwards.
"""
CDC_FROM = "vitianscdc2027@vitstudent.ac.in"
HDR = ["S No.", "ApplicationNo.", "Neo ID", "Skill Stack", "Reporting venue", "Date & Time"]


def _mail(rows, subject="HCL Tech Online Test Is Scheduled on 23-11-2026"):
    import io
    from email.message import EmailMessage
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(HDR)
    for i, r in enumerate(rows, start=1):
        ws.append([i, *r])
    buf = io.BytesIO()
    wb.save(buf)
    m = EmailMessage()
    m["From"] = CDC_FROM
    m["Subject"] = subject
    m["Date"] = "Fri, 20 Nov 2026 17:57:34 +0530"
    m.set_content("Shortlist attached.")
    m.add_attachment(buf.getvalue(), maintype="application",
                     subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     filename="list.xlsx")
    return m.as_bytes()


ROWS = [("HCLTFP2461546", "K3I6O4I8", "Java (CSE/IT/EEE/ECE)", "PRP 713", "23-11-2026 (2.30 pm)")]


async def _ingest(raw, uid):
    from app.main import db as module_db
    from app.ingest import process_message
    with module_db.session() as s:
        return process_message(raw, uid, s)


async def test_adding_an_id_backfills_past_shortlists(client, register):
    # the mail arrives BEFORE anyone tracks this code -> no hit at ingest time
    await _ingest(_mail(ROWS), "9600")
    from app.main import db as module_db
    from app.models import Hit
    from sqlalchemy import select
    with module_db.session() as s:
        assert s.execute(select(Hit)).scalars().all() == []

    await register()
    r = await client.post("/api/me/ids", json={"register_id": "K3I6O4I8"})
    assert r.status_code == 200
    assert r.json()["backfilled"] == 1, "the historical shortlist must become a hit now"

    hits = (await client.get("/api/hits")).json()["hits"]
    assert len(hits) == 1
    assert hits[0]["normalized_id"] == "K3I6O4I8"
    assert "PRP 713" in hits[0]["slot"]


async def test_backfill_is_idempotent(client, register):
    await _ingest(_mail(ROWS), "9601")
    await register()
    await client.post("/api/me/ids", json={"register_id": "K3I6O4I8"})
    again = await client.post("/api/me/ids", json={"register_id": "K3I6O4I8"})
    assert again.json()["added"] is False
    hits = (await client.get("/api/hits")).json()["hits"]
    assert len(hits) == 1, "re-adding must not duplicate the hit"


async def test_backfill_only_touches_mails_that_contain_the_code(client, register):
    """A mail with a DIFFERENT code must not produce a hit for this user."""
    other = [("HCLTFP9999999", "Z9Z9Z9Z9", "Python", "PRP 718", "24-11-2026 (2.15 pm)")]
    await _ingest(_mail(other, subject="Some other shortlist"), "9602")
    await register()
    r = await client.post("/api/me/ids", json={"register_id": "K3I6O4I8"})
    assert r.json()["backfilled"] == 0
    assert (await client.get("/api/hits")).json()["hits"] == []


async def test_register_number_also_backfills_body_lists(client, register):
    """Body-only shortlists (no spreadsheet) must backfill too."""
    raw = (b"From: " + CDC_FROM.encode() + b"\r\nSubject: Selection List 2027\r\n\r\n"
           b"Honeywell list: 23BAI0021 and 23BCE0654 are selected.\r\n")
    await _ingest(raw, "9603")
    await register()
    r = await client.post("/api/me/ids", json={"register_id": "23BAI0021"})
    assert r.json()["backfilled"] == 1
    assert len((await client.get("/api/hits")).json()["hits"]) == 1
