#!/usr/bin/env python3
"""Rebuild the `hits` table from what is still in the database.

Why this is possible at all: a hit is not stored knowledge, it is a *derived* claim —
"this user's tracked code appeared on this mail". Both halves survive independently:

  * `entries`   which hashes were on which mail (per ingested_id)
  * `user_ids`  which hashes belong to which user

So losing `hits` costs history-view and read/unread flags, not information. This script
recomputes the rows with a single set join, using the same hashes the matcher compares.

What cannot be recovered: `read_at` (when someone opened a hit) — those become unread
again, and `first_seen_at` is set to the mail's own timestamp, which is the honest
approximation.

Usage:
    python3 scripts/rebuild_hits.py                     # dry run on the live DB
    python3 scripts/rebuild_hits.py --apply             # write the rows back
    python3 scripts/rebuild_hits.py --db /tmp/copy.db --apply
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "db" / "recruit.db"


def plan(c: sqlite3.Connection) -> list[tuple]:
    """Every (user_id, ingested_id, code_hash) that should exist, with the mail's time."""
    return c.execute("""
        select ui.user_id, e.ingested_id, e.code_hash, i.created_at
        from entries e
        join user_ids ui on ui.code_hash = e.code_hash
        join ingested  i on i.id = e.ingested_id
        group by ui.user_id, e.ingested_id, e.code_hash
        order by e.ingested_id, ui.user_id
    """).fetchall()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    a = ap.parse_args()

    path = Path(a.db)
    if not path.exists():
        print(f"no database at {path}")
        return 2

    # A dry run must not write; --apply needs rw or the CREATE/INSERT below fails with
    # "attempt to write a readonly database".
    mode = "rw" if a.apply else "ro"
    ro = sqlite3.connect(f"file:{path}?mode={mode}", uri=True)
    exists = ro.execute(
        "select count(*) from sqlite_master where type='table' and name='hits'").fetchone()[0]
    current = ro.execute("select count(*) from hits").fetchone()[0] if exists else 0
    rows = plan(ro)
    print(f"table present: {bool(exists)} | rows now: {current} | rows implied by entries: {len(rows)}")

    if not a.apply:
        print("dry run — nothing written. add --apply to insert them.")
        ro.close()
        return 0

    if not exists:
        ro.execute("""create table if not exists hits (
                         id integer primary key,
                         user_id integer not null references users(id),
                         ingested_id integer not null references ingested(id),
                         normalized_id varchar(64) not null,
                         first_seen_at datetime not null default current_timestamp,
                         read_at datetime,
                         constraint uq_hit unique (user_id, ingested_id, normalized_id))""")
        ro.execute("create unique index if not exists uq_hit on hits (user_id, ingested_id, normalized_id)")
        ro.execute("create index if not exists ix_hits_user_id on hits (user_id)")
        ro.execute("create index if not exists ix_hits_ingested_id on hits (ingested_id)")

    before = ro.execute("select count(*) from hits").fetchone()[0]
    ro.executemany("""insert or ignore into hits
                        (user_id, ingested_id, normalized_id, first_seen_at)
                      values (?, ?, ?, ?)""", rows)
    ro.commit()
    after = ro.execute("select count(*) from hits").fetchone()[0]
    print(f"inserted {after - before} row(s) → hits now {after}")
    ro.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
