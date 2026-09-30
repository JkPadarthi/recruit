"""Online SQLite backup using the stdlib backup API. Keeps last N in backups/."""
import os
import shutil
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(os.environ.get("DATABASE_URL", "sqlite:////data/db/recruit.db")
                .replace("sqlite:///", ""))
BACKUP_DIR = Path(os.environ.get("DB_BACKUP_DIR", "/data/backups"))
KEEP = int(os.environ.get("BACKUP_KEEP", "14"))


def main() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dest = BACKUP_DIR / f"recruit-{__import__('datetime').datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close(); src.close()
    # prune old
    snaps = sorted(BACKUP_DIR.glob("recruit-*.db"), key=os.path.getmtime)
    for old in snaps[:-KEEP]:
        old.unlink()
    print(f"backup written: {dest}")
    print(f"kept {min(len(snaps), KEEP)}/{sum(1 for _ in BACKUP_DIR.glob('recruit-*.db'))}")


if __name__ == "__main__":
    main()