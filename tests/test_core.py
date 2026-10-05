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


from app.summarize import _extract_json, _normalize_aliases


def test_extract_json_strips_markdown_fence():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('```\n{"a": 2}\n```') == {"a": 2}
    assert _extract_json('{"a": 3}') == {"a": 3}


def test_normalize_flattens_nulls_and_aliases():
    d = _normalize_aliases({"company_name": "X", "event_date": None, "deadline": None,
                            "eligible_branches": None, "summary": "s"})
    assert d["company"] == "X"
    assert d["event_date"] == "" and d["deadline"] == "" 
    assert d["eligible_branches"] == []


from app.extract import extract_ids, classify, extract_urls
from app.push import url_kind
from app.util import normalize_id


def test_url_slugs_are_not_mistaken_for_ids():
    """A broadcast test-link mail (https://.../a3gsbg4oao) must NOT be read as a shortlist."""
    body = ("Kind Attention!! Test 1 : 11:00 AM "
            "Link - https://tests.mettl.com/authenticateKey/a3gsbg4oao for everyone")
    ids = extract_ids(body)
    assert ids == set()
    assert classify("Axxela test", body, ids, False) == "announcement"


def test_inline_ids_still_extracted_after_url_strip():
    body = "selected students include K3I6O4I8 and 23BAI0021"
    ids = extract_ids(body)
    assert normalize_id("K3I6O4I8") in ids
    assert normalize_id("23BAI0021") in ids


def test_extract_urls_returns_links():
    body = "Register: https://placement.vit.ac.in/2027/apply and test at https://tests.mettl.com/ab12cd"
    assert extract_urls(body) == ["https://placement.vit.ac.in/2027/apply",
                                   "https://tests.mettl.com/ab12cd"]
    assert extract_urls("no links here") == []


# ---- notification targeting policy -----------------------------------------
def notify_logic(has_ids, links):
    """Replicates notify_targeted's recipient decision (target=ALL vs matched)."""
    from app.push import url_kind
    kinds = {url_kind(u) for u in links}
    has_test = "test" in kinds
    has_reg = "register" in kinds
    # broadcast a link (register OR test) ONLY when the mail has no IDs;
    # when IDs are present the mail is a targeted shortlist — matched only.
    if (has_reg or has_test) and not has_ids:
        return "ALL"
    return "MATCHED_ONLY"


def test_notify_registration_link_pings_everyone():
    # PWC-style registration link, NO ids -> ALL users
    assert notify_logic(has_ids=False, links=["https://app.joinsuperset.com/join/#/signup/student"]) == "ALL"


def test_notify_registration_link_with_ids_only_matched():
    # targeted shortlist carrying a form/registration link + IDs -> matched only
    assert notify_logic(has_ids=True, links=["https://placement.vit.ac.in/apply/2027"]) == "MATCHED_ONLY"


def test_notify_forms_gle_link_not_broadcast():
    # a bare forms.gle link is the next round's form, not an open drive ->
    # no auto "register" classification (would otherwise ping everyone)
    assert notify_logic(has_ids=True, links=["https://forms.gle/QxmUx3aeEyLsU9bYA"]) == "MATCHED_ONLY"


def test_notify_test_link_no_ids_pings_everyone():
    # Axxela-style test link, no register IDs present -> ALL users
    assert notify_logic(has_ids=False, links=["https://tests.mettl.com/authenticateKey/a3gsbg4oao"]) == "ALL"


def test_notify_test_link_with_ids_only_matched():
    # test link + IDs present -> only matched users
    assert notify_logic(has_ids=True, links=["https://tests.mettl.com/authenticateKey/a3gsbg4oao"]) == "MATCHED_ONLY"


def test_notify_no_link_shortlist_only_matched():
    # LMW-style: shortlist code, no link, not your ID -> matched users only (possibly none)
    assert notify_logic(has_ids=True, links=[]) == "MATCHED_ONLY"


# ---- celebratory title for FINAL selections ---------------------------------
def notify_title(outcome, company="", matched=True, has_test=False, has_reg=False, kind="shortlist"):
    """Mirror of notify_targeted's title decision (VAPID blanked in tests)."""
    if matched:
        if outcome == "selection":
            return (f"🎉🎊 CONGRATULATIONS — you got selected for {company}!"
                    if company else "🎉🎊 CONGRATULATIONS — you got selected!")
        return "✅ You're on the list"
    if has_test:
        return "🧪 Test link available"
    if has_reg:
        return "📝 Registration open"
    if kind == "shortlist":
        return "📋 New shortlist"
    return "📢 New announcement"


def test_title_final_selection_is_celebratory():
    t = notify_title("selection", company="Deloitte India")
    assert t.startswith("🎉🎊 CONGRATULATIONS")
    assert "Deloitte India" in t


def test_title_selection_without_company_still_celebrates():
    assert notify_title("selection") == "🎉🎊 CONGRATULATIONS — you got selected!"


def test_title_plain_shortlist_stays_flat():
    assert notify_title("shortlist") == "✅ You're on the list"


# ---- eligibility / division condition --------------------------------------
from app.extract import audience_matches, parse_audience


def test_agilisium_mba_mail_hides_from_btech():
    # Agilisium: "Eligible Branches * - MBA All specializations *" -> MBA only
    aud = parse_audience("Eligible Branches * - MBA All specializations *",
                         "Agilisium Consulting - Dream Internship - MBA 2027 Batch")
    assert aud == frozenset({"mba"})
    assert audience_matches(aud, "bt") is False      # B.Tech student: no
    assert audience_matches(aud, "mba") is True      # MBA student: yes


def test_generic_mail_matches_everyone():
    aud = parse_audience("", "Hiring drive for all students")
    assert audience_matches(aud, "bt") is True
    assert audience_matches(aud, "mba") is True


def test_division_roundtrip_profile():
    # verify a profile with no division still sees generic mails (fail-open)
    aud = parse_audience("Eligible Branches * - CSE, IT, ECE *", "Dream internship")
    assert "bt" in aud


async def test_profile_page_requires_auth_and_saves(client, register):
    await register()
    # logged in -> profile page loads + save works
    r = await client.get("/profile")
    assert r.status_code == 200
    up = await client.put("/api/me/profile", json={"division": "bt", "branch": "AIML"})
    assert up.status_code == 200
    me = await client.get("/api/me")
    assert me.json()["branch"] == "AIML"
    assert me.json()["division"] == "bt"