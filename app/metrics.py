"""Prometheus metrics for Recruit.

Exposes a /metrics endpoint (in main.py) so the existing Grafana/Prometheus on
abhi can scrape the service. Counters are bumped at event time; gauges are
computed on scrape (cheap SQLite count queries). All safe to call any time.
"""
from __future__ import annotations

import logging

from prometheus_client import Counter, Gauge, generate_latest

log = logging.getLogger("recruit.metrics")

# --- counters (bumped at event time) ---
MAILS_INGESTED = Counter("recruit_mails_ingested_total", "CDC mails ingested", ["kind"])
MAILS_DUPLICATE = Counter("recruit_mails_duplicate_total", "CDC mails skipped as duplicates")
HITS_CREATED = Counter("recruit_hits_created_total", "user shortlist hits created")
HITS_MATCHED = Counter("recruit_hits_user_total", "matched users per mail")
PUSH_SENT = Counter("recruit_push_sent_total", "web pushes delivered")
PUSH_FAILED = Counter("recruit_push_failed_total", "web pushes failed")
PUSH_DEAD = Counter("recruit_push_dead_total", "web pushes to dead endpoints (404/410)")
POLLS_RUN = Counter("recruit_polls_total", "IMAP poll cycles")
SUMMARY_OK = Counter("recruit_summary_ok_total", "mails summarized")
SUMMARY_DEFERRED = Counter("recruit_summary_deferred_total", "mails with deferred summary")

# --- gauges (computed on scrape) ---
G_USERS = Gauge("recruit_users", "registered users")
G_SUBS = Gauge("recruit_push_subscriptions", "push subscriptions")
G_INGESTED = Gauge("recruit_ingested", "ingested mails in feed")
G_HITS_UNREAD = Gauge("recruit_hits_unread", "unread hits across all users")
G_LAST_UID = Gauge("recruit_last_uid", "last processed IMAP UID")


def set_db_gauges(db) -> None:
    """Refresh DB-derived gauges. `db` is the app's DB object (has .session())."""
    from sqlalchemy import func, select

    from .models import Hit, Ingested, PushSubscription, User
    try:
        with db.session() as s:
            G_USERS.set(s.execute(select(func.count(User.id))).scalar_one())
            G_SUBS.set(s.execute(select(func.count(PushSubscription.id))).scalar_one())
            G_INGESTED.set(s.execute(select(func.count(Ingested.id))).scalar_one())
            G_HITS_UNREAD.set(s.execute(
                select(func.count(Hit.id)).where(Hit.read_at.is_(None))).scalar_one())
            st = s.get(__import__("app.models", fromlist=["AppState"]).AppState, 1)
            G_LAST_UID.set(st.last_uid if st and st.last_uid else 0)
    except Exception as e:  # never fail a scrape over a gauge hiccup
        log.warning("metrics gauge refresh failed: %s", e)


def render(db) -> bytes:
    """Return the full /metrics text for the current state."""
    set_db_gauges(db)
    return generate_latest()