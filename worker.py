"""Recruit poll worker — runs the IMAP inbox poller on an interval.

Deployed as a separate container (or `python worker.py` for manual run) so the
FastAPI web process stays responsive. Uses the same settings/.env as the app."""
from __future__ import annotations

import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import settings  # noqa: E402
from app.db import DB  # noqa: E402
from app.ingest import poll_once  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("recruit.worker")


def main() -> None:
    if not (settings.cdc_mailbox_user and settings.cdc_mailbox_token):
        log.error("IMAP creds not configured (CDC_MAILBOX_USER/TOKEN) — bailing")
        sys.exit(1)
    db = DB()
    db.create_all()
    interval = max(settings.poll_interval_min, 1) * 60
    log.info("recruit worker started; poll interval %ds", interval)
    while True:
        try:
            result = poll_once(db)
            log.info("poll: %s", result)
        except Exception as e:
            log.exception("poll failed: %s", e)
        time.sleep(interval)


if __name__ == "__main__":
    main()