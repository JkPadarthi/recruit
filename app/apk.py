"""Serving the Android APK from the site itself.

Students should not need a Telegram link to install the app: the web app is already
the thing they trust, so the download lives next to it. The APK is NOT committed to
git — a 19 MB binary per version bloats history — it sits in `data/apk/`, which is the
bind-mounted durable host dir, and `apk.json` describes it.

`apk.json` is written by scripts/publish_apk.py at build time:
    {"version": "1.1.6", "size_bytes": 19891234, "sha256": "...",
     "built_at": "2026-11-21T23:52:10+05:30", "notes": "..."}
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter(tags=["app"])

APK_NAME = "recruit.apk"


def _dir() -> Path:
    # Env override so tests (and any future host) can point somewhere else.
    return Path(os.environ.get("APK_DIR", "/data/apk"))


def apk_info() -> dict | None:
    """Metadata for the download card, or None when no build has been published.

    Every page that shows the card calls this; a missing build must degrade to "no
    card", never to a 500.
    """
    d = _dir()
    manifest = d / "apk.json"
    apk = d / APK_NAME
    if not apk.is_file():
        return None
    info: dict = {"version": "", "size_bytes": apk.stat().st_size,
                  "built_at": "", "notes": "", "sha256": ""}
    if manifest.is_file():
        try:
            info.update({k: v for k, v in json.loads(manifest.read_text()).items()
                         if k in info})
        except Exception:
            pass
    info["available"] = True
    info["size_mb"] = round(info["size_bytes"] / (1024 * 1024), 1)
    return info


@router.get("/api/app")
def app_manifest(request: Request):
    """Public: what the download card needs, without touching /data blindly."""
    info = apk_info()
    if not info:
        return JSONResponse({"available": False})
    return JSONResponse(info)


@router.get("/download")
def download_apk(request: Request):
    """The APK itself.

    Content-Type is `application/vnd.android.package-archive` and there is a
    filename in Content-Disposition: Android's browser then offers "Install" instead
    of saving an unnamed blob, which is where sideloading usually falls apart.
    """
    d = _dir()
    apk = d / APK_NAME
    if not apk.is_file():
        raise HTTPException(404, "no build published yet")
    info = apk_info() or {}
    version = info.get("version") or "latest"
    return FileResponse(
        apk,
        media_type="application/vnd.android.package-archive",
        filename=f"recruit-v{version}.apk" if version != "latest" else "recruit.apk",
    )
