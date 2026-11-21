"""The Recruit mark, drawn once and reused by every surface.

Two generators import this: `mobile/tool/make_icons.py` (Android/iOS app icons) and
`scripts/make_pwa_icons.py` (web manifest, apple-touch-icon, favicons). Keeping the
geometry here means the home-screen icon on an iPhone and the launcher icon on an
Android phone cannot drift apart.

Design rules, learned by shipping the wrong thing first:
  * One heavy letterform. An earlier mark lost its frame, arcs and negative gaps
    below 48 px.
  * Saffron #F4B33D on R.surface #16211E, straight from the app's theme.
  * The dot sits CLEAR of the letter. A tile-coloured ring around it once ate the
    R's leg and the mark read as a P.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "mobile" / "assets" / "fonts" / "Bricolage-700.ttf"

SAFFRON = (244, 179, 61, 255)
TILE = (22, 33, 30, 255)          # R.surface
SS = 4                            # supersample factor


def _font_for(inner: float, glyph: str = "R") -> tuple[ImageFont.FreeTypeFont, float, float]:
    """A font sized so `glyph`'s ink fills `inner` px, plus its ink box offset."""
    font = ImageFont.truetype(str(FONT), int(inner * 1.02))
    probe = ImageDraw.Draw(Image.new("L", (10, 10)))
    box = probe.textbbox((0, 0), glyph, font=font)
    gw, gh = box[2] - box[0], box[3] - box[1]
    scale = min(inner / gw, inner / gh)
    if scale < 1:
        font = ImageFont.truetype(str(FONT), int(font.size * scale))
        box = probe.textbbox((0, 0), glyph, font=font)
        gw, gh = box[2] - box[0], box[3] - box[1]
    return font, gw, gh


def mark(size: int, *, tile: bool = True, pad: float = 0.13, dot: bool = True) -> Image.Image:
    """The mark at `size` px. `pad` is the fraction of the canvas kept empty.

    iOS `apple-touch-icon` and maskable PWA icons need an opaque tile; the in-app
    mark is drawn with tile=False so it sits on the app's own background.
    """
    s = size * SS
    img = Image.new("RGBA", (s, s), TILE if tile else (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    inner = s * (1 - 2 * pad)
    font, gw, gh = _font_for(inner)
    box = d.textbbox((0, 0), "R", font=font)
    cx, cy = s * 0.47, s * 0.477          # nudged up-left: the dot takes the corner
    d.text((cx - gw / 2 - box[0], cy - gh / 2 - box[1]), "R", font=font, fill=SAFFRON)

    if dot:
        # Positioned relative to the GLYPH, not the canvas. Anchoring it to a canvas
        # fraction meant padding shrank the letter but never pulled the dot inward —
        # which pushed the dot outside Android's maskable safe circle.
        gx0, gy0 = cx - gw / 2, cy - gh / 2
        r = gh * 0.155
        dx, dy = gx0 + gw * 1.075, gy0 + gh * 0.90
        d.ellipse([dx - r, dy - r, dx + r, dy + r], fill=SAFFRON)

    return img.resize((size, size), Image.Resampling.LANCZOS)


def stat_icon(size: int) -> Image.Image:
    """Status-bar icon: white on transparent, no tile, no dot.

    Android paints small icons as a white silhouette, so the coloured tile icon
    shows up as a featureless white square in the status bar.
    """
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    inner = s * 0.88
    font, gw, gh = _font_for(inner)
    box = d.textbbox((0, 0), "R", font=font)
    d.text((s / 2 - gw / 2 - box[0], s / 2 - gh / 2 - box[1]), "R",
           font=font, fill=(255, 255, 255, 255))
    return img.resize((size, size), Image.Resampling.LANCZOS)
