"""One pose, one look: the contact QA sheet, built from the real meshes.

    python tools/inspect/contact_sheet.py LOOK.vrm --pose sittingWide \\
        --garment "Red Bodycon Mini Dress" --garment "Beige Tailored Briefs" \\
        [--before OLD_LOOK.vrm] [--poses tests/fixtures/homepilot-poses.json] --out /tmp/qa

Rows of the sheet (``OUT/contact-sheet.png``), every panel posed with Pose Studio's own
quaternions:

* **A** the whole look, front, side and back;
* **B** each garment alone (body and other garments hidden): product view, wireframe, side;
* **C** each garment coloured by its clearance to the posed body (front and back three-quarter)
  and by edge stretch;
* **D** with ``--before``: each garment's clearance in the old file beside the new one, and
  the numbers.

``OUT/metrics.json`` holds the numbers the colours were made from (tools/inspect/pose_contact.py:
clearance, deepest point inside, share of vertices inside, stretch, and the bone carrying her
nearest skin where it is inside). The technical rows show garments only, never the body: the
measurements carry what a picture of the body would.

Colours: clearance blue clear, green contact (0-2 mm), yellow to red inside (red at 15 mm or
more); stretch white at rest length, yellow 1.5x, red 2.5x or more.

OUT must be outside the repository. The look files are copied there; nothing else is written.
Needs Node, Playwright and Chromium as tools/gallery does (PLAYWRIGHT_CHROMIUM,
GALLERY_CDN_ROUTE).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("pose_contact", ROOT / "tools/inspect/pose_contact.py")
pose_contact = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pose_contact)

SIZE = (360, 480)


def _outside(out: Path) -> Path:
    out = out.resolve()
    if out == ROOT or ROOT in out.parents:
        raise SystemExit(f"{out} is inside the repository; QA output is written outside it")
    return out


def _focus(height_m: float, garment: str) -> list[float] | None:
    """A frame round the garment: the whole look is framed by the page itself (None)."""
    return [round(0.30 * height_m, 3), round(0.80 * height_m, 3)] if garment else None


def build(
    look: Path, pose_name: str, garments: list[str], poses: Path, out: Path, before: Path | None
) -> Path:
    out = _outside(out)
    out.mkdir(parents=True, exist_ok=True)
    presets = {p["name"]: p for p in json.loads(poses.read_text())["presets"]}
    if pose_name not in presets:
        raise SystemExit(f"no pose {pose_name!r} in {poses}; known: {', '.join(presets)}")
    pose = presets[pose_name]
    (out / "look.vrm").write_bytes(look.read_bytes())
    height = 1.6  # VRoid scale; the focus band is a share of it, so a taller avatar still fits
    views, metrics, cells = [], {"pose": pose_name, "look": look.name, "garments": {}}, []

    def view(file: str, name: str, yaw: float, focus=None, present=None, light=None):
        entry = {
            "file": file,
            "out": name,
            "yaw": yaw,
            "size": list(SIZE),
            "focus": focus,
            "bones": pose["bones"],
        }
        if present:
            entry["present"] = present
        if light:
            entry["light"] = light
        views.append(entry)

    for yaw, label in ((0, "front"), (-60, "side"), (180, "back")):
        view("look.vrm", f"A-{label}.png", yaw)
    cells.append(("A  whole look", [(f"A-{x}.png", x) for x in ("front", "side", "back")]))

    for index, garment in enumerate(garments):
        tag = f"g{index}"
        alone = {"mode": "ghost", "product": [garment], "shading": "standard"}
        focus = _focus(height, garment)
        view("look.vrm", f"B-{tag}-product.png", -30, focus, alone, "studio")
        view("look.vrm", f"B-{tag}-wire.png", -30, focus, {**alone, "wireframe": True}, "studio")
        view("look.vrm", f"B-{tag}-side.png", -90, focus, alone, "studio")
        cells.append(
            (
                f"B  {garment} alone",
                [
                    (f"B-{tag}-product.png", "product"),
                    (f"B-{tag}-wire.png", "wireframe"),
                    (f"B-{tag}-side.png", "side"),
                ],
            )
        )
        found = pose_contact.coloured(look, pose, [garment], "clearance", out / f"{tag}-clr.vrm")
        pose_contact.coloured(look, pose, [garment], "stretch", out / f"{tag}-str.vrm")
        metrics["garments"][garment] = {"after": {k: v[pose_name] for k, v in found.items()}}
        colour = {"mode": "ghost", "product": [garment], "vertexColors": True}
        view(f"{tag}-clr.vrm", f"C-{tag}-clr-front.png", -30, focus, colour, "studio")
        view(f"{tag}-clr.vrm", f"C-{tag}-clr-back.png", 150, focus, colour, "studio")
        view(f"{tag}-str.vrm", f"C-{tag}-str.png", -30, focus, colour, "studio")
        cells.append(
            (
                f"C  {garment}: clearance / stretch",
                [
                    (f"C-{tag}-clr-front.png", "clearance, front 3/4"),
                    (f"C-{tag}-clr-back.png", "clearance, back 3/4"),
                    (f"C-{tag}-str.png", "stretch"),
                ],
            )
        )
        if before is not None:
            old = pose_contact.coloured(before, pose, [garment], "clearance", out / f"{tag}-before-clr.vrm")
            metrics["garments"][garment]["before"] = {k: v[pose_name] for k, v in old.items()}
            view(f"{tag}-before-clr.vrm", f"D-{tag}-before.png", -30, focus, colour, "studio")
            cells.append(
                (
                    f"D  {garment}: before / after",
                    [(f"D-{tag}-before.png", "BEFORE"), (f"C-{tag}-clr-front.png", "AFTER"), (None, garment)],
                )
            )

    (out / "views.json").write_text(json.dumps(views))
    subprocess.run(
        ["node", str(ROOT / "tools/gallery/views.mjs"), str(out)], check=True, cwd=ROOT, timeout=1800
    )
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1) + "\n")
    return _assemble(out, cells, metrics)


def _assemble(out: Path, cells, metrics: dict) -> Path:
    from PIL import Image, ImageDraw

    w, h = SIZE
    sheet = Image.new("RGB", (w * 3, 40 + len(cells) * (h + 40)), "white")
    draw = ImageDraw.Draw(sheet)
    draw.text(
        (8, 10),
        f"{metrics['look']} · pose {metrics['pose']} · clearance: blue clear, green contact, "
        "yellow->red inside (red >= 15 mm) · stretch: white 1.0x, yellow 1.5x, red >= 2.5x",
        fill="black",
    )
    y = 40
    for title, row in cells:
        draw.text((8, y), title, fill="black")
        y += 18
        for column, (name, label) in enumerate(row):
            if name and (out / name).is_file():
                sheet.paste(Image.open(out / name).convert("RGB").resize((w, h)), (column * w, y))
            elif name is None:
                lines = []
                for when, by in metrics["garments"][label].items():
                    for _material, m in by.items():
                        lines.append(
                            f"{when}: {m['penetratingPct']}% inside, deepest {m['maxPenetrationMm']} mm,"
                        )
                        lines.append(f"   stretch {m['maxEdgeStretch']}x; inside by {m['insideBy']}")
                for i, line in enumerate(lines):
                    draw.text((column * w + 8, y + 16 + i * 18), line[:54], fill="black")
            draw.text((column * w + 6, y + h + 2), label[:48], fill="black")
        y += h + 22
    path = out / "contact-sheet.png"
    sheet.save(path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("look", type=Path)
    parser.add_argument("--pose", default="sittingWide")
    parser.add_argument("--garment", action="append", required=True, help="a garment material name prefix")
    parser.add_argument("--poses", type=Path, default=ROOT / "tests/fixtures/homepilot-poses.json")
    parser.add_argument("--before", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(build(args.look, args.pose, args.garment, args.poses, args.out, args.before))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
