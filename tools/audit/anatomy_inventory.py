"""AF1. What anatomy each source avatar actually carries, before anything is taken off.

A bare body can only show what the author built. This reads every library source with the
pipeline's own readers and reports, per character:

* materials, and any whose name or extras label them anatomical;
* her skin (``skin_parts``: chosen by material, her clothes excluded) around two landmarks —
  the pubic region (centred between the thigh roots, just below them) and each bust apex:
  how many skin vertices are there, how long their edges are (a 15 mm mesh cannot hold detail
  a few millimetres across), and how far the surface departs from a smooth fit (relief);
* the skin texture under those vertices: luminance spread and the share of texels that are
  not skin-coloured (painted underwear, or authored pigmentation).

Classification per region, as the brief defines it:
  A  geometry exists there (relief above the smooth fit, dense enough to hold it)
  B  detail exists only in texture / normal map
  C  neither: the source has no authored anatomy there

Run:  python tools/audit/anatomy_inventory.py [--out work/anatomy-inventory.json]
Prints a table; writes JSON. Reads only; changes nothing.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from wardrobe.body_surface.surface import skin_parts  # noqa: E402
from wardrobe.vrm.document import GltfDocument  # noqa: E402
from wardrobe.vrm.inspect import inspect_document  # noqa: E402
from wardrobe.vrm.measure import measure_body  # noqa: E402

ANATOMY = ("genital", "vulva", "penis", "scrot", "nipple", "areola", "anatom", "pubic")


def sources() -> list[tuple[str, Path]]:
    lib = ROOT / "assets" / "library"
    out = [(p.stem, p) for p in sorted(lib.glob("*.vrm"))]
    out += [(p.stem, p) for p in sorted((lib / "vroid").glob("*.vrm"))]
    return out


def texture_of(doc: GltfDocument, material: dict):
    """The base-colour image of a material, as an RGB array, or None."""
    from PIL import Image

    info = (material.get("pbrMetallicRoughness") or {}).get("baseColorTexture")
    if not info:
        return None
    texture = doc.gltf["textures"][info["index"]]
    image = doc.gltf["images"][texture["source"]]
    view = doc.gltf["bufferViews"][image["bufferView"]]
    start = view.get("byteOffset", 0)
    data = doc.binary[start:start + view["byteLength"]]
    return np.asarray(Image.open(io.BytesIO(data)).convert("RGBA"), dtype=np.float32) / 255.0


def uv_of(doc: GltfDocument, primitive_ref) -> np.ndarray | None:
    mesh, prim = primitive_ref
    attrs = doc.meshes[mesh]["primitives"][prim].get("attributes", {})
    return doc.read_accessor(attrs["TEXCOORD_0"]) if "TEXCOORD_0" in attrs else None


def relief(points: np.ndarray, normals_hint: np.ndarray | None = None) -> float:
    """RMS distance (mm) of points from their best-fit quadric surface: shape the smooth body lacks."""
    if len(points) < 12:
        return 0.0
    c = points - points.mean(0)
    _, _, vt = np.linalg.svd(c, full_matrices=False)
    u, v, n = c @ vt[0], c @ vt[1], c @ vt[2]
    a = np.stack([u * u, v * v, u * v, u, v, np.ones_like(u)], 1)
    coef, *_ = np.linalg.lstsq(a, n, rcond=None)
    return float(np.sqrt(np.mean((n - a @ coef) ** 2)) * 1000.0)


def region(parts, centre: np.ndarray, radius: float):
    pts, edges, owners = [], [], []
    for part in parts:
        used = part.used
        p = part.positions[used]
        near = np.linalg.norm(p - centre, axis=1) < radius
        if not near.any():
            continue
        keep = set(used[near].tolist())
        pts.append(p[near])
        owners.append((part, used[near]))
        tri = part.triangles[np.isin(part.triangles, list(keep)).all(1)]
        if len(tri):
            e = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
            edges.append(np.linalg.norm(part.positions[e[:, 0]] - part.positions[e[:, 1]], axis=1))
    if not pts:
        return None
    pts = np.concatenate(pts)
    edge = np.concatenate(edges) if edges else np.array([np.nan])
    return pts, edge, owners


def texture_stats(doc, owners):
    lum, painted, n = [], 0, 0
    for part, idx in owners:
        material = doc.materials[part.material]
        tex = texture_of(doc, material)
        uv = uv_of(doc, part.primitives[0])
        if tex is None or uv is None:
            continue
        h, w = tex.shape[:2]
        uvs = uv[idx]
        xs = np.clip((uvs[:, 0] % 1.0) * (w - 1), 0, w - 1).astype(int)
        ys = np.clip((uvs[:, 1] % 1.0) * (h - 1), 0, h - 1).astype(int)
        rgb = tex[ys, xs, :3]
        l = rgb @ np.array([0.299, 0.587, 0.114])
        lum.append(l)
        # Skin is warm and fairly light; anything far from the region's median hue is not skin.
        med = np.median(rgb, 0)
        painted += int((np.linalg.norm(rgb - med, axis=1) > 0.18).sum())
        n += len(rgb)
        alpha = tex[ys, xs, 3]
        painted += int((alpha < 0.5).sum())
    if not lum:
        return {"texture": None}
    l = np.concatenate(lum)
    return {"luminanceStd": round(float(l.std()), 4), "offSkinShare": round(painted / max(n, 1), 3), "texels": n}


def inspect(name: str, path: Path) -> dict:
    doc = GltfDocument.from_path(path)
    info = inspect_document(doc)
    m = measure_body(doc, info)
    bones = {k: np.asarray(v, dtype=float) for k, v in dict(m.bone_positions).items()}
    parts = skin_parts(doc, bones)
    mats = [mat.get("name", "") for mat in doc.materials]
    labelled = [x for x in mats if any(k in x.lower() for k in ANATOMY)]
    out = {"name": name, "materials": len(mats), "anatomicalMaterials": labelled,
           "skinParts": len(parts), "regions": {}}
    if not parts:
        out["regions"] = {"note": "no skin found by skin_parts"}
        return out
    l, r = bones.get("leftUpperLeg"), bones.get("rightUpperLeg")
    hips = bones["hips"]
    if l is not None and r is not None:
        # Pubic region: between the thigh roots, a little below and in front of them.
        pubic = (l + r) / 2.0 + np.array([0.0, -0.06, 0.0])
        all_pts = np.concatenate([p.positions[p.used] for p in parts])
        # Push the centre forward onto the front surface of her body at that height.
        slab = all_pts[np.abs(all_pts[:, 1] - pubic[1]) < 0.02]
        slab = slab[np.abs(slab[:, 0] - pubic[0]) < 0.03]
        front = 1.0 if (all_pts[:, 2].mean() - hips[2]) >= 0 else -1.0
        if len(slab):
            pubic[2] = slab[:, 2].max() if front > 0 else slab[:, 2].min()
        targets = {"pubic": (pubic, 0.06)}
    else:
        targets = {}
    chest = bones.get("upperChest", bones.get("chest"))
    if chest is not None:
        all_pts = np.concatenate([p.positions[p.used] for p in parts])
        band = all_pts[np.abs(all_pts[:, 1] - (chest[1] - 0.02)) < 0.05]
        for side, sign in (("leftBust", 1.0), ("rightBust", -1.0)):
            half = band[(band[:, 0] - chest[0]) * sign > 0.03]
            if len(half):
                apex = half[np.argmax(np.abs(half[:, 2] - chest[2]))]
                targets[side] = (apex, 0.04)
    for key, (centre, radius) in targets.items():
        got = region(parts, centre, radius)
        if got is None:
            out["regions"][key] = {"vertices": 0, "class": "C", "why": "no skin there (deleted under clothes)"}
            continue
        pts, edge, owners = got
        rel = relief(pts)
        tex = texture_stats(doc, owners)
        med_edge = float(np.nanmedian(edge) * 1000.0)
        geometry = len(pts) >= 150 and med_edge < 6.0 and rel > 1.5
        textured = tex.get("luminanceStd", 0) > 0.08
        cls = "A" if geometry else ("B" if textured else "C")
        out["regions"][key] = {
            "vertices": int(len(pts)),
            "medianEdgeMm": round(med_edge, 1),
            "reliefMm": round(rel, 2),
            **tex,
            "class": cls,
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    rows = []
    for name, path in sources():
        try:
            rows.append(inspect(name, path))
        except Exception as exc:  # one unreadable source must not hide the others
            rows.append({"name": name, "error": str(exc)})
    for r in rows:
        regions = r.get("regions", {})
        cells = "  ".join(
            f"{k}: {v.get('class')} ({v.get('vertices', 0)} v, {v.get('medianEdgeMm', '-')} mm, "
            f"relief {v.get('reliefMm', '-')} mm, texStd {v.get('luminanceStd', '-')}, offSkin {v.get('offSkinShare', '-')})"
            for k, v in regions.items() if isinstance(v, dict)
        )
        print(f"{r['name']:<26} labelled={r.get('anatomicalMaterials')}  {cells or r.get('error') or regions}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
