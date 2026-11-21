#!/usr/bin/env python3
"""Generate every app icon from one definition.

Run from mobile/:  python3 tool/make_icons.py

PWA icons are generated next door by:  python3 scripts/make_pwa_icons.py

Design notes, so a future edit does not undo them:
  * One glyph, no hairlines. The previous mark lost its frame, arcs and negative
    gaps below 48 px. Everything here survives being scaled to 48 px because it is
    a single heavy letterform plus one dot.
  * The monogram is drawn in Bricolage 700 — the same display face the UI uses, so
    the icon and the app look like one product.
  * Saffron #F4B33D on tile #101B18, straight from lib/theme.dart.
  * Android adaptive icons must keep their content inside the middle ~66% (the
    launcher masks and parades the rest), so the foreground layer is padded hard.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent          # mobile/

# Geometry lives in scripts/icon_art.py, shared with scripts/make_pwa_icons.py, so the
# web icon and the native icon cannot drift apart.
sys.path.insert(0, str(HERE.parent / "scripts"))
from PIL import Image  # noqa: E402
from icon_art import mark as draw_mark, stat_icon as draw_stat_icon  # noqa: E402


def write(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG", optimize=True)
    print(f"  {path.relative_to(HERE)}  {img.size[0]}x{img.size[1]}")


def main() -> None:
    res = HERE / "android" / "app" / "src" / "main" / "res"

    print("android legacy mipmaps")
    for folder, px in [("mdpi", 48), ("hdpi", 72), ("xhdpi", 96),
                       ("xxhdpi", 144), ("xxxhdpi", 192)]:
        write(draw_mark(px, tile=True, pad=0.13), res / f"mipmap-{folder}" / "ic_launcher.png")

    print("android adaptive foreground (108dp canvas, art inside the safe zone)")
    fg = draw_mark(432, tile=False, pad=0.235)
    write(fg, res / "drawable" / "ic_launcher_foreground.png")

    print("status-bar icon (white silhouette, 24dp nominal)")
    for folder, px in [("mdpi", 24), ("hdpi", 36), ("xhdpi", 48),
                       ("xxhdpi", 72), ("xxxhdpi", 96)]:
        write(draw_stat_icon(px), res / f"drawable-{folder}" / "ic_stat_recruit.png")

    print("ios app icons")
    ios = HERE / "ios" / "Runner" / "Assets.xcassets" / "AppIcon.appiconset"
    for name, px in [("Icon-App-20x20@1x.png", 20), ("Icon-App-20x20@2x.png", 40),
                     ("Icon-App-20x20@3x.png", 60), ("Icon-App-29x29@1x.png", 29),
                     ("Icon-App-29x29@2x.png", 58), ("Icon-App-29x29@3x.png", 87),
                     ("Icon-App-40x40@1x.png", 40), ("Icon-App-40x40@2x.png", 80),
                     ("Icon-App-40x40@3x.png", 120), ("Icon-App-60x60@2x.png", 120),
                     ("Icon-App-60x60@3x.png", 180), ("Icon-App-76x76@1x.png", 76),
                     ("Icon-App-76x76@2x.png", 152), ("Icon-App-83.5x83.5@2x.png", 167),
                     ("Icon-App-1024x1024@1x.png", 1024)]:
        write(draw_mark(px, tile=True, pad=0.13).convert("RGB"), ios / name)

    print("in-app mark + store art")
    write(draw_mark(512, tile=False, pad=0.06), HERE / "assets" / "brand" / "logo.png")
    write(draw_mark(1024, tile=True, pad=0.13), HERE / "assets" / "brand" / "logo-tile.png")
    write(draw_mark(512, tile=True, pad=0.13), HERE / "assets" / "brand" / "store-512.png")

    print("legibility check: 48 px")
    write(draw_mark(48, tile=True, pad=0.13), HERE / "assets" / "brand" / "check-48.png")


if __name__ == "__main__":
    main()
