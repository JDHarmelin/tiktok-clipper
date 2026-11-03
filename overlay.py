"""Socials overlay for stream clips.

Draws a transparent 1080x1920 PNG with a row of platform icons and the
streamer's handle in the top band, plus your own handle (optional) in the
bottom band. ffmpeg lays it over the clip. Icons are simple drawn badges,
so no logo files are needed.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config import OUTPUT_HEIGHT, OUTPUT_WIDTH

SOCIALS = ("twitch", "kick", "youtube", "instagram", "tiktok", "x")
_BOLD_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",   # macOS
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/opentype/inter/Inter-Black.otf",      # Linux
    "/usr/share/fonts/opentype/inter/Inter-Bold.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/ariblk.ttf",
]
_SYMBOL_FONTS = [
    "/System/Library/Fonts/Apple Symbols.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/seguisym.ttf",
]


def _font(size: int, candidates=_BOLD_FONTS) -> ImageFont.FreeTypeFont:
    for f in candidates:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default(size)


def _icon(name: str, s: int) -> Image.Image:
    """One rounded-square platform badge, s x s pixels."""
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = s // 4
    box = (0, 0, s - 1, s - 1)
    white = (255, 255, 255, 255)

    if name == "instagram":
        # Orange to purple diagonal gradient, masked to a rounded square
        grad = Image.new("RGBA", (s, s))
        gp = grad.load()
        for y in range(s):
            for x in range(s):
                t = (x + (s - y)) / (2 * s)
                gp[x, y] = (int(254 - 120 * t), int(200 - 190 * t), int(80 + 120 * t), 255)
        mask = Image.new("L", (s, s), 0)
        ImageDraw.Draw(mask).rounded_rectangle(box, r, fill=255)
        img.paste(grad, (0, 0), mask)
        w = max(3, s // 14)
        m = s // 5
        d.rounded_rectangle((m, m, s - m, s - m), s // 6, outline=white, width=w)
        c = s // 2
        cr = s // 6
        d.ellipse((c - cr, c - cr, c + cr, c + cr), outline=white, width=w)
        d.ellipse((s - m - s // 7, m + s // 14, s - m - s // 14, m + s // 7), fill=white)
        return img

    bg = {
        "twitch": (145, 70, 255, 255),
        "kick": (83, 252, 24, 255),
        "youtube": (255, 0, 0, 255),
        "tiktok": (0, 0, 0, 255),
        "x": (0, 0, 0, 255),
    }.get(name, (60, 60, 60, 255))
    d.rounded_rectangle(box, r, fill=bg, outline=(255, 255, 255, 90) if bg[:3] == (0, 0, 0) else None,
                        width=max(2, s // 30))

    if name == "youtube":
        tri = [(s * 0.38, s * 0.28), (s * 0.38, s * 0.72), (s * 0.74, s * 0.5)]
        d.polygon(tri, fill=white)
    elif name == "twitch":
        # Speech bubble with two bars
        l, t, rr, b = s * 0.24, s * 0.2, s * 0.78, s * 0.66
        d.polygon([(l, t), (rr, t), (rr, b - s * 0.1), (rr - s * 0.12, b), (l + s * 0.22, b),
                   (l + s * 0.1, b + s * 0.13), (l + s * 0.1, b), (l, b)], fill=white)
        bw, bh = s * 0.07, s * 0.18
        for bx in (s * 0.44, s * 0.6):
            d.rectangle((bx, s * 0.32, bx + bw, s * 0.32 + bh), fill=bg)
    elif name in ("kick", "x"):
        letter = "K" if name == "kick" else "X"
        f = _font(int(s * 0.62))
        colour = (0, 0, 0, 255) if name == "kick" else white
        d.text((s / 2, s / 2), letter, font=f, fill=colour, anchor="mm")
    elif name == "tiktok":
        f = _font(int(s * 0.62), _SYMBOL_FONTS)
        c = (s / 2, s / 2)
        d.text((c[0] - s * 0.03, c[1] - s * 0.02), "\u266a", font=f, fill=(37, 244, 238, 255), anchor="mm")
        d.text((c[0] + s * 0.03, c[1] + s * 0.02), "\u266a", font=f, fill=(254, 44, 85, 255), anchor="mm")
        d.text(c, "\u266a", font=f, fill=white, anchor="mm")
    return img


def _shadow_text(d: ImageDraw.ImageDraw, xy, text, font, anchor="mm", stroke=6):
    d.text(xy, text, font=font, fill=(255, 255, 255, 255), anchor=anchor,
           stroke_width=stroke, stroke_fill=(0, 0, 0, 255))


def socials_overlay(
    out_path: Path,
    handle: str,
    socials: list[str],
    band_top: int,
    band_bottom: int,
    our_handle: str = "",
    bottom_band_top: int | None = None,
) -> Path:
    """Write the overlay PNG and return its path.

    The icon row and handle are centred in the band from band_top to
    band_bottom. our_handle, if set, is centred in the band below the clip.
    """
    W, H = OUTPUT_WIDTH, OUTPUT_HEIGHT
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    icons = [n for n in socials if n in SOCIALS] or ["twitch"]
    size, gap = 92, 22
    row_w = len(icons) * size + (len(icons) - 1) * gap
    name_font = _font(84)
    name = handle.lstrip("@").upper()
    while d.textlength(name, font=name_font) > W - 80 and name_font.size > 40:
        name_font = _font(name_font.size - 4)

    block_h = size + 24 + name_font.size
    top = band_top + (band_bottom - band_top - block_h) // 2
    x = (W - row_w) // 2
    for n in icons:
        ic = _icon(n, size)
        img.alpha_composite(ic, (x, top))
        x += size + gap
    _shadow_text(d, (W / 2, top + size + 24 + name_font.size / 2), name, name_font)

    if our_handle and bottom_band_top is not None:
        f = _font(52)
        y = bottom_band_top + (H - bottom_band_top) * 0.42
        _shadow_text(d, (W / 2, y), "@" + our_handle.lstrip("@"), f, stroke=4)

    out_path = Path(out_path)
    img.save(out_path)
    return out_path
