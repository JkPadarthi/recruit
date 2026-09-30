"""Database engine/session bootstrap (SQLite + SQLAlchemy 2.0)."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    u = url or settings.database_url
    kwargs = {"echo": False}
    if u.startswith("sqlite"):
        kwargs.setdefault("connect_args", {"check_same_thread": False})
    return create_engine(u, **kwargs)


class DB:
    """Small holder so tests can swap engine per app instance."""

    def __init__(self, url: str | None = None):
        self.url = url or settings.database_url
        self.engine = make_engine(self.url)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def create_all(self):
        from . import models  # noqa: F401
        Base.metadata.create_all(self.engine)

    def drop_all(self):
        from . import models  # noqa: F401
        Base.metadata.drop_all(self.engine)

    def session(self):
        return self.session_factory()