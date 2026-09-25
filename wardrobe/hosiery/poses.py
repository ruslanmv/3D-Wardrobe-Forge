"""Standing, walking and seated: the poses hosiery is judged in, and skinning points into them.

The rotations are ``POSE_TESTS``'s, with one correction. The pose stress test
rotates the thighs +85° about x for ``sit``, which swings the knees toward -Z.
That is forward for a VRM 0.x avatar and *backward* for a VRM 1.0 one. The
stress test does not care (it measures edge stretch, which is the same either
way), but a strap's tension and a skirt's reveal are nothing but which way the
knee went. So here the leg rotations about x are mirrored for an avatar that
faces +Z. ``POSE_TESTS`` itself is not changed: every existing fit report would
change with it.
"""

from __future__ import annotations

import numpy as np

from wardrobe.engines.geometry_checks import POSE_TESTS, _accumulated_transform

#: The poses a hosiery look is evaluated in, in report order. ``stand`` is the rest pose.
POSES = ("stand", "walk", "sit")

_LEG_BONES = ("leftUpperLeg", "rightUpperLeg", "leftLowerLeg", "rightLowerLeg")


def rotations(pose: str, forward: float) -> dict[str, tuple[float, float, float]]:
    """Bone rotations (degrees) for ``pose``, with knees going the way she faces."""
    if pose == "stand":
        return {}
    base = POSE_TESTS[pose]
    if forward >= 0:  # faces +Z: +x rotation lifts the knee backward; mirror it
        return {bone: ((-rx, ry, rz) if bone in _LEG_BONES else (rx, ry, rz))
                for bone, (rx, ry, rz) in base.items()}
    return dict(base)


def transforms(pose: str | dict, forward: float, pivots: dict[str, np.ndarray],
               bones) -> dict[str, np.ndarray]:
    """World transform (4×4) per bone name for ``pose`` (a name, or a rotation table)."""
    table = rotations(pose, forward) if isinstance(pose, str) else pose
    pivots = {name: np.asarray(p, dtype=np.float64) for name, p in pivots.items()}
    return {name: _accumulated_transform(name, table, pivots) for name in bones}


def skin(points: np.ndarray, bones: list[tuple[str, ...]], weights: list[tuple[float, ...]],
         table: dict[str, np.ndarray]) -> np.ndarray:
    """Linear blend skinning of rest-pose ``points`` with per-point bone names and weights."""
    points = np.asarray(points, dtype=np.float64)
    out = np.zeros_like(points)
    homogeneous = np.hstack([points, np.ones((points.shape[0], 1))])
    for i, (names, ws) in enumerate(zip(bones, weights, strict=True)):
        total = sum(ws) or 1.0
        matrix = sum((w / total) * table.get(name, np.eye(4)) for name, w in zip(names, ws, strict=True))
        if not isinstance(matrix, np.ndarray):
            matrix = np.eye(4)
        out[i] = (matrix @ homogeneous[i])[:3]
    return out


def skin_mesh(positions: np.ndarray, joints: np.ndarray, weights: np.ndarray, segment_names: list[str],
              table: dict[str, np.ndarray]) -> np.ndarray:
    """``skin`` for a bound mesh: joints index ``segment_names``."""
    matrices = np.stack([table.get(name, np.eye(4)) for name in segment_names])
    homogeneous = np.hstack([positions.astype(np.float64), np.ones((positions.shape[0], 1))])
    out = np.zeros((positions.shape[0], 3))
    for slot in range(joints.shape[1]):
        w = weights[:, slot].astype(np.float64)
        if not w.any():
            continue
        j = np.clip(joints[:, slot].astype(int), 0, len(segment_names) - 1)
        out += np.einsum("nij,nj->ni", matrices[j], homogeneous)[:, :3] * w[:, None]
    return out


