"""IMAP ingestion poller.

Reads the central CDC broadcast mailbox, ingests new placement mail, extracts
shortlist IDs deterministically, persists `ingested` + `entries`, matches
registered users to hits, and (when SUMMARIZE_ENABLED) attaches an LLM summary
fail-open. IMAP I/O lives in thin helpers so `process_message` is testable
offline with canned mail bytes."""
from __future__ import annotations

import datetime as dt
import email as email_mod
import imaplib
import json
import logging
import os
import re
import tempfile
from email.header import decode_header, make_header
from email.utils import parseaddr

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .extract import (
    SPREADSHEET_EXTS,
    classify,
    detect_outcome,
    extract_ids,
    extract_ids_from_spreadsheet,
    extract_urls,
    parse_eligible_branches,
)
from .matcher import match_shortlist
from .models import AppState, Entry, Ingested

log = logging.getLogger("recruit.ingest")

# The ONLY sender we ingest (CDC broadcast). Exact From-address match.
CDC_SENDERS = ["vitianscdc2027@vitstudent.ac.in"]

_HEADER_CUT = 320


def sender_allowed(addr: str) -> bool:
    return addr.strip().lower() in CDC_SENDERS


def _dec(v) -> str:
    if not v:
        return ""
    try:
        return str(make_header(decode_header(v)))
    except Exception:
        return v


def _body_text(msg) -> str:
    out: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct not in ("text/plain", "text/html"):
                continue
            disp = part.get_content_disposition() or ""
            if disp.lower().startswith("attachment"):
                continue
            try:
                payload = part.get_payload(decode=True) or b""
                t = payload.decode(part.get_content_charset() or "utf-8", "replace")
            except Exception:
                continue
            if ct == "text/html":
                t = re.sub(r"<[^>]+>", " ", t)
            out.append(t)
    else:
        try:
            payload = msg.get_payload(decode=True) or b""
            out.append(payload.decode(msg.get_content_charset() or "utf-8", "replace"))
        except Exception:
            pass
    return "\n".join(out)


def _spreadsheet_ids_from_msg(msg) -> tuple[set[str], bool]:
    """(ids from spreadsheet attachments, whether any attachment existed)."""
    ids: set[str] = set()
    has_attach = False
    if not msg.is_multipart():
        return ids, has_attach
    for part in msg.walk():
        disp = part.get_content_disposition() or ""
        if not disp.lower().startswith("attachment"):
            continue
        fn = part.get_filename()
        if not fn or not fn.lower().endswith(SPREADSHEET_EXTS):
            continue
        has_attach = True
        raw = part.get_payload(decode=True)
        if not raw:
            continue
        try:
            ext = os.path.splitext(fn)[1] or ".bin"
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as fh:
                fh.write(raw)
                tmp = fh.name
            try:
                ids |= extract_ids_from_spreadsheet(tmp)
            finally:
                os.unlink(tmp)
        except Exception as e:
            log.warning("attachment parse failed %s: %s", fn, e)
    return ids, has_attach


def _maybe_summarize(ingest: Ingested, subject: str, body: str) -> None:
    """Attach LLM summary fail-open. Runs only when SUMMARIZE_ENABLED."""
    if not settings.summarize_enabled:
        return
    try:
        from .summarize import summarize
        parsed = summarize(subject, body)
        ingest.summary = __import__("json").dumps(parsed, ensure_ascii=False)
        ingest.summary_status = "ok"
        from .metrics import SUMMARY_OK
        SUMMARY_OK.inc()
        log.info("uid %s summarized", ingest.msg_uid)
    except Exception as e:
        # FAIL-OPEN: keep the mail, mark deferred; never drop the alert
        ingest.summary_status = "deferred"
        from .metrics import SUMMARY_DEFERRED
        SUMMARY_DEFERRED.inc()
        log.warning("uid %s summary deferred: %s", ingest.msg_uid, e)


