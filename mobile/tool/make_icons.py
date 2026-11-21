#!/usr/bin/env python3
"""Generate every app icon from one definition.

Run from mobile/:  python3 tool/make_icons.py

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
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent.parent
SAFFRON = (244, 179, 61, 255)
TILE = (22, 33, 30, 255)   # R.surface, not the page background
FONT = HERE / "assets" / "fonts" / "Bricolage-700.ttf"

MASTER = 2048          # supersample; everything is downsampled from this
SS = 4                 # extra factor for shape anti-aliasing


def draw_mark(size: int, *, tile: bool, pad: float) -> Image.Image:
    """The mark at `size` px. `pad` is the fraction of the canvas kept empty."""
    s = size * SS
    img = Image.new("RGBA", (s, s), TILE if tile else (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    inner = s * (1 - 2 * pad)
    # The R: sized by bounding box, then centred on its own ink, not its em box.
    font = ImageFont.truetype(str(FONT), int(inner * 1.02))
    box = d.textbbox((0, 0), "R", font=font)
    gw, gh = box[2] - box[0], box[3] - box[1]
    scale = min(inner / gw, inner / gh)
    if scale < 1:
        font = ImageFont.truetype(str(FONT), int(font.size * scale))
        box = d.textbbox((0, 0), "R", font=font)
        gw, gh = box[2] - box[0], box[3] - box[1]

    cx, cy = s * 0.47, s * 0.477          # nudged up-left: the dot takes the corner
    d.text((cx - gw / 2 - box[0], cy - gh / 2 - box[1]), "R", font=font, fill=SAFFRON)

    # One dot, bottom-right: "you were shortlisted". It sits clear of the
    # letterform on purpose — an earlier version painted a tile-coloured ring
    # around it, which ate the R's leg and made the mark read as a P.
    r = gh * 0.155
    dx, dy = s * 0.775, s * 0.775
    d.ellipse([dx - r, dy - r, dx + r, dy + r], fill=SAFFRON)

    return img.resize((size, size), Image.Resampling.LANCZOS)


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
