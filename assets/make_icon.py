"""
assets/make_icon.py
--------------------
Generates the app icon from scratch (red rounded square, editorial-red
accent matching the in-app palette, white "求" glyph) and exports it as:

  assets/icon.png     (1024x1024 master)
  assets/icon.ico     (Windows, multi-resolution)
  assets/icon.icns    (macOS, hand-written — no `iconutil`/macOS needed,
                       so this script also works when generating the icon
                       on Linux/Windows)

Run once with:  python assets/make_icon.py
(Requires Pillow: pip install Pillow)
"""
from __future__ import annotations

import struct
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
ACCENT = (198, 40, 40)          # #c62828 — same red used as the UI accent
ACCENT_DARK = (154, 26, 26)
SIZE = 1024

_CJK_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]


def _load_font(size: int):
    for path in _CJK_FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _rounded_square(size: int, radius_ratio: float = 0.225) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = int(size * radius_ratio)

    # subtle vertical gradient for a bit of depth
    for y in range(size):
        t = y / size
        r = int(ACCENT[0] + (ACCENT_DARK[0] - ACCENT[0]) * t)
        g = int(ACCENT[1] + (ACCENT_DARK[1] - ACCENT[1]) * t)
        b = int(ACCENT[2] + (ACCENT_DARK[2] - ACCENT[2]) * t)
        draw.line([(0, y), (size, y)], fill=(r, g, b, 255))

    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=radius, fill=255)

    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def build_master_icon() -> Image.Image:
    img = _rounded_square(SIZE)
    draw = ImageDraw.Draw(img)

    # White "求" glyph, slightly raised, with a thin white baseline rule
    # underneath to read as an open book / magazine page at small sizes.
    font = _load_font(int(SIZE * 0.52))
    glyph = "求"
    bbox = draw.textbbox((0, 0), glyph, font=font)
    gw, gh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    gx = (SIZE - gw) / 2 - bbox[0]
    gy = (SIZE - gh) / 2 - bbox[1] - SIZE * 0.03
    draw.text((gx, gy), glyph, font=font, fill=(255, 255, 255, 255))

    rule_y = SIZE * 0.74
    draw.rounded_rectangle(
        [(SIZE * 0.30, rule_y), (SIZE * 0.70, rule_y + SIZE * 0.018)],
        radius=int(SIZE * 0.01),
        fill=(255, 255, 255, 230),
    )
    return img


def save_png(img: Image.Image):
    img.save(HERE / "icon.png")


def save_ico(img: Image.Image):
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save(HERE / "icon.ico", sizes=sizes)


# -- minimal, self-contained .icns writer (no macOS tools required) --------
_ICNS_TYPES = {
    16: b"icp4", 32: b"icp5", 64: b"icp6",
    128: b"ic07", 256: b"ic08", 512: b"ic09", 1024: b"ic10",
}


def save_icns(img: Image.Image):
    entries = []
    for px, tag in _ICNS_TYPES.items():
        resized = img.resize((px, px), Image.LANCZOS)
        buf = io.BytesIO()
        resized.save(buf, format="PNG")
        data = buf.getvalue()
        entries.append((tag, data))

    body = b"".join(struct.pack(">4sI", tag, len(data) + 8) + data for tag, data in entries)
    header = struct.pack(">4sI", b"icns", len(body) + 8)
    (HERE / "icon.icns").write_bytes(header + body)


if __name__ == "__main__":
    master = build_master_icon()
    save_png(master)
    save_ico(master)
    save_icns(master)
    print("Generated icon.png, icon.ico, icon.icns in", HERE)
