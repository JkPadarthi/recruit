"""SQLAlchemy models (friends-only: no paywall, admin supported)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    name: Mapped[str] = mapped_column(String(120), default="")
    branch: Mapped[str] = mapped_column(String(40), default="")  # AIML / CSE_CORE / OTHER
    division: Mapped[str] = mapped_column(String(20), default="")  # "bt" (B.Tech) / "mba" / ""
    college: Mapped[str] = mapped_column(String(40), default="VIT")
    is_admin: Mapped[bool] = mapped_column(default=False)
    # Bumped on password reset; every cookie issued before it stops verifying.
    session_epoch: Mapped[int] = mapped_column(default=0)
    # 1 once the address has been proven. Accounts created before verification existed
    # are backfilled to 1 by the migration — they were invited by hand.
    email_verified: Mapped[int] = mapped_column(default=0, server_default="0")
    verify_code_hash: Mapped[str] = mapped_column(String(64), default="", server_default="")
    verify_expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verify_attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    verify_last_sent: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when Resend tells us the mailbox bounced. Not a ban — it means mail to this
    # address (including password resets) is going nowhere, so the admin must know.
    email_bounced_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ids: Mapped[list["UserId"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    hits: Mapped[list["Hit"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserId(Base):
    __tablename__ = "user_ids"
    # Uniqueness follows the hash, not the (now blank) plaintext: two rows for one user
    # would otherwise both be '' and collide.
    __table_args__ = (UniqueConstraint("user_id", "code_hash", name="uq_user_code_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # Both plaintext columns are blanked by scripts/migrate_hash_ids.py and stay blank:
    # the keyed hash is the only record of the code from then on. They are kept so a
    # half-migrated deployment (no ID_HASH_KEY) still works instead of crashing.
    register_id: Mapped[str] = mapped_column(String(64), default="")     # legacy, blanked
    normalized_id: Mapped[str] = mapped_column(String(64), index=True, default="")  # legacy
    # HMAC-SHA256(normalized_id, ID_HASH_KEY) — what matching actually compares.
    code_hash: Mapped[str] = mapped_column(String(64), index=True, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="ids")


class Ingested(Base):
    __tablename__ = "ingested"
    __table_args__ = (UniqueConstraint("msg_uid", name="uq_ingested_msg_uid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    msg_uid: Mapped[str] = mapped_column(String(32))              # IMAP UID
    folder: Mapped[str] = mapped_column(String(64), default="INBOX")
    subject: Mapped[str] = mapped_column(String(300), default="")
    from_addr: Mapped[str] = mapped_column(String(255), default="")
    date: Mapped[str] = mapped_column(String(80), default="")
    kind: Mapped[str] = mapped_column(String(20), default="announcement")  # shortlist | announcement
    outcome: Mapped[str] = mapped_column(String(20), default="")  # "" | shortlist | selection
    eligible_branches: Mapped[str] = mapped_column(Text, default="")
    links: Mapped[str] = mapped_column(Text, default="")  # JSON list of URLs found in the mail
    # LLM summary (gated): raw JSON string of the summary schema; "" when not summarized
    summary: Mapped[str] = mapped_column(Text, default="")
    summary_status: Mapped[str] = mapped_column(String(20), default="")  # "" | ok | deferred | error
    content_hash: Mapped[str] = mapped_column(String(64), default="", index=True)  # dedup/summary cache key
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    entries: Mapped[list["Entry"]] = relationship(back_populates="ingested", cascade="all, delete-orphan")


class Entry(Base):
    __tablename__ = "entries"
    __table_args__ = (UniqueConstraint("ingested_id", "code_hash", name="uq_entry_code_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ingested_id: Mapped[int] = mapped_column(ForeignKey("ingested.id"), index=True)
    # Blanked by scripts/migrate_hash_ids.py: a CDC shortlist names every selected
    # student, so this table is the single biggest pile of NEO IDs in the system.
    normalized_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    original: Mapped[str] = mapped_column(String(120), default="")
    code_hash: Mapped[str] = mapped_column(String(64), index=True, default="")
    # The spreadsheet row this code sat on: date/venue/time/stack, label-qualified.
    # "" when the mail had no row context (body-only lists, no attachment).
    slot: Mapped[str] = mapped_column(Text, default="")

    ingested: Mapped[Ingested] = relationship(back_populates="entries")


class Hit(Base):
    __tablename__ = "hits"
    __table_args__ = (UniqueConstraint("user_id", "ingested_id", "normalized_id", name="uq_hit"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    ingested_id: Mapped[int] = mapped_column(ForeignKey("ingested.id"), index=True)
    normalized_id: Mapped[str] = mapped_column(String(64))
    first_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="hits")
    ingested: Mapped[Ingested] = relationship()


class AppState(Base):
    __tablename__ = "app_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    last_uid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uidvalidity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_poll_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FcmToken(Base):
    """One Android/Android-shell device token per row (FCM HTTP v1).

    Separate from push_subscriptions because the transport is different: a browser
    endpoint has p256dh+auth keys, an FCM token is just a string handed to Play
    Services. Keeping them apart means a dead FCM token can be pruned without
    touching the web subscription and vice versa.
    """
    __tablename__ = "fcm_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    platform: Mapped[str] = mapped_column(String(16), default="android")
    token: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PushSubscription(Base):
    """One push endpoint per user/platform (web = Web Push/VAPID; fcm/apns later)."""
    __tablename__ = "push_subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "platform", "endpoint", name="uq_push"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    platform: Mapped[str] = mapped_column(String(16), default="web")
    endpoint: Mapped[str] = mapped_column(String(512))
    keys_json: Mapped[str] = mapped_column(Text, default="{}")  # p256dh + auth
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship()

class PasswordReset(Base):
    """A reset request, and later the link handed to that user.

    Two states in one row, deliberately: `token_hash` empty means "the user asked,
    nobody has issued a link yet" — the admin panel lists exactly those. Issuing a
    link fills the hash and the expiry, so there is a single audit trail instead of a
    request table plus a token table that can disagree.

    Only the HASH of the token is stored. A leaked database must not be a stack of
    working password links.
    """
    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship()