def process_message(raw: bytes, msg_uid: str, db: Session, folder: str = "INBOX") -> str:
    """Persist one mail. Returns classification: ignored/announcement/shortlist/duplicate."""
    msg = email_mod.message_from_bytes(raw)
    addr = parseaddr(msg.get("From") or "")[1].lower()
    if not sender_allowed(addr):
        log.info("uid %s skip (not CDC sender): %s", msg_uid, addr)
        return "ignored"

    if db.execute(select(Ingested).where(Ingested.msg_uid == str(msg_uid))).scalar_one_or_none():
        log.info("uid %s duplicate", msg_uid)
        from .metrics import MAILS_DUPLICATE
        MAILS_DUPLICATE.inc()
        return "duplicate"

    subject = _dec(msg.get("Subject", ""))[:_HEADER_CUT]
    date = _dec(msg.get("Date", ""))[:80]
    body = _body_text(msg)
    sheet_ids, has_attach = _spreadsheet_ids_from_msg(msg)
    extracted = sheet_ids | extract_ids(body)
    kind = classify(subject, body, extracted, has_attach)
    # FINAL selection vs mere shortlist — persisted so the push (and any
    # later reprocessing) can celebrate a win without re-reading the body.
    outcome = detect_outcome(subject, body, extracted, has_attach) if kind == "shortlist" else ""

    from .summarize import content_hash
    chash = content_hash(subject, body)

    ingest = Ingested(msg_uid=str(msg_uid), folder=folder, subject=subject,
                      from_addr=addr, date=date, kind=kind, outcome=outcome,
                      eligible_branches=parse_eligible_branches(body)[:_HEADER_CUT],
                      links=json.dumps(extract_urls(body), ensure_ascii=False),
                      content_hash=chash)
    db.add(ingest)
    db.flush()

    if settings.summarize_enabled:
        _maybe_summarize(ingest, subject, body)

    for ident in sorted(extracted):
        db.add(Entry(ingested_id=ingest.id, normalized_id=ident, original=ident))
    db.commit()
    log.info("uid %s ingested kind=%s ids=%d", msg_uid, kind, len(extracted))

    matched_user_ids: set[int] = set()
    if kind == "shortlist" and extracted:
        created_hits = match_shortlist(db, ingest.id, extracted)
        if created_hits:
            matched_user_ids = {h.user_id for h in created_hits}
    # POLICY: notify a user when their ID is in the mail, OR the mail has a
    # registration/test link that's relevant to them. has_ids gates the
    # test-link rule (test link + IDs present -> only matched users).
    from .metrics import MAILS_INGESTED
    MAILS_INGESTED.labels(kind).inc()
    from .push import notify_targeted
    notify_targeted(db, ingest, matched_user_ids, has_ids=bool(extracted))
    return kind


# ---------------------------------------------------------------------------
# IMAP thin I/O (the only real-network surface; stubbed in tests)
# ---------------------------------------------------------------------------
def connect():
    if not settings.cdc_mailbox_user or not settings.cdc_mailbox_token:
        raise RuntimeError("IMAP creds not configured (CDC_MAILBOX_USER/TOKEN)")
    M = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port, timeout=30)
    M.login(settings.cdc_mailbox_user, settings.cdc_mailbox_token.replace(" ", ""))
    M.select("INBOX")
    return M


def status_values(M, folder: str = "INBOX") -> dict:
    typ, data = M.status(folder, "(UIDVALIDITY UIDNEXT)")
    text = data[0].decode() if data and data[0] else ""
    return {k: int(v) for k, v in re.findall(r"(UIDVALIDITY|UIDNEXT)\s+(\d+)", text)}


def highest_uid(M) -> int:
    typ, data = M.uid("search", None, "ALL")
    if data and data[0]:
        return int(data[0].split()[-1])
    return 0


def new_uids(M, last_uid: int | None) -> list[int]:
    if last_uid is None:
        return []
    typ, data = M.uid("search", None, f"UID {last_uid + 1}:*")
    if data and data[0]:
        return sorted(u for u in (int(x) for x in data[0].split()) if u > last_uid)
    return []


def fetch_raw(M, uid) -> bytes | None:
    typ, data = M.uid("fetch", str(uid), "(BODY.PEEK[])")
    for part in data:
        if not isinstance(part, tuple):
            continue
        inner = part[1]
        if isinstance(inner, bytes):
            return inner
        if isinstance(inner, list):
            return b"".join(c for c in inner if isinstance(c, bytes))
    return None


def poll_once(db) -> dict:
    """One ingestion round. Returns a status dict (also /api/status)."""
    with db.session() as s:
        st = s.get(AppState, 1)
        if st is None:
            st = AppState(id=1)
            s.add(st)
        M = connect()
        try:
            vals = status_values(M)
            if st.uidvalidity and vals.get("UIDVALIDITY") != st.uidvalidity:
                log.info("UIDVALIDITY changed; resetting baseline")
                st.last_uid = None
            if st.last_uid is None:
                st.last_uid = highest_uid(M)
                st.uidvalidity = vals.get("UIDVALIDITY")
                st.last_poll_at = dt.datetime.now(dt.timezone.utc)
                s.commit()
                log.info("BASELINE set at UID %s (UIDVALIDITY %s)", st.last_uid, st.uidvalidity)
                return {"baselined": True, "last_uid": st.last_uid}

            uids = new_uids(M, st.last_uid)
            processed = [0, 0]  # [shortlist, announcement]
            from .metrics import POLLS_RUN
            POLLS_RUN.inc()
            for uid in uids:
                raw = fetch_raw(M, uid)
                if not raw:
                    continue
                kind = process_message(raw, str(uid), s)
                if kind == "shortlist":
                    processed[0] += 1
                elif kind == "announcement":
                    processed[1] += 1
                st.last_uid = int(uid)
            st.last_poll_at = dt.datetime.now(dt.timezone.utc)
            s.commit()
            log.info("poll: %d new uids, shortlists=%d announcements=%d, cursor=%s",
                     len(uids), processed[0], processed[1], st.last_uid)
            return {"processed": len(uids), "shortlists": processed[0],
                    "announcements": processed[1], "last_uid": st.last_uid,
                    "last_poll_at": st.last_poll_at.isoformat() if st.last_poll_at else None}
        finally:
            try:
                M.logout()
            except Exception:
                pass