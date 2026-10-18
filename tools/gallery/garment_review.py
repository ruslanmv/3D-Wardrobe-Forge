"""G7. A garment's construction, reviewed from every side at matched cameras: before and after a change.

    python tools/gallery/garment_review.py OUT_DIR \\
        --look cardigan "grey long cardigan + white fitted tee + black straight trousers" \\
        --look camisole "red cropped camisole + black leggings" [--avatar PATH] [--compare BEFORE_DIR]

Each look goes through the real pipeline (``looks.py``, on AvatarSample A unless ``--avatar``
says otherwise) and is rendered with the Studio's own viewer (``views.mjs``) from sixteen
fixed cameras: front, three-quarter, left side, back, orthographic front and side (a 1.5° lens
from far away: a box stays a box, so the GC0 review's "the cardigan is a rectangle in profile"
is a picture, not an impression), low angle, arms raised, arms lowered, seated, and close-ups
of the shoulders, neckline, waist, crotch and hems. Writes OUT_DIR/<name>-<view>.png, one
contact sheet per look (OUT_DIR/<name>-sheet.png), and the fit records (g-records.json).

``--compare BEFORE_DIR`` sets each view beside the same view of an earlier run: the cameras
are the same, so the difference is the garment. Rendering needs Playwright and Chromium, as
``render.mjs`` does (PLAYWRIGHT_CHROMIUM and GALLERY_CDN_ROUTE work the same).

The poses are the reference bodies' (``wardrobe.anatomy.rig``), turned into the frame of a
VRM 0.x bone when the avatar is one: VRM 0.x bones face -Z.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "gallery"))
sys.path.insert(0, str(ROOT / "tools" / "anatomy"))
from wardrobe.anatomy import rig  # noqa: E402
from wardrobe.vrm.document import GltfDocument  # noqa: E402

AVATAR = ROOT / "assets" / "library" / "AvatarSample_A.vrm"
FULL = ["front", "three-quarter", "left-side", "back", "ortho-front", "ortho-side", "low-angle",
        "arms-raised", "arms-lowered", "seated"]
CLOSE = ["close-shoulders", "close-neckline", "close-waist", "close-crotch", "close-hem-upper",
         "close-hem-lower"]


def _bones(pose: dict, vrm0: bool) -> str:
    from render_reference import quaternion

    out = {}
    for bone, matrix in pose.items():
        x, y, z, w = quaternion(matrix)
        out[bone] = [-x, y, -z, w] if vrm0 else [x, y, z, w]
    return json.dumps(out)


def views_for(name: str, vrm: Path) -> list[dict]:
    doc = GltfDocument.from_bytes(vrm.read_bytes())
    vrm0 = "VRMC_vrm" not in (doc.gltf.get("extensions") or {})
    sides = (("left", 1), ("right", -1))
    raised = _bones({f"{s}UpperArm": rig.rotation((0, 0, 1), np.radians(k * 35)) for s, k in sides}, vrm0)
    lowered = _bones({f"{s}UpperArm": rig.rotation((0, 0, 1), np.radians(-k * 80)) for s, k in sides}, vrm0)
    seated_pose = {}
    for s, k in sides:
        seated_pose[f"{s}UpperLeg"] = rig.rotation((1, 0, 0), np.radians(-85))
        seated_pose[f"{s}LowerLeg"] = rig.rotation((1, 0, 0), np.radians(85))
        seated_pose[f"{s}UpperArm"] = rig.rotation((0, 0, 1), np.radians(-k * 70))
    seated = _bones(seated_pose, vrm0)
    views: list[dict] = []

    def view(label: str, **kw) -> None:
        size = kw.pop("size", [600, 900])
        views.append({"file": vrm.name, "out": f"{name}-{label}.png", "size": size, **kw})

    for label, yaw in (("front", 0), ("three-quarter", 35), ("left-side", 90), ("back", 180)):
        view(label, yaw=yaw)
    view("ortho-front", yaw=0, ortho=True)
    view("ortho-side", yaw=90, ortho=True)
    view("low-angle", yaw=25, elev=-30, focus=[0.0, 1.55])
    view("arms-raised", yaw=20, bones=raised)
    view("arms-lowered", yaw=20, bones=lowered)
    view("seated", yaw=60, bones=seated)
    for label, band, yaw, elev in (("shoulders", [1.05, 1.42], 30, 0), ("neckline", [1.08, 1.36], 0, 10),
                                   ("waist", [0.78, 1.08], 30, 0), ("crotch", [0.55, 0.85], 15, -25),
                                   ("hem-upper", [0.55, 0.95], 60, 0), ("hem-lower", [0.0, 0.35], 30, 0)):
        view("close-" + label, yaw=yaw, elev=elev, focus=band, size=[700, 560])
    return views


def sheet(out: Path, name: str, title: str, before: Path | None = None) -> Path:
    from PIL import Image, ImageDraw

    W, H, CW, CH = 300, 450, 500, 240
    columns = 2 if before else 1
    canvas = Image.new("RGB", (W * 5 * columns, 40 + 2 * (H + 24) + 2 * (CH + 24)), (36, 34, 42))
    draw = ImageDraw.Draw(canvas)
    draw.text((10, 12), title, fill=(240, 240, 240))
    for c, folder in enumerate([out] + ([before] if before else [])):
        offset = c * W * 5
        if before:
            draw.text((offset + 10, 26), "after" if c == 0 else "before", fill=(200, 200, 120))
        for k, label in enumerate(FULL):
            x, y = offset + (k % 5) * W, 40 + (k // 5) * (H + 24)
            draw.text((x + 6, y + 4), label, fill=(220, 220, 220))
            picture = Image.open(folder / f"{name}-{label}.png").convert("RGB")
            picture.thumbnail((W, H))
            canvas.paste(picture, (x, y + 22))
        for k, label in enumerate(CLOSE):
            x, y = offset + (k % 3) * CW, 40 + 2 * (H + 24) + (k // 3) * (CH + 24)
            draw.text((x + 6, y + 4), label, fill=(220, 220, 220))
            picture = Image.open(folder / f"{name}-{label}.png").convert("RGB")
            picture.thumbnail((CW, CH))
            canvas.paste(picture, (x, y + 22))
    path = out / (f"{name}-compare.png" if before else f"{name}-sheet.png")
    canvas.save(path)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", type=Path)
    parser.add_argument("--look", nargs=2, action="append", metavar=("NAME", "PROMPT"), required=True)
    parser.add_argument("--avatar", type=Path, default=AVATAR)
    parser.add_argument("--compare", type=Path, help="an earlier OUT_DIR, set beside this one view by view")
    parser.add_argument("--no-generate", action="store_true", help="render the VRMs already in OUT_DIR")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not args.no_generate:
        import looks

        looks.EVERYDAY_LOOKS = [(k + 1, name, prompt, {}) for k, (name, prompt) in enumerate(args.look)]
        asyncio.run(looks.main(out, args.avatar.resolve(), set()))
        for k, (name, _) in enumerate(args.look):
            (out / f"{name}.vrm").write_bytes((out / f"g-{k + 1:02d}.vrm").read_bytes())
    views = [v for name, _ in args.look for v in views_for(name, out / f"{name}.vrm")]
    (out / "views.json").write_text(json.dumps(views), encoding="utf-8")
    subprocess.run(["node", str(ROOT / "tools" / "gallery" / "views.mjs"), str(out)], check=True)
    for name, prompt in args.look:
        print(sheet(out, name, prompt))
        if args.compare:
            print(sheet(out, name, f"{prompt} - after | before", before=args.compare.resolve()))


if __name__ == "__main__":
    main()