# ----------------------------------------------------------------------
# posing a whole VRM document with its own skin weights
# ----------------------------------------------------------------------
def node_table(document, info, pose: str, forward: float, pivots: dict) -> dict[int, np.ndarray]:
    """World transform per node for ``pose``: a humanoid bone's own, any other node its bone ancestor's.

    Hair, skirt and bust bones are not humanoid; they ride with the nearest
    humanoid bone above them, which is what a spring-bone rig does at rest.
    """
    by_node = {node: name for name, node in info.humanoid_bones.items()}
    names = list(info.humanoid_bones)
    bone_table = transforms(pose, forward, pivots, names)
    parents = document.parent_map()
    table: dict[int, np.ndarray] = {}
    for index in range(len(document.nodes)):
        cursor, seen = index, set()
        while cursor is not None and cursor not in by_node and cursor not in seen:
            seen.add(cursor)
            cursor = parents.get(cursor)
        table[index] = bone_table.get(by_node.get(cursor), np.eye(4)) if cursor is not None else np.eye(4)
    return table


def posed_primitive(document, node: dict, primitive: dict, table: dict[int, np.ndarray],
                    normals: bool = False):
    """A skinned primitive's positions (and normals) in the pose ``table`` describes, or None."""
    attributes = primitive.get("attributes", {})
    skins = document.gltf.get("skins") or []
    if node.get("skin") is None or "JOINTS_0" not in attributes or "WEIGHTS_0" not in attributes:
        return None
    joint_nodes = skins[node["skin"]].get("joints") or []
    positions = document.read_accessor(attributes["POSITION"]).astype(np.float64)[:, :3]
    joints = document.read_accessor(attributes["JOINTS_0"]).astype(np.int64)
    weights = document.read_accessor(attributes["WEIGHTS_0"]).astype(np.float64)
    matrices = np.stack([table.get(int(j), np.eye(4)) for j in joint_nodes] or [np.eye(4)])
    joints = np.clip(joints, 0, matrices.shape[0] - 1)
    blended = np.einsum("nk,nkij->nij", weights, matrices[joints])
    totals = weights.sum(axis=1)
    blended[totals < 1e-9] = np.eye(4)
    homogeneous = np.hstack([positions, np.ones((positions.shape[0], 1))])
    posed = np.einsum("nij,nj->ni", blended, homogeneous)[:, :3]
    if not normals or "NORMAL" not in attributes:
        return posed, None
    n = document.read_accessor(attributes["NORMAL"]).astype(np.float64)[:, :3]
    n = np.einsum("nij,nj->ni", blended[:, :3, :3], n)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    return posed, n


def _descendants(document, roots: set[int]) -> set[int]:
    found, stack = set(), list(roots)
    while stack:
        index = stack.pop()
        if index in found:
            continue
        found.add(index)
        stack.extend(document.nodes[index].get("children") or [])
    return found


def mirrored(pose: str, forward: float) -> dict[str, tuple[float, float, float]]:
    """``pose`` with left and right swapped: the other leg forward. Walking is judged both ways."""
    swap = {"left": "right", "right": "left"}
    table = rotations(pose, forward)
    out = {}
    for bone, value in table.items():
        for a, b in swap.items():
            if bone.startswith(a):
                out[b + bone[len(a):]] = value
                break
        else:
            out[bone] = value
    return out


