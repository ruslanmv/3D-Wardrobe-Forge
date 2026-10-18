"""SA4. Pictures and numbers of the reference bodies, for checking the anatomy and for later work on it.

    python tools/anatomy/render_reference.py OUT_DIR [--vrm-dir DIR | --from-commit REV]
        [--sizes ref-f-median ...] [--sheets sizes,shoulders,poses] [--metrics]
        [--compare BEFORE_OUT_DIR] [--label TEXT]

A before/after of a change to the bodies, the rig or the correctives, in two commands:

    python tools/anatomy/render_reference.py /tmp/before --from-commit main --metrics --label main
    python tools/anatomy/render_reference.py /tmp/after --metrics --compare /tmp/before --label this

Renders with the Studio's own viewer (three.js + three-vrm in headless Chromium, through
``tools/gallery/views.mjs``), so a picture is what the Studio shows: the same page, lights and
relaxed pose as ``docs/images/anatomy/reference-sizes.jpg``. Needs what the gallery needs — Node,
Playwright, a Chromium, and cdn.jsdelivr.net (``GALLERY_CDN_ROUTE`` for a proxied sandbox).

What it writes into OUT_DIR:

* ``reference-sizes.png`` — every size front, 3/4, side and back in the relaxed pose (the sheet
  the shoulder defect was first seen on);
* ``shoulders-<size>.png`` — both shoulders close from the front, the back and each side in the
  relaxed pose, and under each armpit with the arm raised sideways;
* ``poses-<size>.png`` — the test poses (``wardrobe.anatomy.rig.TEST_POSES``) from the front and
  from behind;
* ``metrics.json`` (``--metrics``) — ``wardrobe.anatomy.posecheck`` for every size and test pose,
  measured on the VRMs that were rendered, read back from the files;
* ``compare-<name>.png`` (``--compare``) — each sheet beside the same sheet in another OUT_DIR,
  left the other, right this one: a before/after at identical cameras and poses.

``--vrm-dir`` renders VRMs already built (``<size>.vrm``) instead of building them from this
checkout; ``--from-commit`` builds them from another revision, in a temporary git worktree that is
removed afterwards. Either way the pictures and the metrics are of the files, read back as a viewer
reads them. The views are fixed in code here so two runs are comparable.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from wardrobe.anatomy import correctives as CR  # noqa: E402
from wardrobe.anatomy import reference as R  # noqa: E402
from wardrobe.anatomy import rig  # noqa: E402
from wardrobe.anatomy.posecheck import ShoulderRegion, read_correctives, read_vrm  # noqa: E402

VIEWS_SCRIPT = ROOT / "tools" / "gallery" / "views.mjs"
SIZES = ("ref-f-median", "ref-f-petite", "ref-f-full", "ref-f-tall")
#: Full-figure views: (label, yaw). The columns of the original sheet.
FIGURE = (("front", 0), ("three-quarter", 35), ("side", 90), ("back", 180))
FIGURE_PX = (600, 945)
CLOSE_PX = (900, 640)
SIDE_PX = (640, 640)
POSE_PX = (520, 820)
BACKGROUND = (38, 35, 42)


def quaternion(R3: np.ndarray) -> list[float]:
    """(x, y, z, w) of a rotation matrix, as three.js takes it."""
    m = R3
    w = np.sqrt(max(0.0, 1 + m[0, 0] + m[1, 1] + m[2, 2])) / 2
    x = np.sqrt(max(0.0, 1 + m[0, 0] - m[1, 1] - m[2, 2])) / 2
    y = np.sqrt(max(0.0, 1 - m[0, 0] + m[1, 1] - m[2, 2])) / 2
    z = np.sqrt(max(0.0, 1 - m[0, 0] - m[1, 1] + m[2, 2])) / 2
    x = np.copysign(x, m[2, 1] - m[1, 2])
    y = np.copysign(y, m[0, 2] - m[2, 0])
    z = np.copysign(z, m[1, 0] - m[0, 1])
    return [float(x), float(y), float(z), float(w)]


def bones_param(pose: dict[str, np.ndarray]) -> str:
    """The page's ?bones=: every arm bone named, so nothing of the relaxed pose is left over."""
    full = {f"{s}{b}": np.eye(3) for s in ("left", "right") for b in ("UpperArm", "LowerArm")}
    full.update(pose)
    return json.dumps({k: [round(v, 6) for v in quaternion(m)] for k, m in full.items()})


