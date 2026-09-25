"""The README's showcase images, from real-avatar gallery renders.

    python tools/gallery/showcase.py REAL_DIR [OUT_DIR]

REAL_DIR holds one render directory per avatar (``looks.py --avatar`` then
``render.mjs``), named after the VRM: AvatarSample_A, AvatarSample_B, ... OUT_DIR
defaults to docs/images. Writes:

* ``lookbook.webp`` — a strip of looks across the library avatars, front 3/4;
* ``before-after.webp`` — avatars as they arrive, then in two new outfits.

Nothing is retouched: every panel is a render of a VRM the pipeline produced,
cropped and scaled. Which looks appear is chosen below, by number, so the
selection is reviewable in a diff.
"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

#: (avatar directory, look number, caption) — the lookbook, left to right.
LOOKBOOK = [
    ("AvatarSample_A", 2, "bodycon mini dress"),
    ("AvatarSample_B", 10, "pleated skirt + halter"),
    ("fem_vroid", 6, "satin slip dress"),
    ("AvatarSample_A", 11, "skater dress + jacket"),
    ("AvatarSample_B", 8, "latex leggings + crop top"),
    ("AvatarSample_C", 1, "crop top + straight jeans"),
    ("fem_vroid", 3, "sequin mini dress"),
    ("AvatarSample_A", 9, "glossy catsuit"),
]

#: (avatar directory, [look numbers]) — before, then after.
BEFORE_AFTER = [("AvatarSample_A", [1, 12]), ("AvatarSample_B", [2, 7])]

BG, INK, MUTED = (30, 28, 34), (244, 237, 230), (169, 159, 154)
PANEL_H = 720


def font(name: str, size: int) -> ImageFont.ImageFont:
    for folder in ("/usr/share/fonts/truetype/dejavu", "/Library/Fonts", "C:/Windows/Fonts"):
        try:
            return ImageFont.truetype(f"{folder}/{name}", size)
        except OSError:
            continue
    return ImageFont.load_default()


SMALL = font("DejaVuSans.ttf", 18)
LABEL = font("DejaVuSans-Bold.ttf", 20)


def portrait(path: Path) -> Image.Image:
    """A render cropped to her figure, scaled to the panel height."""
    image = Image.open(path).convert("RGB")
    w, h = image.size
    image = image.crop((int(w * 0.22), int(h * 0.02), int(w * 0.78), int(h * 0.97)))
    return image.resize((int(image.width * PANEL_H / image.height), PANEL_H), Image.LANCZOS)


def strip(panels: list[tuple[Image.Image, str]], gap: int = 8, caption_h: int = 40) -> Image.Image:
    width = sum(p.width for p, _ in panels) + gap * (len(panels) + 1)
    sheet = Image.new("RGB", (width, PANEL_H + caption_h + gap), BG)
    draw = ImageDraw.Draw(sheet)
    x = gap
    for picture, caption in panels:
        sheet.paste(picture, (x, gap))
        text_w = draw.textlength(caption, font=SMALL)
        draw.text((x + (picture.width - text_w) / 2, PANEL_H + gap + 8), caption, font=SMALL, fill=MUTED)
        x += picture.width + gap
    return sheet


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    real = Path(sys.argv[1]).resolve()
    default = Path(__file__).resolve().parents[2] / "docs" / "images"
    out = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else default
    out.mkdir(parents=True, exist_ok=True)

    looks = [(portrait(real / avatar / f"r-{n:02d}-34.png"), caption) for avatar, n, caption in LOOKBOOK]
    strip(looks).save(out / "lookbook.webp", "WEBP", quality=86, method=6)

    rows = []
    for avatar, numbers in BEFORE_AFTER:
        titles = {r["number"]: r["title"] for r in json.loads((real / avatar / "g-records.json").read_text())}
        panels = [(portrait(real / avatar / "r-source-dressed-34.png"), "as she arrives")]
        panels += [(portrait(real / avatar / f"r-{n:02d}-34.png"), titles[n].lower()) for n in numbers]
        rows.append(strip(panels))
    width = max(r.width for r in rows)
    sheet = Image.new("RGB", (width, sum(r.height for r in rows)), BG)
    y = 0
    for row in rows:
        sheet.paste(row, ((width - row.width) // 2, y))
        y += row.height
    sheet.save(out / "before-after.webp", "WEBP", quality=86, method=6)
    for name in ("lookbook.webp", "before-after.webp"):
        print(name, (out / name).stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