def surface_samples(points: np.ndarray, normals: np.ndarray, triangles: np.ndarray,
                    spacing: float) -> tuple[np.ndarray, np.ndarray]:
    """Points spread across each triangle, with the vertex normals interpolated to them."""
    if triangles.size == 0:
        return np.zeros((0, 3)), np.zeros((0, 3))
    a, b, c = (points[triangles[:, i]] for i in range(3))
    na, nb, nc = (normals[triangles[:, i]] for i in range(3))
    longest = np.maximum.reduce([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1),
                                 np.linalg.norm(a - c, axis=1)])
    steps = np.clip(np.ceil(longest / spacing), 1, 16).astype(int)
    out_p, out_n = [], []
    for k in np.unique(steps):
        chosen = steps == k
        grid = np.array([(i / k, j / k) for i in range(k + 1) for j in range(k + 1 - i)], dtype=np.float64)
        u, v = grid[:, 0][None, :, None], grid[:, 1][None, :, None]
        for (pa, pb, pc), out in (((a, b, c), out_p), ((na, nb, nc), out_n)):
            ta, tb, tc = pa[chosen][:, None, :], pb[chosen][:, None, :], pc[chosen][:, None, :]
            out.append((ta + (tb - ta) * u + (tc - ta) * v).reshape(-1, 3))
    p, n = np.vstack(out_p), np.vstack(out_n)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    return p, n


def posed_body(document, info, pose: str, forward: float, pivots: dict, *,
               exclude_bones: frozenset[str] = frozenset(), spacing: float = 0.008,
               region: tuple[np.ndarray, np.ndarray] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Her body's vertices and normals in ``pose``: every skinned mesh except garments and her head's.

    ``exclude_bones`` drops vertices moved mostly by those bones (her arms, for a strap).
    Returned as samples across her surface, ``spacing`` apart, with normals.
    ``region`` (lo, hi) keeps only what lies inside that box once posed.
    """
    from wardrobe.engines.geometry_checks import _head_attached_nodes

    table = node_table(document, info, pose, forward, pivots)
    head = _head_attached_nodes(document)
    excluded_nodes = _descendants(document, {info.humanoid_bones[b] for b in exclude_bones
                                             if b in info.humanoid_bones})
    points, normals = [], []
    skins = document.gltf.get("skins") or []
    for node_index in document.mesh_nodes():
        node = document.nodes[node_index]
        if ((node.get("extras") or {}).get("wardrobeForge") or {}).get("kind") == "garment":
            continue
        for primitive in document.meshes[node["mesh"]].get("primitives", []):
            result = posed_primitive(document, node, primitive, table, normals=True)
            if result is None or result[1] is None:
                continue
            p, n = result
            attributes = primitive["attributes"]
            joint_nodes = np.asarray(skins[node["skin"]].get("joints") or [0])
            joints = document.read_accessor(attributes["JOINTS_0"]).astype(np.int64)
            weights = document.read_accessor(attributes["WEIGHTS_0"]).astype(np.float64)
            dominant = joint_nodes[np.clip(joints[np.arange(joints.shape[0]), weights.argmax(axis=1)], 0,
                                           joint_nodes.size - 1)]
            drop = np.isin(dominant, list(head | excluded_nodes)) if (head or excluded_nodes) else None
            if primitive.get("indices") is None:
                keep = ~drop if drop is not None else np.ones(p.shape[0], dtype=bool)
                points.append(p[keep])
                normals.append(n[keep])
                continue
            triangles = document.read_accessor(primitive["indices"]).astype(np.int64).reshape(-1, 3)
            if drop is not None:
                triangles = triangles[~drop[triangles].any(axis=1)]
            if region is not None:
                inside = np.all((p >= region[0] - 0.05) & (p <= region[1] + 0.05), axis=1)
                triangles = triangles[inside[triangles].any(axis=1)]
            # Across the triangles, not only at the vertices: a low-poly body has a vertex every
            # few centimetres, and a strap's "nearest surface" was then a vertex round the corner.
            sp, sn = surface_samples(p, n, triangles, spacing)
            points.append(sp)
            normals.append(sn)
    if not points:
        return np.zeros((0, 3)), np.zeros((0, 3))
    points, normals = np.vstack(points), np.vstack(normals)
    if region is not None:
        inside = np.all((points >= region[0]) & (points <= region[1]), axis=1)
        points, normals = points[inside], normals[inside]
    return points, normals


__all__ = ["POSES", "node_table", "posed_body", "posed_primitive", "rotations", "skin", "skin_mesh",
           "transforms"]