def views_for(size_id: str, sheets: set[str]) -> list[dict]:
    """The fixed views of one size: (name, file, page parameters, sheet, row, column)."""
    _, _, J, _ = R.reference_body(size_id)
    file = f"{size_id}.vrm"
    out = []
    if "sizes" in sheets:
        for label, yaw in FIGURE:
            out.append({"name": f"fig-{size_id}-{label}", "file": file, "yaw": yaw, "size": FIGURE_PX})
    shoulder = {s: J[f"joint-{c}-shoulder"] for s, c in (("left", "l"), ("right", "r"))}
    y = float(shoulder["left"][1])
    if "shoulders" in sheets:
        band = [y - 0.19, y + 0.13]
        out += [
            {"name": f"sh-{size_id}-front", "file": file, "yaw": 0, "focus": band, "size": CLOSE_PX},
            {"name": f"sh-{size_id}-back", "file": file, "yaw": 180, "focus": band, "size": CLOSE_PX},
        ]
        raised = bones_param(rig.named_pose("raised-sideways", J))
        for side, sign in (("left", 1.0), ("right", -1.0)):
            x, z = float(shoulder[side][0]), float(shoulder[side][2])
            out.append(
                {"name": f"sh-{size_id}-{side}-side", "file": file, "yaw": 90 * sign, "fx": x, "fz": z,
                 "focus": [y - 0.2, y + 0.12], "size": SIDE_PX}
            )
            # Under the armpit: the arm raised sideways, seen from below, in front and to her side.
            out.append(
                {"name": f"sh-{size_id}-{side}-underarm", "file": file, "yaw": 55 * sign, "elev": -38,
                 "fx": x * 0.8, "fz": z, "focus": [y - 0.16, y + 0.08], "size": SIDE_PX, "bones": raised}
            )
    if "poses" in sheets:
        for pose in rig.TEST_POSES:
            bones = bones_param(rig.named_pose(pose, J)) if pose != "t-pose" else "rest"
            for label, yaw in (("front", 0), ("back", 180)):
                out.append(
                    {"name": f"pose-{size_id}-{pose}-{label}", "file": file, "yaw": yaw, "size": POSE_PX,
                     "bones": bones}
                )
    return out


def render(work: Path, views: list[dict]) -> None:
    spec = [
        {k: v for k, v in {**view, "out": f"{view['name']}.png"}.items() if k != "name"}
        for view in views
        if not (work / f"{view['name']}.png").exists()
    ]
    if not spec:
        return
    (work / "views.json").write_text(json.dumps(spec))
    done = subprocess.run(["node", str(VIEWS_SCRIPT), str(work)], cwd=str(ROOT), env=os.environ.copy(),
                          timeout=60 * 60)
    if done.returncode != 0:
        raise SystemExit("the viewer failed; see its output above")


