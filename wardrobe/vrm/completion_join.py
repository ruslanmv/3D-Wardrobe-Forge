"""BR2. How well a BC1 patch meets the body it completes, in numbers.

BR1 made a bare body buildable for a character whose export deleted part of her skin, by filling
only the missing band with BC1's featureless patch. Whether that fill is *good* was never
measured: the integrity check only says the band is now closed when sampled round her axis. A
patch can close the band and still show a crack at its edge, sit in the same depth as her skin
(z-fighting), shade as a different surface across the seam, tear away from her when she moves,
or be a different colour from the skin round it. Each of those is a number here, so a change to
the patch can be judged by measurement and a reviewer reads the same numbers the tests assert.

Nothing here changes the document. It reads the authored skin (her own skin material's
primitives, minus garments and the patch), finds the authored *open boundary* next to the patch
(the rim of the hole the export left), and compares that rim with the patch:

* ``gapMm`` — each rim vertex's distance to the patch surface (the crack you would see);
* ``overlap`` — patch vertices within ``ZFIGHT_M`` of her skin (same depth: z-fighting), and
  how much of the patch lies under her skin rather than in the hole;
* ``normals`` — the angle between her normal at the rim and the patch's at the same place,
  and inside the patch between its stored normals and its own surface;
* ``posed`` — the rim's distance to the patch again in each of the integration tests' poses
  (``POSE_TESTS``), skinned with each surface's own weights: a patch weighted unlike her rim
  opens a crack as soon as she moves;
* ``colour`` — her texel colour at each rim vertex against the patch's, as RGB distance, against
  the restorer's own ``KNOWN_DISTANCE`` (what it counts as "her skin");
* ``material`` — render state of the patch's material against hers; and ``tags``.
"""

from __future__ import annotations

import numpy as np

from wardrobe.engines.geometry_checks import POSE_TESTS
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.measure import BodyMeasurements
from wardrobe.vrm.painted_clothing import TORSO_RADIUS_M, _image, _triangles

#: Closer than this to her skin, a patch face fights it for depth.
ZFIGHT_M = 0.0005
#: Rim vertices are taken this far beyond the patch's own height span.
RIM_MARGIN_M = 0.01
PROXY_NAME = "body proxy"


def _is_proxy(material: dict) -> bool:
    return PROXY_NAME in str(material.get("name", "")).lower()


