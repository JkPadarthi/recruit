#!/usr/bin/env python3
"""Publish a built APK to the site so Android users can download it.

    python3 scripts/publish_apk.py ~/Downloads/recruit-v1.1.6.apk --notes "new mark"

Copies the file to the app host's durable data dir and writes `apk.json` next to it.
The web app serves both (`/download`, `/api/app`); `/data/apk` is read per request, so
no restart is needed.

Why not commit the APK: 19 MB per version in git history is a tax forever. The binary
lives on the host, git holds only the code that serves it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

HOST = os.environ.get("APK_HOST", "abhi")
REMOTE_DIR = os.environ.get("APK_REMOTE_DIR", "Projects/recruit/data/apk")


def version_of(apk: Path) -> str:
    """versionName out of the binary AndroidManifest (UTF-16 string pool)."""
    with zipfile.ZipFile(apk) as z:
        raw = z.read("AndroidManifest.xml")
    for run in re.findall(rb"(?:[\x20-\x7e]\x00){3,}", raw):
        s = run.decode("utf-16-le")
        if re.fullmatch(r"\d+\.\d+\.\d+", s):
            return s
    raise SystemExit("no versionName found — is this actually an APK?")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("apk")
    ap.add_argument("--notes", default="", help="one line shown on the download card")
    args = ap.parse_args()

    apk = Path(args.apk).expanduser().resolve()
    if not apk.is_file():
        raise SystemExit(f"no such file: {apk}")
    if not zipfile.is_zipfile(apk):
        raise SystemExit(f"not a zip/apk: {apk}")

    version = version_of(apk)
    digest = sha256(apk)
    size = apk.stat().st_size
    manifest = {
        "version": version,
        "size_bytes": size,
        "sha256": digest,
        "built_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "notes": args.notes,
    }

    tmp = Path("/tmp/apk.json")
    tmp.write_text(json.dumps(manifest, indent=2))

    print(f"==> publishing recruit v{version} ({size / 1048576:.1f} MB) to {HOST}:{REMOTE_DIR}")
    subprocess.run(["ssh", HOST, f"mkdir -p ~/{REMOTE_DIR}"], check=True)
    subprocess.run(["scp", "-q", str(apk), f"{HOST}:~/{REMOTE_DIR}/recruit.apk"], check=True)
    subprocess.run(["scp", "-q", str(tmp), f"{HOST}:~/{REMOTE_DIR}/apk.json"], check=True)

    # Read the bytes back: scp exiting 0 does not prove the file arrived intact, and a
    # truncated APK fails to install with a message that blames the user's phone.
    remote = subprocess.run(
        ["ssh", HOST, f"sha256sum ~/{REMOTE_DIR}/recruit.apk"],
        check=True, capture_output=True, text=True,
    ).stdout.split()[0]
    if remote != digest:
        raise SystemExit(f"remote sha256 mismatch: {remote[:12]}… != {digest[:12]}…")

    print(f"    sha256 verified on host: {digest[:16]}…")
    print(f"    served at /download and /api/app")


if __name__ == "__main__":
    main()
