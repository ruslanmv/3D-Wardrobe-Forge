#!/usr/bin/env python3
"""AB1. Every After Dark · Bare look painted on Forge's synthetic reference body, in one sheet.

A look in ``assets/body_detail/bare_looks.json`` is a design (preset + state + extras); before a
new one ships, or after the painter changes, look at all of them side by side. This paints each
one exactly as the registry's thumbnail does (``body_previews.render_items``: the look's merged
spec, in the flat view of its state) and lays them out with their names, chapter by chapter.

    .venv/bin/python tools/body_surface/bare_looks_sheet.py --base <scratch>/ref-atlas.vrm \\
        --out <scratch>/bare-looks.png [--only creampie,glazed]

The reference body comes from ``tools/body_surface/detail_preview.py`` (about five minutes the
first time); never a library character. The sheet is explicit: write it to a scratch directory,
never into the repository. The flat view shows the fixture's sparse texels as stripes and black
wedges — that is the test body, not the paint (CLAUDE.md, Looking at results). About 15 minutes
for all 24.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base", type=Path, required=True, help="ref-atlas.vrm from detail_preview.py")
    parser.add_argument("--out", type=Path, required=True, help="Where to write the sheet (scratch only)")
    parser.add_argument("--only", help="Only looks whose id contains one of these (comma-separated)")
    parser.add_argument("--cols", type=int, default=6)
    parser.add_argument("--cell", type=int, default=180, help="Cell width in pixels")
    opts = parser.parse_args(argv)

    from PIL import Image, ImageDraw

    from wardrobe.registry import bare_looks, body_previews

    data = bare_looks.load()
    order = {c["id"]: n for n, c in enumerate(data["chapters"])}
    looks = sorted(data["looks"].items(), key=lambda kv: order.get(kv[1]["chapter"], 99))
    if opts.only:
        wanted = [w.strip() for w in opts.only.split(",") if w.strip()]
        looks = [(k, v) for k, v in looks if any(w in k for w in wanted)]
    if not looks:
        print("no looks matched", file=sys.stderr)
        return 1
    ids = [f"look:{k}" for k, _ in looks]
    images = body_previews.render_items(opts.base.read_bytes(), ids)
    tiles = [Image.open(io.BytesIO(images[i])).convert("RGB") for i in ids if i in images]
    if len(tiles) != len(ids):
        print(f"{len(ids) - len(tiles)} looks were not painted", file=sys.stderr)
    w, h = tiles[0].size
    scale = opts.cell / w
    cw, ch = opts.cell, int(h * scale)
    rows = (len(tiles) + opts.cols - 1) // opts.cols
    sheet = Image.new("RGB", (cw * opts.cols, (ch + 18) * rows), "white")
    draw = ImageDraw.Draw(sheet)
    for n, ((_, spec), tile) in enumerate(zip(looks, tiles, strict=False)):
        x, y = (n % opts.cols) * cw, (n // opts.cols) * (ch + 18)
        sheet.paste(tile.resize((cw, ch)), (x, y + 18))
        draw.text((x + 3, y + 3), spec["label"], fill="black")
    opts.out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(opts.out)
    print(f"{len(tiles)} looks → {opts.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