def closest_on_triangles(points: np.ndarray, tris: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Distance from each point to the nearest of ``tris`` (T, 3, 3), and that triangle's index."""
    best = np.full(len(points), np.inf)
    which = np.zeros(len(points), dtype=np.int64)
    if not len(tris) or not len(points):
        return best, which
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    ab, ac = b - a, c - a
    for start in range(0, len(points), 256):
        p = points[start:start + 256, None, :]
        ap = p - a
        d1, d2 = (ab * ap).sum(-1), (ac * ap).sum(-1)
        bp = p - b
        d3, d4 = (ab * bp).sum(-1), (ac * bp).sum(-1)
        cp = p - c
        d5, d6 = (ab * cp).sum(-1), (ac * cp).sum(-1)
        va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
        denom = np.where(np.abs(va + vb + vc) < 1e-18, 1e-18, va + vb + vc)
        v, w = vb / denom, vc / denom
        inside = (v >= 0) & (w >= 0) & (v + w <= 1)
        face = np.sqrt(((p - (a + ab * v[..., None] + ac * w[..., None])) ** 2).sum(-1))
        # Outside the face the nearest point is on one of its three edges (never the in-plane
        # projection, which lies off the triangle and would read nearer than anything on it).
        edge = np.full(face.shape, np.inf)
        for e0, e1 in ((a, b), (b, c), (c, a)):
            ed = e1 - e0
            t = np.clip(((p - e0) * ed).sum(-1) / np.maximum((ed * ed).sum(-1), 1e-18), 0.0, 1.0)
            edge = np.minimum(edge, np.sqrt(((p - (e0 + ed * t[..., None])) ** 2).sum(-1)))
        dist = np.where(inside, face, edge)
        best[start:start + 256] = dist.min(axis=1)
        which[start:start + 256] = dist.argmin(axis=1)
    return best, which


def _drawn(document: GltfDocument):
    """(node index, node, mesh index, primitive index, primitive) of every drawn triangle primitive."""
    for ni in document.mesh_nodes():
        node = document.nodes[ni]
        for pi, primitive in enumerate(document.meshes[node["mesh"]].get("primitives", [])):
            if primitive.get("mode", 4) == 4 and "POSITION" in primitive.get("attributes", {}):
                yield ni, node, node["mesh"], pi, primitive


def _barycentric(point: np.ndarray, corners: np.ndarray) -> np.ndarray:
    """Barycentric coordinates of ``point``'s projection on a triangle, clamped onto it."""
    a, b, c = corners
    v0, v1, v2 = b - a, c - a, point - a
    d00, d01, d11, d20, d21 = v0 @ v0, v0 @ v1, v1 @ v1, v2 @ v0, v2 @ v1
    denom = d00 * d11 - d01 * d01
    if abs(denom) < 1e-18:
        return np.array([1.0, 0.0, 0.0])
    v = (d11 * d20 - d01 * d21) / denom
    w = (d00 * d21 - d01 * d20) / denom
    out = np.clip(np.array([1.0 - v - w, v, w]), 0.0, None)
    return out / max(out.sum(), 1e-12)


def _edges(faces: np.ndarray) -> np.ndarray:
    """Each undirected edge of ``faces`` once."""
    if not len(faces):
        return np.zeros((0, 2), dtype=np.int64)
    both = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    return np.unique(np.sort(both, axis=1), axis=0)


def _vertex_normals(points: np.ndarray, faces: np.ndarray) -> np.ndarray:
    out = np.zeros_like(points)
    face = np.cross(points[faces[:, 1]] - points[faces[:, 0]], points[faces[:, 2]] - points[faces[:, 0]])
    for k in range(3):
        np.add.at(out, faces[:, k], face)
    return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-12)


def _angle_deg(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-12)
    b = b / np.maximum(np.linalg.norm(b, axis=1, keepdims=True), 1e-12)
    return np.degrees(np.arccos(np.clip((a * b).sum(axis=1), -1.0, 1.0)))


def _texel(document: GltfDocument, material: dict, uv: np.ndarray, cache: dict) -> np.ndarray | None:
    pbr = material.get("pbrMetallicRoughness") or {}
    factor = np.asarray(pbr.get("baseColorFactor", [1, 1, 1, 1])[:3], dtype=np.float64)
    index = (pbr.get("baseColorTexture") or {}).get("index")
    if index is None:
        return np.tile(factor * 255.0, (len(uv), 1))
    image = _image(document, int(index), cache)
    if image is None:
        return None
    h, w = image.shape[:2]
    px = np.clip(((uv[:, 0] % 1.0) * w).astype(int), 0, w - 1)
    py = np.clip(((uv[:, 1] % 1.0) * h).astype(int), 0, h - 1)
    return image[py, px, :3].astype(np.float64) * factor


def _pose_table(document: GltfDocument, info, measurements: BodyMeasurements, pose: str) -> dict:
    from wardrobe.hosiery.poses import node_table

    forward = 1.0 if str(getattr(info, "spec_version", "") or "").startswith("1") or \
        "VRMC_vrm" in (document.gltf.get("extensions") or {}) else -1.0
    return node_table(document, info, pose, forward, measurements.bone_positions)


def _posed(document, node, primitive, table) -> np.ndarray:
    from wardrobe.hosiery.poses import posed_primitive

    result = posed_primitive(document, node, primitive, table)
    if result is None:
        return document.read_accessor(primitive["attributes"]["POSITION"]).astype(np.float64)[:, :3]
    return result[0]


def _stats(values: np.ndarray, scale: float = 1.0, digits: int = 2) -> dict:
    if not len(values):
        return {"max": None, "p95": None, "mean": None}
    v = np.asarray(values, dtype=np.float64) * scale
    return {"max": round(float(v.max()), digits), "p95": round(float(np.percentile(v, 95)), digits),
            "mean": round(float(v.mean()), digits)}


