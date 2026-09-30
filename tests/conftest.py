"""Test fixtures. Isolated temp-file sqlite (NOT :memory: — SQLite memory gives
each connection its own empty DB), VAPID/LLM/IMAP blanked before config loads."""
import os
import sys
from pathlib import Path

os.environ["VAPID_PUBLIC_KEY"] = ""
os.environ["VAPID_PRIVATE_KEY"] = ""
os.environ["VAPID_SUBJECT"] = ""
os.environ["CDC_MAILBOX_USER"] = ""
os.environ["CDC_MAILBOX_TOKEN"] = ""
os.environ["SUMMARIZE_ENABLED"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_API_KEY"] = ""
os.environ["SECRET_KEY"] = "test-secret"
os.environ["SESSION_SECURE"] = "0"
os.environ["INVITE_CODE"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from app.db import Base, DB  # noqa: E402
from app.main import app, db as module_db  # noqa: E402


@pytest_asyncio.fixture()
async def client(tmp_path):
    """Per-test isolated temp-file DB bound into the app's module DB."""
    db = DB(url=f"sqlite:///{tmp_path / 't.db'}")
    db.create_all()  # tables exist on this engine
    # point the app's module-level DB at the test engine/session
    module_db.engine = db.engine
    module_db.session_factory = db.session_factory
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    db.drop_all()


@pytest.fixture()
def register(client):
    """Helper: register + login a user."""
    async def _reg(email="user@vit.ac.in", password="pw12345", name="Test", branch="AIML"):
        r = await client.post("/api/register", json={"email": email, "password": password,
                                                     "name": name, "branch": branch})
        assert r.status_code in (200, 201), r.text
        r2 = await client.post("/api/login", json={"email": email, "password": password})
        assert r2.status_code == 200, r2.text
        return email, password
    return _reg