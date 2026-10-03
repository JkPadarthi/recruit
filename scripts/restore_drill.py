#!/usr/bin/env python3
"""Restore drill: prove a nightly backup can actually be restored and is usable.
Restores the newest backup to a throwaway DB, runs integrity_check, and compares
row counts against the LIVE db. Prints a verdict. Safe — never touches live data.

Usage: python3 scripts/restore_drill.py   (run anywhere the data dir is mounted;
the compose backup container doesn't hold it, so prefer running on the host or
via `docker run --rm -v $PWD/data:/data`)."""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

DATA = Path(os.environ.get("DATA_DIR", "/data"))
LIVE = Path(os.environ.get("DATABASE_URL", "sqlite:////data/db/recruit.db").replace("sqlite:///", ""))
BACKUP_DIR = DATA / "backups"

def counts(db_path: str) -> dict:
    c = sqlite3.connect(db_path)
    out = {}
    for (t,) in c.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'"):
        out[t] = c.execute(f'select count(*) from "{t}"').fetchone()[0]
    c.close()
    return out

def main() -> int:
    snaps = sorted(BACKUP_DIR.glob("recruit-*.db"), key=os.path.getmtime)
    if not snaps:
        print("FAIL: no backups found in", BACKUP_DIR)
        return 1
    src = snaps[-1]
    with tempfile.NamedTemporaryFile(suffix=".db", delete=True) as tf:
        tmp = tf.name
        # online-restore: backup src (the snapshot) INTO tmp
        s = sqlite3.connect(str(src)); d = sqlite3.connect(tmp)
        try:
            s.backup(d); d.commit()
        finally:
            d.close(); s.close()
        ic = sqlite3.connect(tmp).execute("pragma integrity_check").fetchone()[0]
        print(f"source backup  : {src.name} ({src.stat().st_size} bytes)")
        print(f"restore target : {tmp}")
        print(f"integrity_check: {ic}")
        if ic != "ok":
            print("FAIL: restored DB failed integrity_check")
            return 1
        live_counts = counts(str(LIVE))
        rest_counts = counts(tmp)
        headers = ("table", "live", "backup", "match")
        rows = []
        all_ok = True
        tables = sorted(set(live_counts) | set(rest_counts))
        for t in tables:
            l = live_counts.get(t, 0); r = rest_counts.get(t, 0)
            ok = (l == r)
            if not ok: all_ok = False
            rows.append((t, l, r, "yes" if ok else "DIFF"))
        w = max(len(str(h)) for h in headers) + max(len(r[0]) for r in rows) + 2
        print("  ".join(h.ljust(w) for h in headers))
        for r in rows:
            print("  ".join(str(x).ljust(w) for x in r))
        print("VERDICT:", "RESTORE OK — backup matches live data" if all_ok else "RESTORE MISMATCH — investigate")
        return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())