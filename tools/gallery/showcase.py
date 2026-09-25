"""The README's showcase images, from real-avatar gallery renders.

    python tools/gallery/showcase.py REAL_DIR [OUT_DIR]

REAL_DIR holds one render directory per avatar (``looks.py --avatar`` then
``render.mjs``), named after the VRM: AvatarSample_A, AvatarSample_B, ... OUT_DIR
defaults to docs/images. Writes:

* ``lookbook.webp`` — a strip of looks across the library avatars, front 3/4;
* ``before-after.webp`` — avatars as they arrive, then in two new outfits;
* ``features.webp`` — the feature map: one card per feature, with a render where
  the feature can be seen and plain text where it is a property;
* ``hosiery.webp`` — the hosiery golden previews (tools/gallery/hosiery.py), on the
  calibration mannequin the repository declares adult.

``--hosiery`` writes hosiery.webp and redraws only the hosiery card of an existing
features.webp, so the gallery need not be re-rendered for it.

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


#: The feature map, row by row: (title, lines, picture). A picture is ("render",
#: avatar, look), ("pair", avatar, look) for source then look, ("image", path),
#: ("sketch", name) for a drawn diagram, or None for a text-only card.
FEATURES = [
    ("Words in, VRM out", ["A plain-language request becomes", "a validated VRM in one job."],
     ("render", "AvatarSample_A", 2)),
    ("58-garment library", ["Procedural templates, generated at", "each avatar's own measurements."],
     ("render", "AvatarSample_B", 10)),
    ("Toon-true materials", ["6 finishes, 7 patterns and a sheer", "scale, all readable under MToon."],
     ("render", "fem_vroid", 3)),
    ("Layered outfits", ["Inner first, each layer clearing", "the ones beneath it, in one VRM."],
     ("render", "AvatarSample_A", 11)),
    ("Base Body Prep", ["Her own clothes come off only where", "an authored body is underneath."],
     ("pair", "AvatarSample_B", 2)),
    ("Measured fit", ["Legs, arms, crotch, armpit and", "shoulders measured from her mesh."],
     ("render", "AvatarSample_C", 1)),
    ("Wardrobe Studio", ["Design, check the plan, compare", "and export, on desktop or phone."],
     ("image", "docs/images/studio-layers.webp")),
    ("Validated output",
     ["\u2713 humanoid \u2713 weights \u2713 skeleton \u2713 expressions \u2713 clearance,",
      "re-checked from the output bytes."],
     None),
    ("Licensing and safety",
     ["Model terms checked first. Intimate", "garments need an operator's adult",
      "declaration; prompts cannot grant it."],
     None),
    ("Static-bundle export", ["One call packs a wardrobe that", "3D-Avatar-Chatbot loads by unzipping."],
     None),
    ("Runs on plain Python", ["Native engine: Python and numpy.", "Blender optional. 623 tests in CI."],
     None),
    ("Hosiery & suspenders",
     ["Straps clipped to the fitted stocking tops, tension checked walking and seated, "
      "a hem solved for the reveal. Gated; shown on the adult mannequin."],
     ("golden", "assets/gallery/hosiery/hosiery_garter_statement_front-detail.webp")),
]

CARD_W, CARD_H, THUMB_W = 520, 250, 170
ACCENT, CARD, LINE = (232, 185, 164), (42, 39, 48), (70, 66, 76)


def _thumb(real: Path, root: Path, picture) -> Image.Image | None:
    if picture is None:
        return None
    kind = picture[0]
    if kind == "render":
        image = portrait(real / picture[1] / f"r-{picture[2]:02d}-34.png")
    elif kind == "pair":
        a = portrait(real / picture[1] / "r-source-dressed-34.png")
        b = portrait(real / picture[1] / f"r-{picture[2]:02d}-34.png")
        image = Image.new("RGB", (a.width + b.width, PANEL_H), BG)
        image.paste(a, (0, 0))
        image.paste(b, (a.width, 0))
    elif kind == "golden":  # a hosiery golden preview: shown whole
        image = Image.open(root / picture[1]).convert("RGB")
    elif kind == "image":
        image = Image.open(root / picture[1]).convert("RGB")
        w, h = image.size  # the viewport: her in two outfits, not the panels round it
        image = image.crop((int(w * 0.18), int(h * 0.1), int(w * 0.68), int(h * 0.9)))
    else:
        return _sketch_hosiery()
    scale = min(THUMB_W / image.width, (CARD_H - 24) / image.height)
    return image.resize((max(int(image.width * scale), 1), max(int(image.height * scale), 1)), Image.LANCZOS)


def _sketch_hosiery() -> Image.Image:
    """A labelled line diagram of the hosiery layers: a schematic, not a render."""
    w, h = THUMB_W, CARD_H - 24
    sketch = Image.new("RGB", (w, h), CARD)
    d = ImageDraw.Draw(sketch)
    cx = w // 2 + 30  # the drawing on the right, its labels in a column on the left
    d.rectangle((cx - 40, 30, cx + 40, 40), outline=ACCENT, width=2)                  # belt
    for x in range(cx - 48, cx + 48, 8):
        d.line((x, 84, x + 4, 84), fill=MUTED, width=1)                               # hem
    for side in (-1, 1):
        x0 = cx + side * 20
        d.polygon([(x0 - 14, 118), (x0 + 14, 118), (x0 + 9, h - 8), (x0 - 9, h - 8)], outline=INK)
        d.rectangle((x0 - 14, 118, x0 + 14, 130), fill=(20, 19, 23), outline=INK)     # band
        d.line((cx + side * 24, 40, x0, 116), fill=ACCENT, width=3)                   # strap
        d.ellipse((x0 - 4, 112, x0 + 4, 120), fill=(199, 201, 204))                   # clip
    for label, y, colour in (("belt", 28, ACCENT), ("hem", 77, MUTED), ("clips", 106, INK),
                             ("band", 124, INK), ("stocking", 170, INK)):
        d.text((2, y), label, font=TINY, fill=colour)
    return sketch

TINY = font("DejaVuSans.ttf", 13)
TITLE = font("DejaVuSans-Bold.ttf", 23)
BODY_TEXT = font("DejaVuSans.ttf", 17)
HEAD = font("DejaVuSans-Bold.ttf", 34)


def _wrap(text: str, width: int) -> list[str]:
    """Break ``text`` at spaces so each line fits ``width`` pixels in the body font."""
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and BODY_TEXT.getlength(trial) > width:
            lines.append(line)
            trial = word
        line = trial
    return lines + [line]


def _card(sheet: Image.Image, d: ImageDraw.ImageDraw, i: int, thumb: Image.Image | None) -> None:
    """Card ``i`` of the feature map, drawn in place."""
    cols, gap, top = 3, 16, 96
    title, lines, _picture = FEATURES[i]
    x = gap + (i % cols) * (CARD_W + gap)
    y = top + (i // cols) * (CARD_H + gap)
    designed = title.startswith("Designed")
    d.rectangle((x - 2, y - 2, x + CARD_W + 2, y + CARD_H + 2), fill=BG)
    d.rounded_rectangle((x, y, x + CARD_W, y + CARD_H), radius=14, fill=CARD,
                        outline=ACCENT if designed else LINE, width=2 if designed else 1)
    text_x = x + 20
    if thumb is not None:
        sheet.paste(thumb, (x + CARD_W - thumb.width - 12, y + (CARD_H - thumb.height) // 2))
    if designed:
        d.text((text_x, y + 18), "DESIGNED \u00b7 NOT YET BUILT", font=TINY, fill=ACCENT)
    name = title.replace("Designed next: ", "")
    d.text((text_x, y + 40), name, font=TITLE, fill=ACCENT if designed else INK)
    room = CARD_W - 40 - (thumb.width + 20 if thumb is not None else 0)
    for k, line in enumerate(_wrap(" ".join(lines), room)):
        d.text((text_x, y + 84 + k * 26), line, font=BODY_TEXT, fill=MUTED)


def patch_card(path: Path, index: int, *, keep_picture: bool = False) -> None:
    """Redraw one card of an existing feature map: what changed, without re-rendering the gallery.

    ``keep_picture`` reuses the picture already on the card (a render from the real
    gallery, which is not kept in the repository) and redraws only its words.
    """
    root = Path(__file__).resolve().parents[2]
    sheet = Image.open(path).convert("RGB")
    if keep_picture:
        cols, gap, top = 3, 16, 96
        x = gap + (index % cols) * (CARD_W + gap)
        y = top + (index // cols) * (CARD_H + gap)
        thumb = None
        if FEATURES[index][2] is not None:
            box = sheet.crop((x + CARD_W - THUMB_W - 12, y + 12, x + CARD_W - 12, y + CARD_H - 12))
            # The picture alone: from the right, the columns that are not card, up to the first
            # column of plain card (what lies left of it is the card's old words).
            import numpy as np

            pixels = np.asarray(box, dtype=np.int16)
            # A render's own background is a shade off the card's, so the threshold is tight.
            differs = np.abs(pixels - np.array(CARD)).max(axis=2) > 3
            filled = differs.sum(axis=0) > 2
            columns = np.nonzero(filled)[0]
            if columns.size:
                right = int(columns[-1])
                left = right
                while left > 0 and filled[left - 1]:
                    left -= 1
                rows = np.nonzero(differs[:, left:right + 1].sum(axis=1) > 2)[0]
                thumb = box.crop((left, int(rows[0]), right + 1, int(rows[-1]) + 1))
    else:
        thumb = _thumb(Path("."), root, FEATURES[index][2])
    _card(sheet, ImageDraw.Draw(sheet), index, thumb)
    sheet.save(path, "WEBP", quality=88, method=6)


#: The hosiery showcase: (golden image, caption), left to right.
HOSIERY = [
    ("hosiery_garter_glimpse_front.webp", "glimpse \u00b7 standing: covered"),
    ("hosiery_garter_glimpse_seated.webp", "glimpse \u00b7 seated: the tops show"),
    ("hosiery_garter_statement_front.webp", "statement \u00b7 below the hem"),
    ("hosiery_garter_seamed_back.webp", "seamed \u00b7 six straps"),
    ("hosiery_garter_fishnet_front.webp", "fishnet"),
]
HOSIERY_DETAILS = [
    ("hosiery_garter_statement_front-detail.webp", "flat straps, silver clasps, wide tops, rolled edge"),
    ("hosiery_garter_glimpse_front-detail.webp", "seated close-up: the glimpse"),
]


def hosiery(out: Path) -> None:
    """docs/images/hosiery.webp: the reference look standing, seated and close up, and its variants."""
    golden = Path(__file__).resolve().parents[2] / "assets" / "gallery" / "hosiery"
    panels = []
    for name, caption in HOSIERY:
        image = Image.open(golden / name).convert("RGB")
        w, h = image.size
        image = image.crop((int(w * 0.18), int(h * 0.06), int(w * 0.82), int(h * 0.94)))
        size = (int(image.width * PANEL_H / image.height), PANEL_H)
        panels.append((image.resize(size, Image.LANCZOS), caption))
    top = strip(panels)
    details = []
    for name, caption in HOSIERY_DETAILS:
        image = Image.open(golden / name).convert("RGB")
        width = (top.width - 24) // 2
        size = (width, int(image.height * width / image.width))
        details.append((image.resize(size, Image.LANCZOS), caption))
    row_h = max(i.height for i, _ in details) + 48
    sheet = Image.new("RGB", (top.width, top.height + row_h), BG)
    sheet.paste(top, (0, 0))
    d = ImageDraw.Draw(sheet)
    x = 8
    for image, caption in details:
        sheet.paste(image, (x, top.height))
        text_w = d.textlength(caption, font=SMALL)
        d.text((x + (image.width - text_w) / 2, top.height + image.height + 10), caption, font=SMALL,
               fill=MUTED)
        x += image.width + 8
    sheet.save(out / "hosiery.webp", "WEBP", quality=86, method=6)


def features(real: Path, out: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    cols, gap, top = 3, 16, 96
    rows = (len(FEATURES) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * CARD_W + (cols + 1) * gap, top + rows * (CARD_H + gap) + gap), BG)
    d = ImageDraw.Draw(sheet)
    d.text((gap + 4, 22), "3D Wardrobe Forge", font=HEAD, fill=INK)
    d.text((gap + 4 + d.textlength("3D Wardrobe Forge", font=HEAD) + 18, 36),
           "what it does, on real VRoid avatars", font=BODY_TEXT, fill=MUTED)
    for i in range(len(FEATURES)):
        _card(sheet, d, i, _thumb(real, root, FEATURES[i][2]))
    sheet.save(out / "features.webp", "WEBP", quality=88, method=6)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    if sys.argv[1] == "--hosiery":
        out = Path(__file__).resolve().parents[2] / "docs" / "images"
        hosiery(out)
        patch_card(out / "features.webp", len(FEATURES) - 1)
        for index, (title, _lines, _picture) in enumerate(FEATURES):  # the counts hosiery changed
            if title.startswith(("58-garment", "Runs on plain Python")):
                patch_card(out / "features.webp", index, keep_picture=True)
        for name in ("hosiery.webp", "features.webp"):
            print(name, (out / name).stat().st_size // 1024, "KB")
        return
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
    features(real, out)
    hosiery(out)
    for name in ("lookbook.webp", "before-after.webp", "features.webp", "hosiery.webp"):
        print(name, (out / name).stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
