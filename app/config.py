"""Recruit app configuration (from environment, never secrets in code)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_BASE = Path(__file__).resolve().parent.parent


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _flag(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class Settings:
    # Core
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "sqlite:///./recruit.db"))
    secret_key: str = field(default_factory=lambda: _env("SECRET_KEY", "dev-insecure-key"))
    session_cookie_name: str = field(default_factory=lambda: _env("SESSION_COOKIE_NAME", "recruit_session"))
    session_max_age_sec: int = int(_env("SESSION_MAX_AGE_SEC", str(60 * 60 * 24 * 7)))
    session_secure: bool = field(default_factory=lambda: _flag(_env("SESSION_SECURE", "1")))
    brand_name: str = field(default_factory=lambda: _env("BRAND_NAME", "Recruit"))
    public_base_url: str = field(default_factory=lambda: _env("PUBLIC_BASE_URL", "http://127.0.0.1:8090"))
    invite_code: str = field(default_factory=lambda: _env("INVITE_CODE", "").strip())  # empty = open
    admin_email: str = field(default_factory=lambda: _env("ADMIN_EMAIL", "").strip().lower())
    allowed_email_domains: tuple = field(
        default_factory=lambda: tuple(d.strip().lower() for d in _env("ALLOWED_EMAIL_DOMAINS", "").split(",") if d.strip()))

    # IMAP / CDC mailbox
    imap_host: str = field(default_factory=lambda: _env("IMAP_HOST", "imap.gmail.com"))
    imap_port: int = int(_env("IMAP_PORT", "993"))
    cdc_mailbox_user: str = field(default_factory=lambda: _env("CDC_MAILBOX_USER", ""))
    cdc_mailbox_token: str = field(default_factory=lambda: _env("CDC_MAILBOX_TOKEN", ""))
    poll_interval_min: int = int(_env("POLL_INTERVAL_MIN", "5"))

    # Paths
    log_dir: str = field(default_factory=lambda: _env("LOG_DIR", str(_BASE / "logs")))
    db_backup_dir: str = field(default_factory=lambda: _env("DB_BACKUP_DIR", str(_BASE / "backups")))

    # Web Push / VAPID (empty = push disabled, app still works)
    vapid_public_key: str = field(default_factory=lambda: _env("VAPID_PUBLIC_KEY", ""))
    vapid_private_key: str = field(default_factory=lambda: _env("VAPID_PRIVATE_KEY", ""))
    vapid_subject: str = field(default_factory=lambda: _env("VAPID_SUBJECT", "mailto:admin@example.com"))

    # LLM summarizer (gated off until the deterministic core is validated)
    summarize_enabled: bool = field(default_factory=lambda: _flag(_env("SUMMARIZE_ENABLED", "")))
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", ""))
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", ""))
    llm_timeout_s: int = int(_env("LLM_TIMEOUT_S", "30"))

    # Dev-only testing endpoints. MUST be off in production.
    enable_dev_endpoint: bool = field(default_factory=lambda: _flag(_env("ENABLE_DEV_ENDPOINT", "")))


settings = Settings()