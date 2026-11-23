"""Replace every stored NEO ID / register number with a keyed hash.

What it touches (all three tables that held the codes):

* `entries.normalized_id` and `entries.original` — a CDC shortlist attachment lists every
  selected student, so this is the biggest pile of IDs in the system (164k rows).
* `user_ids.normalized_id` / `register_id` — which student is watching which code.
* `hits.normalized_id` — which of a user's codes matched which mail.

After this runs the plaintext is gone from the database. It is NOT recoverable without
`ID_HASH_KEY`, and it is not recoverable *with* it either (HMAC is one-way) — matching only
needs equality, and the UI shows "ID 1", "ID 2" instead.

Both `user_ids` and `entries` get their unique constraint rebuilt over `code_hash`: two
blanked plaintext rows for one user would otherwise collide on ''.

Idempotent: rows that already have a code_hash are skipped, so a re-run is a no-op.
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ids import hash_id, hashing_enabled  # noqa: E402


def _cols(c: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in c.execute(f"pragma table_info({table})")}


def _backup(db_path: Path) -> Path:
    dest = db_path.with_name(f"{db_path.name}.bak_hash_{int(time.time())}")
    shutil.copy2(db_path, dest)
    return dest


def main(db_path: str) -> int:
    if not hashing_enabled():
        print("REFUSING: ID_HASH_KEY is not set. Hashing with an empty key would store the")
        print("IDs unchanged in a column called code_hash — worse than not migrating.")
        return 2

    path = Path(db_path)
    dest = _backup(path)
    print(f"backup: {dest.name} ({dest.stat().st_size // 1024} KiB)")

    c = sqlite3.connect(path)
    c.execute("pragma journal_mode=wal")

    # ---- 1. columns -------------------------------------------------------
    for table in ("user_ids", "entries"):
        if "code_hash" not in _cols(c, table):
            c.execute(f"alter table {table} add column code_hash varchar(64) default ''")
            print(f"{table}: added code_hash")

    # ---- 2. backfill every plaintext value --------------------------------
    entries = c.execute(
        "select id, normalized_id from entries where code_hash = '' and normalized_id != ''"
    ).fetchall()
    c.executemany("update entries set code_hash = ? where id = ?",
                  [(hash_id(n), i) for i, n in entries])
    print(f"entries: hashed {len(entries)}")

    uids = c.execute(
        "select id, normalized_id from user_ids where code_hash = '' and normalized_id != ''"
    ).fetchall()
    c.executemany("update user_ids set code_hash = ? where id = ?",
                  [(hash_id(n), i) for i, n in uids])
    print(f"user_ids: hashed {len(uids)}")

    # hits.normalized_id holds the matched code; rewrite in place (it is the dedupe key,
    # so it must become the same hash the matcher will compare against).
    hits = c.execute("select id, normalized_id from hits "
                     "where length(normalized_id) != 64").fetchall()
    c.executemany("update hits set normalized_id = ? where id = ?",
                  [(hash_id(n), i) for i, n in hits])
    print(f"hits: hashed {len(hits)}")

    # ---- 3. (the plaintext is wiped by the rebuild below) -----------------
    # Blanks cannot be set with an UPDATE: the OLD unique constraint is still
    # (ingested_id, normalized_id), so every row of a mail would collide on ''. The
    # table rebuild drops that constraint and inserts '' in one statement instead.
    c.commit()

    # ---- 4. rebuild both tables so uniqueness follows code_hash -----------
    c.executescript("""
        begin;
        create table user_ids_new (
            id integer primary key,
            user_id integer not null references users(id),
            register_id varchar(64) not null default '',
            normalized_id varchar(64) not null default '',
            code_hash varchar(64) not null default '',
            created_at datetime default current_timestamp
        );
        insert into user_ids_new (id, user_id, register_id, normalized_id, code_hash, created_at)
            select id, user_id, '', '', code_hash, created_at from user_ids;
        drop table user_ids;
        alter table user_ids_new rename to user_ids;
        create unique index uq_user_code_hash on user_ids (user_id, code_hash);
        create index ix_user_ids_user_id on user_ids (user_id);
        create index ix_user_ids_code_hash on user_ids (code_hash);

        create table entries_new (
            id integer primary key,
            ingested_id integer not null references ingested(id),
            normalized_id varchar(64) not null default '',
            original varchar(120) not null default '',
            code_hash varchar(64) not null default '',
            slot text not null default ''
        );
        insert into entries_new (id, ingested_id, normalized_id, original, code_hash, slot)
            select id, ingested_id, '', '', code_hash, slot from entries;
        drop table entries;
        alter table entries_new rename to entries;
        create unique index uq_entry_code_hash on entries (ingested_id, code_hash);
        create index ix_entries_ingested_id on entries (ingested_id);
        create index ix_entries_code_hash on entries (code_hash);
        commit;
    """)
    print("tables rebuilt with uniqueness on code_hash")

    # ---- 5. prove the plaintext is gone ----------------------------------
    for table, cols in (("entries", ("normalized_id", "original")),
                        ("user_ids", ("normalized_id", "register_id"))):
        leftovers = c.execute(
            f"select count(*) from {table} where " + " or ".join(f"{x} != ''" for x in cols)
        ).fetchone()[0]
        print(f"{table}: rows still holding text = {leftovers}")

    rows = c.execute("select count(*), count(distinct code_hash) from entries").fetchone()
    print(f"entries: {rows[0]} rows, {rows[1]} distinct hashes")
    blank = c.execute("select count(*) from user_ids where code_hash = ''").fetchone()[0]
    print(f"user_ids: rows without a hash = {blank}")
    c.commit()
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/data/db/recruit.db"))