def _font(size: int):
    from PIL import ImageFont

    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def grid(cells: list[list[Path | None]], col_labels: list[str], row_labels: list[str], title: str,
         cell: tuple[int, int]) -> object:
    """Tiles in rows and columns, labelled, on the viewer's own background."""
    from PIL import Image, ImageDraw

    head, side = 46, 0
    w, h = cell
    sheet = Image.new("RGB", (side + w * len(col_labels), head + 30 + (h + 26) * len(cells)), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    draw.text((10, 10), title, fill=(235, 232, 240), font=_font(22))
    for c, label in enumerate(col_labels):
        draw.text((side + c * w + 8, head + 4), label, fill=(190, 186, 200), font=_font(17))
    for r, row in enumerate(cells):
        top = head + 30 + r * (h + 26)
        draw.text((side + 8, top + 2), row_labels[r], fill=(220, 216, 228), font=_font(17))
        for c, path in enumerate(row):
            if path is not None and path.exists():
                tile = Image.open(path).convert("RGB").resize((w, h), Image.LANCZOS)
                sheet.paste(tile, (side + c * w, top + 24))
    return sheet


def compose(out: Path, work: Path, sizes: list[str], sheets: set[str], label: str) -> list[str]:
    written = []
    tag = f" - {label}" if label else ""
    if "sizes" in sheets:
        cells = [[work / f"fig-{s}-{v}.png" for v, _ in FIGURE] for s in sizes]
        grid(cells, [v for v, _ in FIGURE], list(sizes), f"Reference sizes, relaxed pose{tag}",
             (300, 472)).save(out / "reference-sizes.png")
        written.append("reference-sizes.png")
    for s in sizes:
        if "shoulders" in sheets:
            cells = [
                [work / f"sh-{s}-front.png", work / f"sh-{s}-back.png"],
                [work / f"sh-{s}-right-side.png", work / f"sh-{s}-left-side.png"],
                [work / f"sh-{s}-right-underarm.png", work / f"sh-{s}-left-underarm.png"],
            ]
            grid(cells, ["", ""], ["front | back (relaxed)", "her right side | her left side (relaxed)",
                                   "under her right arm | under her left arm (raised sideways)"],
                 f"{s} shoulders{tag}", (540, 384)).save(out / f"shoulders-{s}.png")
            written.append(f"shoulders-{s}.png")
        if "poses" in sheets:
            poses = list(rig.TEST_POSES)
            cells = [[work / f"pose-{s}-{p}-{v}.png" for p in poses] for v in ("front", "back")]
            grid(cells, poses, ["front", "back"], f"{s} test poses{tag}", (220, 347)).save(
                out / f"poses-{s}.png"
            )
            written.append(f"poses-{s}.png")
    return written


def metrics(vrm_dir: Path, sizes: list[str]) -> dict:
    """``wardrobe.anatomy.posecheck`` per size and test pose, on the VRM files as rendered.

    ``skinning`` is what any viewer shows; ``driven`` what one that drives the VRM's corrective
    morphs shows (the Studio does), when the file has any. ``armpit`` counts crossings out to
    ``correctives.REGION_M``, where an arm at her side meets her chest below the shoulder region.
    """
    out = {}
    for s in sizes:
        V, T, J, _ = R.reference_body(s)
        region = ShoulderRegion(V, T, J)
        armpit = ShoulderRegion(V, T, J, radius=CR.REGION_M)
        data = (vrm_dir / f"{s}.vrm").read_bytes()
        bound, weights, bind = read_vrm(data)
        made = read_correctives(data)
        out[s] = {}
        for pose in rig.TEST_POSES:
            p = rig.named_pose(pose, J)
            plain = rig.pose_surface(bound, bind, p, weights_of=weights)
            entry = {"skinning": region.report(plain), "armpitSkinning": armpit.report(plain)["crossings"]}
            if made:
                driven = rig.pose_surface(bound, bind, p, morph=CR.driven_morph(made, p), weights_of=weights)
                entry["driven"] = region.report(driven)
                entry["armpitDriven"] = armpit.report(driven)["crossings"]
            out[s][pose] = entry
        print("measured", s, flush=True)
    return out


def side_by_side(before: Path, after: Path, out: Path) -> None:
    from PIL import Image, ImageDraw

    a, b = Image.open(before).convert("RGB"), Image.open(after).convert("RGB")
    h = max(a.height, b.height)
    sheet = Image.new("RGB", (a.width + b.width + 12, h + 40), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    draw.text((10, 8), "before", fill=(235, 180, 180), font=_font(24))
    draw.text((a.width + 22, 8), "after", fill=(180, 235, 190), font=_font(24))
    sheet.paste(a, (0, 40))
    sheet.paste(b, (a.width + 12, 40))
    sheet.save(out)


def build_at_commit(revision: str, sizes: list[str], into: Path) -> None:
    """Build the sizes' VRMs as ``revision`` built them, in a throwaway worktree (this checkout untouched)."""
    import tempfile

    tree = Path(tempfile.mkdtemp(prefix="anatomy-rev-")) / "tree"
    subprocess.run(["git", "worktree", "add", "--detach", str(tree), revision], cwd=ROOT, check=True)
    try:
        script = (
            "import sys; from pathlib import Path; sys.path.insert(0, '.')\n"
            "from wardrobe.anatomy.vrm import build_reference_vrm\n"
            "for s in sys.argv[2:]: (Path(sys.argv[1]) / f'{s}.vrm').write_bytes(build_reference_vrm(s))\n"
        )
        subprocess.run([sys.executable, "-I", "-c", script, str(into), *sizes], cwd=tree, check=True)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=ROOT, check=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--vrm-dir", type=Path, default=None, help="render <size>.vrm from here, not built")
    parser.add_argument("--from-commit", default=None, help="build the VRMs as this git revision did")
    parser.add_argument("--sizes", nargs="*", default=list(SIZES))
    parser.add_argument("--sheets", default="sizes,shoulders,poses")
    parser.add_argument("--metrics", action="store_true")
    parser.add_argument("--compare", type=Path, default=None, help="an earlier OUT_DIR to set beside this")
    parser.add_argument("--label", default="")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    work = out / "tiles"
    work.mkdir(parents=True, exist_ok=True)
    sheets = {s.strip() for s in args.sheets.split(",") if s.strip()}
    if args.from_commit:
        missing = [s for s in args.sizes if not (work / f"{s}.vrm").exists()]
        if missing:
            build_at_commit(args.from_commit, missing, work)
        args.vrm_dir = work
    for s in args.sizes:
        target = work / f"{s}.vrm"
        if args.vrm_dir is not None:
            if args.vrm_dir.resolve() != work:
                shutil.copyfile(args.vrm_dir / f"{s}.vrm", target)
        elif not target.exists():
            from wardrobe.anatomy.vrm import build_reference_vrm

            target.write_bytes(build_reference_vrm(s))
            print("built", target.name, flush=True)
    render(work, [v for s in args.sizes for v in views_for(s, sheets)])
    written = compose(out, work, args.sizes, sheets, args.label)
    if args.metrics:
        (out / "metrics.json").write_text(json.dumps(metrics(work, args.sizes), indent=1) + "\n")
        written.append("metrics.json")
    if args.compare is not None:
        for name in [w for w in written if w.endswith(".png")]:
            if (args.compare / name).exists():
                side_by_side(args.compare / name, out / name, out / f"compare-{name}")
                written.append(f"compare-{name}")
    print("wrote", ", ".join(written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
