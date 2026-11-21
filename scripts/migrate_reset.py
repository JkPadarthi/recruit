"""Add what the reset flow needs: users.session_epoch and the password_resets table.

Run INSIDE the container (the DB lives at /data/db/recruit.db there):
    ssh abhi 'docker exec -i recruit-app-1 python3 -' < scripts/migrate_reset.py

Safe to run twice. Backs the database up first, because the alternative — a failed
ALTER on the live DB with no snapshot — is how a small feature becomes an outage.
"""
from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path

DB = Path("/data/db/recruit.db")

if not DB.is_file():
    raise SystemExit(f"no database at {DB}")

backup = DB.with_suffix(f".db.bak_reset_{int(time.time())}")
shutil.copy2(DB, backup)
print(f"backup: {backup} ({backup.stat().st_size // 1024} KB)")

con = sqlite3.connect(DB)
cur = con.cursor()

cols = [r[1] for r in cur.execute("PRAGMA table_info(users)")]
if "session_epoch" not in cols:
    cur.execute("ALTER TABLE users ADD COLUMN session_epoch INTEGER NOT NULL DEFAULT 0")
    print("added users.session_epoch")
else:
    print("users.session_epoch already present")

cur.execute("""
    CREATE TABLE IF NOT EXISTS password_resets (
        id          INTEGER PRIMARY KEY,
        user_id     INTEGER NOT NULL REFERENCES users(id),
        token_hash  VARCHAR(64) NOT NULL DEFAULT '',
        created_at  DATETIME    DEFAULT CURRENT_TIMESTAMP,
        expires_at  DATETIME,
        used_at     DATETIME
    )
""")
cur.execute("CREATE INDEX IF NOT EXISTS ix_password_resets_user_id ON password_resets (user_id)")
cur.execute("CREATE INDEX IF NOT EXISTS ix_password_resets_token_hash ON password_resets (token_hash)")
con.commit()

# Prove it, rather than trusting the statements above.
cols = [r[1] for r in cur.execute("PRAGMA table_info(users)")]
tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
users = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
con.close()

print("users.session_epoch:", "session_epoch" in cols)
print("password_resets table:", "password_resets" in tables)
print("users intact:", users)
