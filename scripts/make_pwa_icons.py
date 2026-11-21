#!/usr/bin/env python3
"""Generate every PWA icon: manifest sizes, maskable, apple-touch-icon, favicons.

Run from the repo root:  python3 scripts/make_pwa_icons.py

Why maskable gets its own file: the manifest used to claim `"any maskable"` on the
full-bleed art. Android then masks it to a circle, and anything in the corners — the
dot, in our case — is cropped away. A maskable icon must keep its content inside the
middle 80% circle, so it is drawn with much heavier padding.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from icon_art import mark  # noqa: E402

STATIC = ROOT / "static"


def save(img, name: str) -> None:
    path = STATIC / name
    img.save(path, "PNG", optimize=True)
    print(f"  static/{name:<26} {img.size[0]}x{img.size[1]}  {path.stat().st_size // 1024 or 1} KB")


def main() -> None:
    print("manifest icons (purpose: any)")
    for px in (192, 384, 512):
        save(mark(px, pad=0.13).convert("RGB"), f"icon-{px}.png")

    print("maskable (content inside the safe circle)")
    save(mark(512, pad=0.26).convert("RGB"), "icon-maskable-512.png")

    print("apple-touch-icon (opaque; iOS puts black behind transparency)")
    save(mark(180, pad=0.16).convert("RGB"), "apple-touch-icon.png")

    print("favicons")
    save(mark(32, pad=0.09).convert("RGB"), "favicon.png")
    save(mark(256, pad=0.11).convert("RGB"), "favicon-256.png")

    # Multi-size .ico: browsers pick the size they need, and a 16px entry that is
    # merely a downscaled 256 looks like mud.
    ico_sizes = [16, 32, 48]
    base = mark(max(ico_sizes), pad=0.09).convert("RGB")
    base.save(STATIC / "favicon.ico", sizes=[(s, s) for s in ico_sizes])
    print(f"  static/favicon.ico              {', '.join(f'{s}x{s}' for s in ico_sizes)}")


if __name__ == "__main__":
    main()
