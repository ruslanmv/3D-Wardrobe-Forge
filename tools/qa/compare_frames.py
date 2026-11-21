#!/usr/bin/env python3
"""BD29. Two or more runs of the same Step 5 frames, side by side, one row per frame.

The question after a painter change is always "what changed, from the same camera": this puts
each run's ``<position>-<state>.png`` next to the others' (cropped to her, labelled), so old,
first fix and second fix are judged in one image rather than three folders.

    .venv/bin/python tools/qa/compare_frames.py --out <scratch>/compare.png \\
        --run OLD=<dir> --run "BD24 rebuild=<dir>" --run BD27=<dir> \\
        --frames all-fours-doggy-bottle-anal,face-down-doggy-bottle-anal,bent-over-doggy-bottle-anal

Frames come from tools/qa/private-positions-live.mjs (via tools/qa/verify_pack.sh). Explicit
frames are never committed: write the sheet outside every repository.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--run", action="append", required=True, help="LABEL=directory of frames")
    parser.add_argument("--frames", required=True, help="Comma-separated frame names without .png")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--width", type=int, default=300, help="Pixels per frame")
    parser.add_argument("--crop", type=float, default=0.1, help="Share cut from each side (0 keeps all)")
    opts = parser.parse_args(argv)
    runs = [r.split("=", 1) for r in opts.run]
    rows = []
    for frame in opts.frames.split(","):
        files = [Path(d) / f"{frame}.png" for _, d in runs]
        if not all(f.exists() for f in files):
            print(
                f"skipped {frame}: missing in "
                + ", ".join(lab for (lab, _), f in zip(runs, files, strict=True) if not f.exists())
            )
            continue
        cells = []
        for f in files:
            im = Image.open(f).convert("RGB")
            c = opts.crop
            im = im.crop(
                (
                    int(im.width * c),
                    int(im.height * c * 1.2),
                    int(im.width * (1 - c)),
                    int(im.height * (1 - c * 1.2)),
                )
            )
            cells.append(im.resize((opts.width, int(im.height * opts.width / im.width))))
        h = max(c.height for c in cells)
        row = Image.new("RGB", (len(cells) * (opts.width + 10) + 10, h + 26), (20, 20, 24))
        ImageDraw.Draw(row).text(
            (6, 6), f"{frame}   " + "  |  ".join(lab for lab, _ in runs), fill=(230, 230, 230)
        )
        for k, c in enumerate(cells):
            row.paste(c, (10 + k * (opts.width + 10), 22))
        rows.append(row)
    if not rows:
        print("nothing to compare")
        return 1
    sheet = Image.new("RGB", (rows[0].width, sum(r.height for r in rows)), (20, 20, 24))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height
    opts.out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(opts.out)
    print(f"{len(rows)} rows: {opts.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
