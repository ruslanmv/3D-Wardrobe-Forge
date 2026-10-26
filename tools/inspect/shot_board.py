"""Assemble homepilot_shots.mjs folders into one comparison board.

    python tools/inspect/shot_board.py OUT.png --title "Sitting (Wide) · front" \\
        --column "Before=/tmp/shots-before" --column "After=/tmp/shots-after" \\
        --row sittingWide-front --row sittingWide-side [--scale 0.6]

One column per folder (a look), one row per shot name (``<pose>-<view>``, as the shots tool
names them). Or one look in every pose and view, a row per pose and a column per view:

    python tools/inspect/shot_board.py OUT.png --grid /tmp/shots \
        --poses standing,sittingWide,sittingDesk,sittingCrossed --views front,threequarter,side,back
 Each row is cropped to what is drawn in any of its columns, plus a margin, so the
looks in a row are the same size and at the same place: a difference between them is the look's,
not the crop's. A shot missing from a folder is left blank and says so.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BACKGROUND = (0xD9, 0xDD, 0xE3)  # what homepilot_shots.mjs paints behind the avatar
INK, MUTED, BOARD = (236, 236, 236), (170, 176, 186), (22, 24, 28)
COLOURS = [(214, 104, 92), (98, 190, 132), (220, 180, 90), (110, 160, 230)]


def font(size: int, bold: bool = False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{name}", size)
    except OSError:
        return ImageFont.load_default()


def drawn_box(image: Image.Image) -> tuple[int, int, int, int] | None:
    """The box of what differs from the background, ignoring the viewer's frame and status chip."""
    a = np.asarray(image.convert("RGB")).astype(int)
    mask = np.abs(a - BACKGROUND).sum(axis=2) > 40
    h, w = mask.shape
    mask[: int(h * 0.09)] = False  # the viewer's corner marks
    mask[int(h * 0.9):] = False  # its READY chip
    mask[:, : int(w * 0.06)] = False
    mask[:, int(w * 0.94):] = False
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("out", type=Path)
    parser.add_argument("--title", default="")
    parser.add_argument("--column", action="append", default=[], help="LABEL=FOLDER")
    parser.add_argument("--row", action="append", default=[], help="a shot name: <pose>-<view>")
    parser.add_argument("--grid", type=Path, help="one folder: a row per pose, a column per view")
    parser.add_argument("--poses", default="standing,sittingWide,sittingDesk,sittingCrossed")
    parser.add_argument("--views", default="front,threequarter,side,back")
    parser.add_argument("--scale", type=float, default=0.6)
    parser.add_argument("--margin", type=int, default=40)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    if args.out.resolve().is_relative_to(root):
        parser.error(f"OUT must be outside the repository ({root}): no board can be committed by accident")
    if args.grid:
        # A column per view: the same folder, each column reading its own view of the row's pose.
        columns = [(view, args.grid, view) for view in args.views.split(",")]
        names = args.poses.split(",")
    else:
        if not args.column or not args.row:
            parser.error("give --column and --row, or --grid")
        columns = [(c.split("=", 1)[0], Path(c.split("=", 1)[1]), None) for c in args.column]
        names = args.row

    def path_of(folder: Path, name: str, view: str | None) -> Path:
        return folder / (f"{name}-{view}.png" if view else f"{name}.png")

    rows = []
    for name in names:
        paths = [path_of(folder, name, view) for _, folder, view in columns]
        images = [Image.open(p).convert("RGB") if p.exists() else None for p in paths]
        boxes = [drawn_box(i) for i in images if i is not None]
        boxes = [b for b in boxes if b]
        if boxes:
            m = args.margin
            box = (min(b[0] for b in boxes) - m, min(b[1] for b in boxes) - m,
                   max(b[2] for b in boxes) + m, max(b[3] for b in boxes) + m)
        else:
            box = (0, 0, 400, 400)
        size = (int((box[2] - box[0]) * args.scale), int((box[3] - box[1]) * args.scale))
        cells = []
        for image in images:
            if image is None:
                cell = Image.new("RGB", size, BACKGROUND)
                ImageDraw.Draw(cell).text((12, 12), "no shot", font=font(14), fill=(120, 120, 120))
            else:
                cell = image.crop(box).resize(size)
            cells.append(cell)
        rows.append((name, size, cells))

    pad, top, label = 16, 96 if args.title else 60, 30
    width = max(pad + len(columns) * (size[0] + pad) for _, size, _ in rows)
    height = top + sum(label + size[1] for _, size, _ in rows) + pad
    board = Image.new("RGB", (width, height), BOARD)
    draw = ImageDraw.Draw(board)
    if args.title:
        draw.text((pad, 14), args.title, font=font(20, True), fill=INK)
    col_w = rows[0][1][0]
    for k, (name, _, _) in enumerate(columns):
        colour = COLOURS[k % len(COLOURS)]
        draw.text((pad + k * (col_w + pad), top - 36), name, font=font(15, True), fill=colour)
    y = top
    for name, size, cells in rows:
        draw.text((pad, y + 6), name, font=font(14), fill=MUTED)
        y += label
        for k, cell in enumerate(cells):
            board.paste(cell, (pad + k * (size[0] + pad), y))
        y += size[1]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    board.save(args.out)
    print(f"{args.out} {board.size[0]}x{board.size[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
