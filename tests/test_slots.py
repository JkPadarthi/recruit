"""The slot fix: a shortlist code must carry the row it sat on.

Regression guard for the HCL case — a mail whose subject said "23 & 24 Nov,
2.15 PM" while the student's own row said "23-11-2026 (2.30 pm) · PRP 713".
Before this, extract_ids_from_xlsx() flattened every cell to a set of codes and
the row was lost, so the feed and the push could only ever show the subject.
"""
import io

CDC_FROM = "vitianscdc2027@vitstudent.ac.in"
HDR = ["S No.", "ApplicationNo.", "Neo ID", "Skill Stack", "Reporting venue", "Date & Time"]


def _xlsx(rows, path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(HDR)
    for i, r in enumerate(rows, start=1):
        ws.append([i, *r])
    wb.save(path)
    return path


def _mail_with_xlsx(rows, subject="HCL Tech Online Test Is Scheduled on 23-11-2026 & 24-11-2026"):
    """A real multipart CDC mail carrying a shortlist spreadsheet."""
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
    m.set_content("Please find the attached shortlisted students list with the test "
                  "date, reporting venue & timings.")
    m.add_attachment(
        buf.getvalue(), maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="HCL Schedule 23rd & 24th November 2026.xlsx",
    )
    return m.as_bytes()


ROWS = [
    ("HCLTFP2460909", "A2Z7K4F5", "Java (CSE/IT/EEE/ECE)", "PRP 717", "23-11-2026 (2.15 pm)"),
    ("HCLTFP2461546", "K3I6O4I8", "Java (CSE/IT/EEE/ECE)", "PRP 713", "23-11-2026 (2.30 pm)"),
    ("HCLTFP2464527", "P4E7P1E0", "Python (CSE/IT/EEE/ECE)", "PRP 718", "24-11-2026 (2.15 pm)"),
]


# ---- extraction layer ------------------------------------------------------
def test_row_context_is_captured_per_code(tmp_path):
    from app.extract import extract_from_spreadsheet
    p = _xlsx(ROWS, tmp_path / "s.xlsx")
    ids, slots = extract_from_spreadsheet(p)
    assert ids == {"A2Z7K4F5", "K3I6O4I8", "P4E7P1E0"}
    # the whole point: the code knows where and when it must report
    assert slots["K3I6O4I8"] == (
        "ApplicationNo.: HCLTFP2461546 · Skill Stack: Java (CSE/IT/EEE/ECE) · "
        "Reporting venue: PRP 713 · Date & Time: 23-11-2026 (2.30 pm)")
    # and neighbouring students are not confused with each other
    assert "PRP 713" in slots["K3I6O4I8"] and "PRP 713" not in slots["A2Z7K4F5"]
    assert "24-11-2026" in slots["P4E7P1E0"]


def test_serial_column_is_not_mistaken_for_information(tmp_path):
    from app.extract import extract_slots_from_spreadsheet
    slots = extract_slots_from_spreadsheet(_xlsx(ROWS, tmp_path / "s2.xlsx"))
    assert "S No.: 2" not in slots["K3I6O4I8"]


def test_two_codes_in_one_cell_share_the_row(tmp_path):
    from openpyxl import Workbook
    from app.extract import extract_from_spreadsheet
    wb = Workbook()
    ws = wb.active
    ws.append(["Neo ID", "Reporting venue", "Date & Time"])
    ws.append(["K3I6O4I8, 23BAI0021", "PRP 713", "23-11-2026 (2.30 pm)"])
    p = tmp_path / "pair.xlsx"
    wb.save(p)
    ids, slots = extract_from_spreadsheet(p)
    assert ids == {"K3I6O4I8", "23BAI0021"}
    assert slots["23BAI0021"] == slots["K3I6O4I8"]
    assert "PRP 713" in slots["23BAI0021"]


def test_headerless_sheet_still_yields_the_values(tmp_path):
    from openpyxl import Workbook
    from app.extract import extract_slots_from_spreadsheet
    wb = Workbook()
    ws = wb.active
    ws.append(["K3I6O4I8", "PRP 713", "23-11-2026 (2.30 pm)"])  # no header row at all
    p = tmp_path / "bare.xlsx"
    wb.save(p)
    slot = extract_slots_from_spreadsheet(p)["K3I6O4I8"]
    assert "PRP 713" in slot and "2.30 pm" in slot


def test_compact_slot_puts_the_date_before_the_venue():
    from app.extract import compact_slot
    full = ("ApplicationNo.: HCLTFP2461546 · Skill Stack: Java (CSE/IT/EEE/ECE) · "
            "Reporting venue: PRP 713 · Date & Time: 23-11-2026 (2.30 pm)")
    assert compact_slot(full) == "23-11-2026 (2.30 pm) · PRP 713"
    assert compact_slot("") == ""


# ---- ingest layer ----------------------------------------------------------
async def test_ingest_persists_the_slot_on_the_entry(client):
    from sqlalchemy import select
    from app.main import db as module_db
    from app.ingest import process_message
    from app.models import Entry
    with module_db.session() as s:
        assert process_message(_mail_with_xlsx(ROWS), "9001", s) == "shortlist"
    with module_db.session() as s:
        e = s.execute(select(Entry).where(Entry.normalized_id == "K3I6O4I8")).scalars().one()
        assert "PRP 713" in e.slot and "23-11-2026 (2.30 pm)" in e.slot
        # body-only codes have no row context and must stay ""
        e2 = s.execute(select(Entry).where(Entry.normalized_id == "A2Z7K4F5")).scalars().one()
        assert "PRP 717" in e2.slot


# ---- API layer -------------------------------------------------------------
async def test_hit_api_returns_the_students_own_slot(client, register):
    await register()
    await client.post("/api/me/ids", json={"register_id": "K3I6O4I8"})
    from app.main import db as module_db
    from app.ingest import process_message
    with module_db.session() as s:
        process_message(_mail_with_xlsx(ROWS), "9002", s)
    hits = (await client.get("/api/hits")).json()["hits"]
    assert hits[0]["normalized_id"] == "K3I6O4I8"
    assert "PRP 713" in hits[0]["slot"] and "2:30 pm" in hits[0]["slot"]


async def test_feed_only_carries_your_own_rows(client, register):
    await register()
    await client.post("/api/me/ids", json={"register_id": "K3I6O4I8"})
    from app.main import db as module_db
    from app.ingest import process_message
    with module_db.session() as s:
        process_message(_mail_with_xlsx(ROWS), "9003", s)
    mails = (await client.get("/api/mails")).json()["mails"]
    mine = mails[0]["my_slots"]
    assert list(mine) == ["K3I6O4I8"]              # 831 rows never ship, only yours
    assert "PRP 713" in mine["K3I6O4I8"]


# ---- push layer ------------------------------------------------------------
async def test_push_body_carries_slot_for_matched_user_only(client, register, monkeypatch):
    await register()
    await client.post("/api/me/ids", json={"register_id": "K3I6O4I8"})
    await client.post("/api/push/subscribe",
                      json={"endpoint": "https://fcm.googleapis.com/fcm/send/SLOT_TEST", "platform": "web"})
    import app.push as push_mod
    sent: list[dict] = []
    monkeypatch.setattr(push_mod, "vapid_enabled", lambda: True)
    monkeypatch.setattr(push_mod, "send_to_subscription", lambda sub, payload: sent.append(payload) or True)
    from app.main import db as module_db
    from app.ingest import process_message
    with module_db.session() as s:
        process_message(_mail_with_xlsx(ROWS), "9004", s)
    assert len(sent) == 1
    body = sent[0]["body"]
    assert "23-11-2026 (2:30 pm) - PRP 713" in body      # THEIR slot, not the subject's
    assert sent[0]["title"] == "✅ You're on the list"
    assert "2.15" not in body                              # the subject's decoy time is gone


async def test_push_body_without_row_context_is_unchanged(client, register, monkeypatch):
    """A body-only shortlist (no attachment) must keep the old subject-only push."""
    await register()
    await client.post("/api/me/ids", json={"register_id": "23BAI0021"})
    await client.post("/api/push/subscribe",
                      json={"endpoint": "https://fcm.googleapis.com/fcm/send/SLOT_TEST2", "platform": "web"})
    import app.push as push_mod
    sent: list[dict] = []
    monkeypatch.setattr(push_mod, "vapid_enabled", lambda: True)
    monkeypatch.setattr(push_mod, "send_to_subscription", lambda sub, payload: sent.append(payload) or True)
    from app.main import db as module_db
    from app.ingest import process_message
    raw = (b"From: " + CDC_FROM.encode() + b"\r\nSubject: Selection List 2027\r\n\r\n"
           b"Honeywell list: 23BAI0021 and 23BCE0654 are selected.\r\n")
    with module_db.session() as s:
        process_message(raw, "9005", s)
    assert len(sent) == 1
    assert "📍" not in sent[0]["body"]


# ---- folded header regression ----------------------------------------------
FOLDED = (b"HCL Tech Online Test Is Scheduled on 23-11-2026 & 24-11-2026 by 2.15\r\n"
          b" PM @ PRP\r\n")


async def test_folded_subject_is_collapsed_and_push_stays_one_line(client, register, monkeypatch):
    """VIT folds long subjects; a raw CRLF inside the push body looked broken."""
    from sqlalchemy import select
    from app.main import db as module_db
    from app.ingest import process_message
    from app.models import Ingested

    await register()
    await client.post("/api/me/ids", json={"register_id": "K3I6O4I8"})
    await client.post("/api/push/subscribe",
                      json={"endpoint": "https://fcm.googleapis.com/fcm/send/FOLD", "platform": "web"})
    import app.push as push_mod
    sent: list[dict] = []
    monkeypatch.setattr(push_mod, "vapid_enabled", lambda: True)
    monkeypatch.setattr(push_mod, "send_to_subscription", lambda sub, payload: sent.append(payload) or True)

    raw = (b"From: " + CDC_FROM.encode() + b"\r\nSubject: " + FOLDED + b"\r\n"
           + b"Shortlist: K3I6O4I8\r\n")
    with module_db.session() as s:
        process_message(raw, "9100", s)

    with module_db.session() as s:
        ing = s.execute(select(Ingested)).scalars().one()
        assert "\r" not in ing.subject and "\n" not in ing.subject
        assert ing.subject.endswith("2.15 PM @ PRP")

    assert len(sent) == 1
    body = sent[0]["body"]
    assert "\r" not in body
    assert body.split("\n")[0].endswith("2.15 PM @ PRP")   # subject is exactly one line


# ---- the notification is ONE derived line, never the subject ---------------
def test_headline_is_exactly_the_actionable_line():
    from app.extract import slot_headline
    full = ("ApplicationNo.: HCLTFP2461546 · Skill Stack: Java (CSE/IT/EEE/ECE) · "
            "Reporting venue: PRP 713 · Date & Time: 23-11-2026 (2.30 pm)")
    subject = ("HCL Tech Online Test Is Scheduled on 23-11-2026 & 24-11-2026 by 2.15 PM @ PRP")
    assert slot_headline(full, "HCL Tech", subject) == (
        "HCL Tech Online Test on 23-11-2026 (2:30 pm) - PRP 713")


def test_headline_handles_split_date_and_time_columns():
    from app.extract import slot_headline
    slot = "Date: 9th November · Time: 4:00pm · Venue: PRP 704"
    assert slot_headline(slot, "Zoho", "Zoho interview schedule") == (
        "Zoho Interview on 9th November, 4:00pm - PRP 704")


def test_headline_without_company_or_kind_still_reads():
    from app.extract import slot_headline
    slot = "Reporting venue: PRP 713 · Date & Time: 23-11-2026 (2.30 pm)"
    assert slot_headline(slot, "", "Kind attention!!") == "23-11-2026 (2:30 pm) - PRP 713"


def test_pretty_time_leaves_dates_alone():
    from app.extract import pretty_time
    assert pretty_time("23-11-2026 (2.30 pm)") == "23-11-2026 (2:30 pm)"
    assert pretty_time("23.11.2026") == "23.11.2026"


async def test_push_body_is_only_the_headline_for_a_matched_user(client, register, monkeypatch):
    """No subject, no slot paragraph, no link flag — one line, exactly."""
    from app.main import db as module_db
    from app.ingest import process_message
    import app.push as push_mod

    await register()
    await client.post("/api/me/ids", json={"register_id": "K3I6O4I8"})
    await client.post("/api/push/subscribe",
                      json={"endpoint": "https://fcm.googleapis.com/fcm/send/ONE_LINE", "platform": "web"})
    sent: list[dict] = []
    monkeypatch.setattr(push_mod, "vapid_enabled", lambda: True)
    monkeypatch.setattr(push_mod, "send_to_subscription", lambda sub, payload: sent.append(payload) or True)

    with module_db.session() as s:
        process_message(_mail_with_xlsx(ROWS, subject=(
            "HCL Tech Online Test Is Scheduled on 23-11-2026 & 24-11-2026 by 2.15 PM @ PRP")),
            "9200", s)

    assert len(sent) == 1
    assert sent[0]["title"] == "✅ You're on the list"
    assert sent[0]["body"] == "HCL Tech Online Test on 23-11-2026 (2:30 pm) - PRP 713"
    assert "Is Scheduled" not in sent[0]["body"]
    assert "📍" not in sent[0]["body"]


async def test_push_payload_carries_a_tag_so_resends_replace(client, register, monkeypatch):
    """Three sends of one mail must collapse to one card, not stack."""
    from app.main import db as module_db
    import app.push as push_mod

    await register()
    await client.post("/api/me/ids", json={"register_id": "K3I6O4I8"})
    await client.post("/api/push/subscribe",
                      json={"endpoint": "https://fcm.googleapis.com/fcm/send/TAG", "platform": "web"})
    sent: list[dict] = []
    monkeypatch.setattr(push_mod, "vapid_enabled", lambda: True)
    monkeypatch.setattr(push_mod, "send_to_subscription", lambda sub, payload: sent.append(payload) or True)

    with module_db.session() as s:
        ing = _seed(s)          # ingest pushes once
        assert len(sent) == 1
        sent.clear()
        for _ in range(3):      # a manual re-send, three times
            push_mod.notify_targeted(s, ing, {1}, has_ids=True)

    assert len(sent) == 3
    assert {p["tag"] for p in sent} == {"recruit-1"}, "same mail -> same tag -> OS replaces"
    assert all(p["url"] == "/dashboard#hits" for p in sent)
    assert all(p["body"] == "HCL Tech Online Test on 23-11-2026 (2:30 pm) - PRP 713" for p in sent)


def _seed(s):
    """Ingest the HCL-style mail once and return its Ingested row."""
    from sqlalchemy import select
    from app.models import Ingested
    from app.ingest import process_message
    process_message(_mail_with_xlsx(ROWS, subject=(
        "HCL Tech Online Test Is Scheduled on 23-11-2026 & 24-11-2026 by 2.15 PM @ PRP")), "9300", s)
    return s.execute(select(Ingested).where(Ingested.msg_uid == "9300")).scalars().one()


async def test_hits_api_exposes_company_and_prefers_the_sheet_row(client, register):
    """Card header = ID + company; body = the sheet row, never summary AND row."""
    from app.main import db as module_db
    from app.ingest import process_message

    await register()
    await client.post("/api/me/ids", json={"register_id": "K3I6O4I8"})
    with module_db.session() as s:
        process_message(_mail_with_xlsx(ROWS, subject=(
            "HCL Tech Online Test Is Scheduled on 23-11-2026 & 24-11-2026 by 2.15 PM @ PRP")),
            "9400", s)

    h = (await client.get("/api/hits")).json()["hits"][0]
    assert h["normalized_id"] == "K3I6O4I8"
    assert h["company"] == "HCL Tech"                       # chip next to the ID
    assert h["slot"].startswith("ApplicationNo.: HCLTFP2461546")   # card body
    # house date style: the sheet writes 2.30 pm, every surface shows 2:30 pm
    assert "PRP 713" in h["slot"] and "23-11-2026 (2:30 pm)" in h["slot"]


async def test_feed_slot_uses_house_date_style_too(client, register):
    """Feed, hits and push must all read 2:30 pm — not the sheet's 2.30 pm."""
    from app.main import db as module_db
    from app.ingest import process_message

    await register()
    await client.post("/api/me/ids", json={"register_id": "K3I6O4I8"})
    with module_db.session() as s:
        process_message(_mail_with_xlsx(ROWS), "9500", s)
    mails = (await client.get("/api/mails")).json()["mails"]
    slot = [m for m in mails if m.get("my_slots")][0]["my_slots"]["K3I6O4I8"]
    assert "23-11-2026 (2:30 pm)" in slot
    assert "2.30 pm" not in slot
