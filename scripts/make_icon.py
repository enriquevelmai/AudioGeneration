"""Generates the AudioGeneration icon: assets/icon.png (512 px) and assets/icon.ico (16-256 px).

Design: a "squircle" with a violet -> coral gradient, a white studio microphone in the
center and two pairs of sound waves in warm yellow. It is drawn at 4x and downscaled
with LANCZOS for smooth edges; the small .ico sizes (16-32 px) use a simplified
version (no grille or outer waves) so that it stays legible.

Pillow is NOT a project dependency. Run with:

    uv run --no-project --with pillow python scripts/make_icon.py
"""
from __future__ import annotations

from pathlib import Path

import math

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

BASE = 512            # design space
S = 4                 # supersampling
SZ = BASE * S

TOP_LEFT = (124, 58, 237)      # violet   #7C3AED
BOTTOM_RIGHT = (251, 113, 133)  # coral    #FB7185
MIC = (255, 255, 255)
MIC_SHADE = (237, 233, 254)    # very light lavender for the grille
GRILLE = (167, 139, 250)       # #A78BFA
WAVE = (253, 224, 71)          # yellow   #FDE047
SHADOW = (49, 16, 107, 90)     # soft shadow under the mic


def sc(v: float) -> int:
    return int(round(v * S))


def box(x0: float, y0: float, x1: float, y1: float) -> list[int]:
    return [sc(x0), sc(y0), sc(x1), sc(y1)]


def gradient() -> Image.Image:
    """Diagonal gradient (top-left -> bottom-right) the size of the canvas."""
    ramp = Image.linear_gradient("L").resize((SZ * 2, SZ * 2)).rotate(45, resample=Image.BICUBIC)
    off = SZ // 2
    mask = ramp.crop((off, off, off + SZ, off + SZ))
    a = Image.new("RGB", (SZ, SZ), TOP_LEFT)
    b = Image.new("RGB", (SZ, SZ), BOTTOM_RIGHT)
    return Image.composite(b, a, mask).convert("RGBA")


def squircle_mask(radius: float = 116) -> Image.Image:
    m = Image.new("L", (SZ, SZ), 0)
    ImageDraw.Draw(m).rounded_rectangle(box(16, 16, 496, 496), radius=sc(radius), fill=255)
    return m


def arc(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, start: float, end: float,
        width: float, fill) -> None:
    d.arc(box(cx - r, cy - r, cx + r, cy + r), start=start, end=end, fill=fill, width=sc(width))
    # rounded ends
    for ang in (start, end):
        x = cx + (r - width / 2) * math.cos(math.radians(ang))
        y = cy + (r - width / 2) * math.sin(math.radians(ang))
        d.ellipse(box(x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=fill)


def draw(simple: bool = False) -> Image.Image:
    """Full icon at SZ x SZ. ``simple`` = variant for 16-32 px."""
    bg = gradient()
    layer = Image.new("RGBA", (SZ, SZ), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx = 256

    if simple:
        # Bigger, thicker mic, no grille; a single pair of waves.
        d.rounded_rectangle(box(cx - 78, 70, cx + 78, 300), radius=sc(78), fill=MIC)
        arc(d, cx, 226, 128, 20, 160, 34, MIC)
        d.rectangle(box(cx - 17, 350, cx + 17, 420), fill=MIC)
        d.rounded_rectangle(box(cx - 90, 408, cx + 90, 444), radius=sc(18), fill=MIC)
        for side in (-1, 1):
            start, end = (140, 220) if side < 0 else (-40, 40)
            arc(d, cx, 185, 205, start, end, 34, WAVE)
    else:
        # shadow
        shadow = Image.new("RGBA", (SZ, SZ), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(box(cx - 66, 92, cx + 74, 316), radius=sc(70),
                                                 fill=SHADOW)
        layer = Image.alpha_composite(layer, shadow)
        d = ImageDraw.Draw(layer)
        # capsule
        d.rounded_rectangle(box(cx - 70, 82, cx + 70, 306), radius=sc(70), fill=MIC)
        # grille: horizontal stripes clipped to the top part of the capsule
        grille = Image.new("L", (SZ, SZ), 0)
        gd = ImageDraw.Draw(grille)
        for y in range(118, 216, 22):
            gd.rounded_rectangle(box(cx - 44, y, cx + 44, y + 9), radius=sc(4.5), fill=255)
        layer.paste(Image.new("RGBA", (SZ, SZ), GRILLE + (255,)), (0, 0), grille)
        # center ring
        d.rectangle(box(cx - 70, 232, cx + 70, 246), fill=MIC_SHADE)
        # yoke, stand and base
        arc(d, cx, 216, 118, 12, 168, 24, MIC)
        d.rectangle(box(cx - 12, 334, cx + 12, 410), fill=MIC)
        d.rounded_rectangle(box(cx - 82, 404, cx + 82, 432), radius=sc(14), fill=MIC)
        # waves: two per side; the inner one yellow and the outer one translucent white
        for r, w, col in ((176, 22, WAVE + (255,)), (226, 16, (255, 255, 255, 150))):
            arc(d, cx, 196, r, 150, 210, w, col)
            arc(d, cx, 196, r, -30, 30, w, col)

    img = Image.alpha_composite(bg, layer)
    out = Image.new("RGBA", (SZ, SZ), (0, 0, 0, 0))
    out.paste(img, (0, 0), squircle_mask(130 if simple else 116))
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    full = draw(simple=False)
    small = draw(simple=True)

    png = full.resize((512, 512), Image.LANCZOS)
    png.save(ASSETS / "icon.png", optimize=True)

    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = [(small if s <= 32 else full).resize((s, s), Image.LANCZOS) for s in sizes]
    big = frames[-1]
    big.save(ASSETS / "icon.ico", format="ICO", sizes=[(s, s) for s in sizes],
             append_images=frames[:-1])
    # quick check: the .ico must contain every size
    with Image.open(ASSETS / "icon.ico") as ico:
        got = sorted(ico.info.get("sizes", set()))
    print(f"assets/icon.png (512 px) and assets/icon.ico ({', '.join(str(w) for w, _ in got)} px)")


if __name__ == "__main__":
    main()
