"""Add the email-verification columns and trust everyone who signed up before them.

Every existing account was invited by hand (12 people, all known), so backfilling them
to verified is correct: the gate exists to stop strangers claiming an address, not to
lock out people already using the app.

Idempotent — safe to run twice. Backs the DB up first.
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
import time
from pathlib import Path

DB = Path("/data/db/recruit.db")

COLUMNS = {
    "email_verified": "INTEGER NOT NULL DEFAULT 0",
    "verify_code_hash": "TEXT NOT NULL DEFAULT ''",
    "verify_expires_at": "TIMESTAMP",
    "verify_attempts": "INTEGER NOT NULL DEFAULT 0",
    "verify_last_sent": "TIMESTAMP",
}


def main(path: Path) -> int:
    if not path.exists():
        print(f"!! no database at {path}", file=sys.stderr)
        return 1

    backup = path.with_name(f"{path.name}.bak_verify_{int(time.time())}")
    shutil.copy2(path, backup)
    print(f"backup: {backup.name}")

    con = sqlite3.connect(path)
    have = {row[1] for row in con.execute("PRAGMA table_info(users)")}

    added = []
    for name, decl in COLUMNS.items():
        if name in have:
            continue
        con.execute(f"ALTER TABLE users ADD COLUMN {name} {decl}")
        added.append(name)
    print("columns added:", added or "none (already present)")

    before = con.execute("SELECT COUNT(*) FROM users WHERE email_verified = 0").fetchone()[0]
    con.execute("UPDATE users SET email_verified = 1")
    con.commit()
    print(f"backfilled {before} existing account(s) as verified")

    total = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    verified = con.execute("SELECT COUNT(*) FROM users WHERE email_verified = 1").fetchone()[0]
    print(f"users: {total} · verified: {verified}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else DB))
