#!/usr/bin/env python3
"""Look at the Recruit database — read-only, and without unmasking anything.

The point of this tool is that the hashed columns are opaque: there is nothing to unmask.
What you *can* ask it is "is this code tracked, and by whom", because it hashes the code
you pass it and compares hashes. Your code never gets printed back.

Usage (from the host, next to the repo):

    python3 scripts/dbview.py                      # every table + row counts + integrity
    python3 scripts/dbview.py -t user_ids          # one table (first 20 rows)
    python3 scripts/dbview.py -t entries -n 5
    python3 scripts/dbview.py -t hits -n 10
    python3 scripts/dbview.py --schema user_ids
    python3 scripts/dbview.py --check K3I6O4I8     # who tracks this code (hash-compared)
    python3 scripts/dbview.py --audit              # prove no plaintext IDs are left
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import os
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "db" / "recruit.db"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
HASH_COLS = {"code_hash", "normalized_id"}
SECRET_COLS = {"password_hash", "verify_code_hash", "token_hash", "keys_json",
               "endpoint", "p256dh", "auth"}


def _key() -> bytes:
    """ID_HASH_KEY from the environment, else from the repo's .env."""
    raw = os.environ.get("ID_HASH_KEY", "").strip()
    if not raw and ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("ID_HASH_KEY="):
                raw = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    return base64.b64decode(raw) if raw else b""


def hm(code: str) -> str:
    key = _key()
    if not key:
        sys.exit("ID_HASH_KEY not found (env or .env) — cannot compare hashes")
    return hmac.new(key, code.strip().upper().encode(), hashlib.sha256).hexdigest()


def connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        sys.exit(f"no database at {path}")
    # mode=ro: this tool can never write, whatever the query says.
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def tables(c: sqlite3.Connection) -> list[str]:
    return [r[0] for r in c.execute(
        "select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]


def show_table(c: sqlite3.Connection, table: str, limit: int) -> None:
    n = c.execute(f"select count(*) from {table}").fetchone()[0]
    print(f"\n== {table}  ({n} rows, showing {min(limit, n)})\n")
    cur = c.execute(f"select * from {table} limit {limit}")
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    if not rows:
        print("  (empty)")
        return
    widths = {col: max(len(col), 6) for col in cols}
    out = []
    for r in rows:
        cells = []
        for col in cols:
            v = "" if r[col] is None else str(r[col])
            if col in HASH_COLS and len(v) > 14:
                v = v[:10] + "…"          # a hash is opaque; show that it exists, not all of it
            elif col in SECRET_COLS and v:
                v = f"<{len(v)} chars>"
            elif len(v) > 46:
                v = v[:44] + "…"
            widths[col] = max(widths[col], min(len(v), 46))
            cells.append(v)
        out.append(cells)
    print("  " + " | ".join(col.ljust(widths[col]) for col in cols))
    print("  " + "-+-".join("-" * widths[col] for col in cols))
    for cells in out:
        print("  " + " | ".join(cell.ljust(widths[col]) for cell, col in zip(cells, cols)))


def schema(c: sqlite3.Connection, table: str) -> None:
    print(f"\n== {table}\n")
    for r in c.execute(f"pragma table_info({table})"):
        null = "NOT NULL" if r[3] else ""
        print(f"  {r[1]:<16} {r[2]:<16} {null}")
    for r in c.execute("select sql from sqlite_master where tbl_name=? and type='index'", (table,)):
        if r[0]:
            print("  " + r[0])


def audit(c: sqlite3.Connection) -> None:
    print("\n== integrity: is any tracked ID still stored as text?\n")
    checks = [
        ("entries.normalized_id", "select count(*) from entries where normalized_id != ''"),
        ("entries.original", "select count(*) from entries where original != ''"),
        ("user_ids.normalized_id", "select count(*) from user_ids where normalized_id != ''"),
        ("user_ids.register_id", "select count(*) from user_ids where register_id != ''"),
        ("hits without a hash", "select count(*) from hits where length(normalized_id) != 64"),
        ("entries without a hash", "select count(*) from entries where code_hash = ''"),
        ("user_ids without a hash", "select count(*) from user_ids where code_hash = ''"),
    ]
    bad = 0
    for label, q in checks:
        n = c.execute(q).fetchone()[0]
        bad += n
        print(f"  {'FAIL' if n else 'ok  '}  {label:<26} {n}")
    print(f"\n  {'CLEAN' if bad == 0 else 'PLAINTEXT PRESENT'} — {bad} offending row(s)")


def check(c: sqlite3.Connection, code: str) -> None:
    h = hm(code)
    print(f"\n== is this code tracked?\n  lookup by hash only: {h[:12]}…\n")
    users = c.execute(
        "select u.id, u.email, ui.id from user_ids ui join users u on u.id = ui.user_id "
        "where ui.code_hash = ?", (h,)).fetchall()
    if users:
        for r in users:
            print(f"  TRACKED  user {r['id']} {r['email']}  (user_ids row {r['id'] if False else r[2]})")
    else:
        print("  not tracked by any account")
    n = c.execute("select count(distinct ingested_id) from entries where code_hash = ?", (h,)).fetchone()[0]
    print(f"  appears in {n} ingested mail(s)")
    hits = c.execute("select count(*) from hits where normalized_id = ?", (h,)).fetchone()[0]
    print(f"  produced {hits} hit(s)")


def main() -> None:
    ap = argparse.ArgumentParser(description="read-only view of the Recruit database")
    ap.add_argument("-t", "--table", help="table to print")
    ap.add_argument("-n", "--limit", type=int, default=20, help="rows to show (default 20)")
    ap.add_argument("--schema", metavar="TABLE", help="columns and indexes for one table")
    ap.add_argument("--check", metavar="CODE", help="is this code tracked? (compared as a hash)")
    ap.add_argument("--audit", action="store_true", help="verify no plaintext IDs remain")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="database file")
    a = ap.parse_args()

    c = connect(Path(a.db))
    if a.audit:
        audit(c)
    elif a.check:
        check(c, a.check)
    elif a.schema:
        schema(c, a.schema)
    elif a.table:
        show_table(c, a.table, a.limit)
    else:
        print(f"\ndatabase: {a.db}\n")
        for t in tables(c):
            n = c.execute(f"select count(*) from {t}").fetchone()[0]
            print(f"  {t:<20} {n:>8} rows")
        audit(c)
        print("\n  -t <table> to print rows · --schema <table> · --check <CODE> · --audit")


if __name__ == "__main__":
    main()
