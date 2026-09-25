"""The README's Studio-on-a-phone picture, composed from the three screens ``studio.mjs`` captured.

    node tools/gallery/studio.mjs http://127.0.0.1:8080 OUT_DIR
    python tools/gallery/studio_sheet.py OUT_DIR [--sheet docs/images/studio-mobile.webp]

The screens are taken at device scale 2 so the text survives the WebP; here they
are brought back to the phone's own 414 x 896 and laid side by side on the
page's dark ground, in the order a user meets them: the wardrobe with the new
look in it, the designer, and the finished job with its fit report. Nothing is
drawn over them: every word in the picture is the Studio's.
"""

import argparse
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]

SCREENS = ("studio-wardrobe.png", "studio-design.png", "studio-report.png")
#: The phone's viewport in CSS pixels, which is the size each screen is shown at.
PHONE = (414, 896)
MARGIN, GAP = 28, 29
GROUND = (18, 15, 18)


def compose(shots: Path, target: Path) -> None:
    width = 2 * MARGIN + len(SCREENS) * PHONE[0] + (len(SCREENS) - 1) * GAP
    sheet = Image.new("RGB", (width, PHONE[1] + 2 * MARGIN), GROUND)
    for n, name in enumerate(SCREENS):
        screen = Image.open(shots / name).convert("RGB").resize(PHONE, Image.LANCZOS)
        sheet.paste(screen, (MARGIN + n * (PHONE[0] + GAP), MARGIN))
    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target, "WEBP", quality=88, method=6)
    print(target, sheet.size, target.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("shots", type=Path)
    parser.add_argument("--sheet", type=Path, default=ROOT / "docs" / "images" / "studio-mobile.webp")
    args = parser.parse_args()
    compose(args.shots.resolve(), args.sheet.resolve())
