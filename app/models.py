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
    college: Mapped[str] = mapped_column(String(40), default="VIT")
    is_admin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ids: Mapped[list["UserId"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    hits: Mapped[list["Hit"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserId(Base):
    __tablename__ = "user_ids"
    __table_args__ = (UniqueConstraint("user_id", "normalized_id", name="uq_user_normalized"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    register_id: Mapped[str] = mapped_column(String(64))          # raw as entered
    normalized_id: Mapped[str] = mapped_column(String(64), index=True)  # squashed+uppercased
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
    __table_args__ = (UniqueConstraint("ingested_id", "normalized_id", name="uq_entry_normalized"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ingested_id: Mapped[int] = mapped_column(ForeignKey("ingested.id"), index=True)
    normalized_id: Mapped[str] = mapped_column(String(64), index=True)
    original: Mapped[str] = mapped_column(String(120), default="")

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