def measure_join(document: GltfDocument, measurements: BodyMeasurements, info=None, *,
                 removed: set[tuple[int, int]] = frozenset(), poses: bool = True) -> dict | None:
    """Every join number for the BC1 patch in ``document``; None when it has no patch.

    ``removed`` are garment primitives still in the document but not part of her body (the
    patch is made before they come off); a document they were already removed from needs none.
    """
    if info is None:
        from wardrobe.vrm.inspect import inspect_document
        info = inspect_document(document)
    materials = document.materials
    proxy_parts, skin_parts = [], {}
    for ni, node, mi, pi, primitive in _drawn(document):
        material = materials[primitive["material"]] if "material" in primitive else {}
        if _is_proxy(material):
            proxy_parts.append((ni, node, mi, pi, primitive))
        elif (mi, pi) not in removed:
            skin_parts.setdefault(primitive.get("material"), []).append((ni, node, mi, pi, primitive))
    if not proxy_parts:
        return None
    # Her skin is the material the patch was copied from: same name before " · body proxy".
    proxy_material = materials[proxy_parts[0][4]["material"]]
    base_name = str(proxy_material.get("name", "")).split(" · ")[0]
    skin_index = next((k for k in skin_parts
                       if k is not None and materials[k].get("name") == base_name), None)
    if skin_index is None:
        return None
    skin_material = materials[skin_index]

    skins = document.gltf.get("skins") or []

    def gather(parts):
        pts, faces, normals, uvs, refs, rig, offset = [], [], [], [], [], [], 0
        for ni, node, _, _, primitive in parts:
            attributes = primitive["attributes"]
            p = document.read_accessor(attributes["POSITION"]).astype(np.float64)[:, :3]
            t = _triangles(document, primitive, len(p))
            used = np.unique(t)
            remap = np.full(len(p), -1)
            remap[used] = np.arange(len(used)) + offset
            pts.append(p[used])
            faces.append(remap[t])
            n = (document.read_accessor(attributes["NORMAL"]).astype(np.float64)[:, :3][used]
                 if "NORMAL" in attributes else np.zeros((len(used), 3)))
            normals.append(n)
            uv = (document.read_accessor(attributes["TEXCOORD_0"]).astype(np.float64)[:, :2][used]
                  if "TEXCOORD_0" in attributes else np.zeros((len(used), 2)))
            uvs.append(uv)
            refs.append((ni, node, primitive, used, offset))
            # Weights by joint *node*, so two meshes on different skins still compare.
            nodes = (skins[node["skin"]].get("joints") or []) if node.get("skin") is not None else []
            if nodes and "JOINTS_0" in attributes and "WEIGHTS_0" in attributes:
                js = document.read_accessor(attributes["JOINTS_0"]).astype(np.int64)[used]
                ws = document.read_accessor(attributes["WEIGHTS_0"]).astype(np.float64)[used]
                rig += [{nodes[int(j)]: float(w) for j, w in zip(jr, wr, strict=True)
                         if w > 0 and j < len(nodes)} for jr, wr in zip(js, ws, strict=True)]
            else:
                rig += [{} for _ in used]
            offset += len(used)
        return np.vstack(pts), np.vstack(faces), np.vstack(normals), np.vstack(uvs), refs, rig

    patch_p, patch_f, patch_n, patch_uv, patch_refs, patch_rig = gather(proxy_parts)
    skin_p, skin_f, skin_n, skin_uv, skin_refs, skin_rig = gather(skin_parts[skin_index])

    # The authored open boundary: edges used by one triangle once vertices split at UV seams are
    # welded back together by position.
    key = np.round(skin_p / 1e-5).astype(np.int64)
    _, weld = np.unique(key, axis=0, return_inverse=True)
    weld = weld.reshape(-1)
    welded = weld[skin_f]
    edges = np.sort(np.concatenate([welded[:, [0, 1]], welded[:, [1, 2]], welded[:, [2, 0]]]), axis=1)
    unique_edges, counts = np.unique(edges, axis=0, return_counts=True)
    open_ids = np.unique(unique_edges[counts == 1])
    representative = np.zeros(weld.max() + 1, dtype=np.int64)
    representative[weld] = np.arange(len(weld))
    rim = representative[open_ids]
    low, high = patch_p[:, 1].min() - RIM_MARGIN_M, patch_p[:, 1].max() + RIM_MARGIN_M
    hips = measurements.bone_positions.get("hips")
    axis_x, axis_z = (float(hips[0]), float(hips[2])) if hips is not None else (0.0, 0.0)
    radial = np.hypot(skin_p[rim, 0] - axis_x, skin_p[rim, 2] - axis_z)
    rim = rim[(skin_p[rim, 1] >= low) & (skin_p[rim, 1] <= high) & (radial < TORSO_RADIUS_M)]

    patch_tris = patch_p[patch_f]
    gap, nearest_face = closest_on_triangles(skin_p[rim], patch_tris)

    # Skin near the patch only: a whole body's triangles are not needed to measure a band.
    centre_y = skin_p[skin_f].mean(axis=1)[:, 1]
    near = skin_f[(centre_y >= low - 0.03) & (centre_y <= high + 0.03)]
    under, under_face = closest_on_triangles(patch_p, skin_p[near])
    # In front of her skin: over the nearest skin face (its nearest point inside the face, not on
    # an edge — past the rim's edge a vertex is in the hole, not in front of anything), on its
    # outer side (her own normals say which side is out), and close enough to be that face's.
    in_front = np.zeros(len(patch_p), dtype=bool)
    if len(near):
        tri = skin_p[near][under_face]
        plane = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        plane /= np.maximum(np.linalg.norm(plane, axis=1, keepdims=True), 1e-12)
        plane *= np.sign((plane * skin_n[near][under_face].sum(axis=1)).sum(axis=1))[:, None]
        signed = ((patch_p - tri[:, 0]) * plane).sum(axis=1)
        in_front = (signed > 0) & (np.abs(np.abs(signed) - under) < 1e-5) & (under < 0.005)
    patch_area = 0.5 * np.linalg.norm(np.cross(patch_tris[:, 1] - patch_tris[:, 0],
                                               patch_tris[:, 2] - patch_tris[:, 0]), axis=1)
    face_under = under[patch_f].max(axis=1) < 0.005

    # Normals: hers at the rim against the patch's stored normal at the nearest patch corner.
    corner = patch_f[nearest_face]
    pick = np.array([], int)
    if len(rim):
        closest = np.argmin(np.linalg.norm(patch_p[corner] - skin_p[rim][:, None, :], axis=2), axis=1)
        pick = corner[np.arange(len(rim)), closest]
    seam_angle = _angle_deg(skin_n[rim], patch_n[pick]) if len(rim) else np.array([])
    geometric = _vertex_normals(patch_p, patch_f)
    stored_vs_surface = _angle_deg(patch_n, geometric)
    # Between neighbours along every patch edge: a step in shading inside the patch, or where the
    # rows under her skin (her normals) meet the rows over the hole (the patch's own).
    edges = _edges(patch_f)
    neighbour = _angle_deg(patch_n[edges[:, 0]], patch_n[edges[:, 1]])
    # The same between her own neighbouring vertices round the patch: what "smooth" means on her.
    own_edges = _edges(near)
    own_neighbour = (_angle_deg(skin_n[own_edges[:, 0]], skin_n[own_edges[:, 1]])
                     if len(own_edges) else np.array([]))

    # Colour: her texel at each rim vertex against the patch's colour there.
    cache: dict = {}
    hers = _texel(document, skin_material, skin_uv[rim], cache) if len(rim) else None
    ours = _texel(document, proxy_material, patch_uv[pick], cache) if len(rim) else None
    colour = (np.linalg.norm(hers - ours, axis=1) if hers is not None and ours is not None else np.array([]))

    # Weights: hers at each rim vertex against the patch's at the same place (its nearest face's
    # corners, interpolated). Sum of absolute differences per joint: 0 is the same rig, 2 is none
    # in common. The patch at her rim must move as her rim moves.
    weight_l1 = []
    for i, vertex in enumerate(rim):
        tri = patch_f[nearest_face[i]]
        shares = _barycentric(skin_p[vertex], patch_p[tri])
        ours: dict[int, float] = {}
        for corner_vertex, share in zip(tri, shares, strict=True):
            for joint, w in patch_rig[corner_vertex].items():
                ours[joint] = ours.get(joint, 0.0) + w * share
        hers = skin_rig[vertex]
        total_ours, total_hers = sum(ours.values()) or 1.0, sum(hers.values()) or 1.0
        weight_l1.append(sum(abs(ours.get(j, 0.0) / total_ours - hers.get(j, 0.0) / total_hers)
                             for j in set(ours) | set(hers)))

    report = {
        "rimVertices": int(len(rim)),
        "patchVertices": int(len(patch_p)),
        "gapMm": _stats(gap, 1000.0),
        "overlap": {
            "zFightVertices": int((under < ZFIGHT_M).sum()),
            "inFrontOfSkinVertices": int(in_front.sum()),
            "underSkinCm2": round(float(patch_area[face_under].sum()) * 1e4, 1),
            "nearestSkinMm": _stats(under, 1000.0),
        },
        "normals": {"seamDeg": _stats(seam_angle, 1.0, 1), "neighbourDeg": _stats(neighbour, 1.0, 1),
                    "herNeighbourDeg": _stats(own_neighbour, 1.0, 1),
                    "storedVsSurfaceDeg": _stats(stored_vs_surface, 1.0, 1)},
        "colour": {"rgbDistance": _stats(colour, 1.0, 1)},
        "weights": {"seamL1": _stats(np.array(weight_l1), 1.0, 3)},
    }

    if poses:
        posed = {}
        for pose in POSE_TESTS:
            table = _pose_table(document, info, measurements, pose)
            pp = np.vstack([_posed(document, node, primitive, table)[used]
                            for _, node, primitive, used, _ in patch_refs])
            sp = np.vstack([_posed(document, node, primitive, table)[used]
                            for _, node, primitive, used, _ in skin_refs])
            moved, _ = closest_on_triangles(sp[rim], pp[patch_f])
            change = round(float(np.abs(moved - gap).max()) * 1000.0, 2) if len(rim) else None
            posed[pose] = {"gapMm": _stats(moved, 1000.0), "changeMm": change}
        report["posed"] = posed

    report["material"] = _material_diff(skin_material, proxy_material)
    report["tags"] = _tags(document, proxy_parts)
    return report


