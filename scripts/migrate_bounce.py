"""Add users.email_bounced_at — Resend's bounce reports land here.

Idempotent, backs the DB up first, and is safe to run while the old code is still live
(the column is nullable and nothing reads it yet).
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
import time
from pathlib import Path

DB = Path("/data/db/recruit.db")


def main(path: Path) -> int:
    if not path.exists():
        print(f"!! no database at {path}", file=sys.stderr)
        return 1
    backup = path.with_name(f"{path.name}.bak_bounce_{int(time.time())}")
    shutil.copy2(path, backup)
    print(f"backup: {backup.name}")

    con = sqlite3.connect(path)
    cols = {row[1] for row in con.execute("PRAGMA table_info(users)")}
    if "email_bounced_at" in cols:
        print("column already present")
    else:
        con.execute("ALTER TABLE users ADD COLUMN email_bounced_at TIMESTAMP")
        con.commit()
        print("added users.email_bounced_at")
    print("users:", con.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else DB))
