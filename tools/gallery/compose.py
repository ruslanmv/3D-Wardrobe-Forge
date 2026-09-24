"""Compose each look's renders and its checks into one captioned image.

    python tools/gallery/compose.py OUT_DIR [GALLERY_DIR]

GALLERY_DIR defaults to assets/gallery. Captions are the plan and the fit report
from g-records.json — what the pipeline decided, not a description written after
looking at the picture. A caption that disagrees with its image is a finding.
"""

import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PANEL_W = 420
GAP = 16
BG, INK, MUTED, ACCENT = (38, 35, 42), (244, 237, 230), (169, 159, 154), (232, 185, 164)


def font(name: str, size: int) -> ImageFont.ImageFont:
    for folder in ("/usr/share/fonts/truetype/dejavu", "/Library/Fonts", "C:/Windows/Fonts"):
        try:
            return ImageFont.truetype(f"{folder}/{name}", size)
        except OSError:
            continue
    return ImageFont.load_default()


BOLD = font("DejaVuSans-Bold.ttf", 26)
BODY = font("DejaVuSans.ttf", 17)
SMALL = font("DejaVuSans.ttf", 15)


def panel(path: Path) -> Image.Image:
    """One render, cropped to her figure and scaled to the panel width."""
    image = Image.open(path).convert("RGB")
    w, h = image.size
    image = image.crop((int(w * 0.14), int(h * 0.05), int(w * 0.86), int(h * 0.96)))
    return image.resize((PANEL_W, int(PANEL_W * image.height / image.width)), Image.LANCZOS)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def describe(garment: dict) -> str:
    """The resolved material and style of one garment, as the plan recorded them."""
    parts = [garment["finish"]]
    if garment["pattern"] != "none":
        parts.append(garment["pattern"])
    opacity = f" {garment['opacity']:g}" if garment["opacity"] < 1 else ""
    parts.append(garment["alpha"].upper() + opacity)
    if garment["lined"]:
        parts.append("lined")
    if garment["coverage"] != "standard":
        parts.append(garment["coverage"])
    for key in ("neckline", "straps", "legCut", "rise"):
        if garment[key]:
            parts.append(f"{key} {garment[key]}")
    return " · ".join(parts)


def wrap(text: str, width: int) -> list[str]:
    """Break ``text`` at spaces so each line fits ``width`` pixels in the body font."""
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and BODY.getlength(trial) > width:
            lines.append(line)
            trial = word
        line = trial
    return lines + [line]


def compose(renders: Path, number: int, record: dict) -> Image.Image:
    panels = [panel(renders / f"r-{number:02d}-34.png"), panel(renders / f"r-{number:02d}-front.png")]
    labels = ["front 3/4 · A-pose", "front · A-pose"]
    if record.get("dressed"):
        panels.insert(0, panel(renders / "r-source-dressed-front.png"))
        labels.insert(0, "source: wearing a top and trousers")

    height = max(p.height for p in panels)
    width = PANEL_W * len(panels) + GAP * (len(panels) + 1)
    prompt = wrap(f"“{record['prompt']}”", width - 2 * GAP)
    caption = 64 + 26 * (len(record["garments"]) + len(prompt) + 2)
    image = Image.new("RGB", (width, height + caption + 2 * GAP), BG)
    draw = ImageDraw.Draw(image)
    for i, (picture, label) in enumerate(zip(panels, labels, strict=True)):
        x = GAP + i * (PANEL_W + GAP)
        image.paste(picture, (x, GAP))
        draw.text((x + 8, GAP + 6), label, font=SMALL, fill=MUTED)

    y = height + 2 * GAP
    adult = any(g["adult"] for g in record["garments"])
    title = f"#{number}  {record['title']}" + ("   [18+ gated]" if adult else "")
    draw.text((GAP, y), title, font=BOLD, fill=ACCENT if adult else INK)
    y += 38
    for line in prompt:
        draw.text((GAP, y), line, font=BODY, fill=MUTED)
        y += 26
    y += 2
    for g in record["garments"]:
        draw.text((GAP, y), f"L{g['layer']} {g['name']}  —  {describe(g)}", font=BODY, fill=INK)
        y += 26
    removed = ", ".join(record["removed"]) or "none"
    verdict = "passed" if record["passed"] else "NEEDS WORK"
    summary = f"fit {verdict} · clearance {record['clipping']} · her own clothes removed: {removed}"
    draw.text((GAP, y), summary, font=BODY, fill=MUTED)
    return image


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    renders = Path(sys.argv[1]).resolve()
    default = Path(__file__).resolve().parents[2] / "assets" / "gallery"
    gallery = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else default
    gallery.mkdir(parents=True, exist_ok=True)

    records = json.loads((renders / "g-records.json").read_text())
    index = []
    for record in sorted(records, key=lambda r: r["number"]):
        if not record.get("garments"):
            print(f"#{record['number']} has no look ({record.get('error')}); skipped")
            continue
        number = record["number"]
        name = f"{number:02d}-{slug(record['title'])}.webp"
        compose(renders, number, record).save(gallery / name, "WEBP", quality=84, method=6)
        index.append({"number": number, "image": name, **record})
    (gallery / "gallery.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n")
    size = sum((gallery / entry["image"]).stat().st_size for entry in index) // 1024
    print(f"{len(index)} images, {size} KB -> {gallery}")


if __name__ == "__main__":
    main()
