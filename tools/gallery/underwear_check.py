"""Underwear check: one look, its review sheet, close-ups from below and a geometry report.

    python tools/gallery/underwear_check.py OUT_DIR \\
        [--avatar assets/library/AvatarSample_A.vrm] [--prompt "white plunge bra + white thong"]
        [--no-generate]

What the white micro thong on AvatarSample A needed to be seen, kept as a tool, since a fit
report that passes says nothing about what the underside looks like:

* the full review sheet (``garment_review.py``: 18 cameras, Studio options, the avatar declared
  adult as the Space's admin session does), as ``look-sheet.png``;
* tight close-ups between her thighs from below and from the front (``close-below.png``,
  ``close-front.png``), the Studio's own viewer and lights;
* per garment, a wireframe seen from below with folded triangles in red (``wire-<name>.png``);
* ``report.json``: per garment, triangles folded against their corners' normals, gusset
  triangles wound into her (facing up under her crotch), slivers, open edges (welded by
  position, as ``wardrobe.lingerie.seams`` counts them) and clearance from her skin in mm.

The rendering needs Chromium and the CDN route the gallery uses (PLAYWRIGHT_CHROMIUM,
GALLERY_CDN_ROUTE; see render.mjs). Library avatars come from ``tools/fetch_library.py``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from wardrobe.vrm.document import GltfDocument  # noqa: E402

LOOK = "look"
#: Close-ups between her thighs: (name, elevation in degrees, height band in metres).
CLOSE = (("close-below", -70, [0.74, 0.92]), ("close-front", -10, [0.78, 0.92]))
#: A triangle smaller than this (m²) is a sliver.
SLIVER_M2 = 5e-7


def primitives(document: GltfDocument):
    """(node name, material name, positions, triangles, normals) of every primitive."""
    for node in document.nodes:
        if "mesh" not in node:
            continue
        for prim in document.meshes[node["mesh"]]["primitives"]:
            material = document.gltf["materials"][prim["material"]].get("name", "")
            yield (node.get("name") or "", material,
                   document.read_accessor(prim["attributes"]["POSITION"]).astype(np.float64),
                   document.read_accessor(prim["indices"]).astype(np.int64).reshape(-1, 3),
                   document.read_accessor(prim["attributes"]["NORMAL"]).astype(np.float64))


def garment_report(V, F, N, skin_points, skin_normals, crotch_y: float) -> dict:
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    face = np.cross(b - a, c - a)
    area = np.linalg.norm(face, axis=1) / 2
    unit = face / np.maximum(np.linalg.norm(face, axis=1, keepdims=True), 1e-15)
    folded = np.einsum("ij,ij->i", unit, N[F].mean(axis=1)) < 0
    centre = V[F].mean(axis=1)
    under = (centre[:, 1] < crotch_y) & (np.abs(centre[:, 0]) < 0.05)
    inward = under & (unit[:, 1] > 0.2)
    keys = np.round(V / 1e-6).astype(np.int64)
    _, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    welded = first[inverse.reshape(-1)][F]
    edges = np.sort(np.vstack([welded[:, [0, 1]], welded[:, [1, 2]], welded[:, [2, 0]]]), axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    used = np.unique(F)
    signed = np.empty(used.size)
    for start in range(0, used.size, 300):
        p = V[used[start:start + 300]]
        nearest = ((p[:, None, :] - skin_points[None]) ** 2).sum(-1).argmin(axis=1)
        signed[start:start + 300] = np.einsum("ij,ij->i", p - skin_points[nearest], skin_normals[nearest])
    return {
        "triangles": int(F.shape[0]),
        "folded": int(folded.sum()),
        "gussetIntoHer": int(inward.sum()),
        "slivers": int((area < SLIVER_M2).sum()),
        "openEdges": int((counts == 1).sum()),
        "nonManifoldEdges": int((counts > 2).sum()),
        "clearanceMm": {"min": round(float(signed.min() * 1000), 2),
                        "p1": round(float(np.percentile(signed, 1) * 1000), 2),
                        "median": round(float(np.median(signed) * 1000), 2)},
        "verticesInside": int((signed < 0).sum()),
    }


def wireframe_below(V, F, folded, out: Path, crotch_y: float) -> None:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1000, 1000), (20, 20, 24))
    draw = ImageDraw.Draw(image)
    keep = V[F].mean(axis=1)[:, 1] < crotch_y + 0.06
    scale = 6000.0

    def at(v):
        return 500 + v[0] * scale, 500 - v[2] * scale

    for tri, bad in zip(F[keep], folded[keep], strict=True):
        draw.polygon([at(V[i]) for i in tri], fill=(200, 40, 40) if bad else None, outline=(120, 160, 255))
    image.save(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", type=Path)
    parser.add_argument("--avatar", default=str(ROOT / "assets" / "library" / "AvatarSample_A.vrm"))
    parser.add_argument("--prompt", default="white plunge bra + white thong")
    parser.add_argument("--no-generate", action="store_true", help="reuse OUT/look.vrm")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not args.no_generate:
        subprocess.run([sys.executable, str(ROOT / "tools" / "gallery" / "garment_review.py"), str(out),
                        "--avatar", args.avatar, "--studio", "--declare-adult", "--look", LOOK, args.prompt],
                       check=True)
    vrm = out / f"{LOOK}.vrm"
    views = [{"file": vrm.name, "out": f"{name}.png", "size": [900, 700], "yaw": 0, "elev": elev,
              "focus": band} for name, elev, band in CLOSE]
    (out / "views.json").write_text(json.dumps(views))
    subprocess.run(["node", str(ROOT / "tools" / "gallery" / "views.mjs"), str(out)], check=True)

    document = GltfDocument.from_bytes(vrm.read_bytes())
    prims = list(primitives(document))
    skin = [(V[np.unique(F)], N[np.unique(F)]) for node, material, V, F, N in prims
            if node == "Body" and "SKIN" in material.upper()]
    skin_points = np.vstack([s[0] for s in skin])
    skin_normals = np.vstack([s[1] for s in skin])
    garments = {}
    for node, _material, V, F, N in prims:
        if node in ("Body", "Face") or node.startswith("Hair"):
            continue
        garments.setdefault(node, []).append((V, F, N))
    report = {"avatar": Path(args.avatar).name, "prompt": args.prompt, "garments": {}}
    lower = [V[:, 1].min() for parts in garments.values() for V, _F, _N in parts]
    crotch_y = float(min(lower)) + 0.03 if lower else 0.8
    for name, parts in garments.items():
        V, F, N = parts[0]
        near = (np.abs(skin_points[:, 1] - V[:, 1].mean()) < 0.25) & (np.abs(skin_points[:, 0]) < 0.25)
        report["garments"][name] = garment_report(V, F, N, skin_points[near], skin_normals[near], crotch_y)
        a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
        folded = np.einsum("ij,ij->i", np.cross(b - a, c - a), N[F].mean(axis=1)) < 0
        wireframe_below(V, F, folded, out / f"wire-{name.replace(' ', '-').lower()}.png", crotch_y)
    (out / "report.json").write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