def _material_diff(skin: dict, proxy: dict) -> dict:
    """Render state the patch does not share with her skin (textures aside: the patch has its own)."""
    def state(m: dict) -> dict:
        mtoon = dict((m.get("extensions") or {}).get("VRMC_materials_mtoon") or {})
        for k in [k for k in mtoon if k.endswith("Texture")]:
            mtoon.pop(k)
        return {"alphaMode": m.get("alphaMode", "OPAQUE"), "alphaCutoff": m.get("alphaCutoff", 0.5)
                if m.get("alphaMode") == "MASK" else None, "doubleSided": bool(m.get("doubleSided")),
                "mtoon": mtoon or None, "unlit": "KHR_materials_unlit" in (m.get("extensions") or {})}
    mine, theirs = state(skin), state(proxy)
    return {"differs": sorted(k for k in mine if mine[k] != theirs[k])}


def _tags(document: GltfDocument, proxy_parts) -> dict:
    tagged = [i for i, m in enumerate(document.meshes)
              if "bodyProxy" in (((m.get("extras") or {}).get("wardrobeForge")) or {})
              or (((m.get("extras") or {}).get("wardrobeForge")) or {}).get("kind") == "bodyProxy"]
    meshes = sorted({mi for _, _, mi, _, _ in proxy_parts})
    own = all(all(_is_proxy(document.materials[p.get("material")]) for p in document.meshes[mi]["primitives"])
              for mi in meshes)
    extras = ((document.gltf.get("extras") or {}).get("wardrobeForge")) or {}
    return {"taggedMeshes": tagged, "patchMeshes": meshes, "patchOnOwnMesh": own,
            "taggedIsPatch": tagged == meshes and own,
            "fileTags": {k: extras.get(k)
                         for k in ("reconstructed", "reconstruction", "reconstructedRegions")}}


__all__ = ["ZFIGHT_M", "closest_on_triangles", "measure_join"]
