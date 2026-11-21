"""Outbound email — only used for password resets.

Deliberately small: one function, one SMTP connection, no retries, no queue. A reset
mail that has to be retried is a reset mail that already failed, and the admin-issued
link in the dashboard exists for exactly that case.

Configuration is env-only (SMTP_HOST/PORT/USER/PASSWORD/FROM). With no SMTP_HOST the
app stays fully functional and `enabled()` is False — the forgot page then says so
plainly instead of pretending a mail went out.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

from .config import settings

log = logging.getLogger(__name__)


def enabled() -> bool:
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)


def _from_header() -> str:
    raw = settings.smtp_from or settings.smtp_user
    name, addr = parseaddr(raw)
    return formataddr((name or settings.brand_name, addr)) if addr else raw


def send(to: str, subject: str, text: str, html: str = "") -> bool:
    """True only if the server accepted the message. Never raises."""
    if not enabled():
        log.warning("SMTP not configured — cannot send '%s' to %s", subject, to)
        return False

    msg = EmailMessage()
    msg["From"] = _from_header()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    try:
        if settings.smtp_port == 465:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port,
                                      context=ssl.create_default_context(), timeout=20)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
            server.ehlo()
            if settings.smtp_port in (587, 25):
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
        server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)
        server.quit()
        log.info("reset mail accepted for %s", to)
        return True
    except Exception as e:
        # Gmail's own error text is the useful part ("535 auth", "550 relay denied").
        log.error("reset mail failed for %s: %s", to, e)
        return False
