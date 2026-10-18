"""BS2. Her skin, read out of the VRM as surfaces the body-surface stage can work on.

The body surface is built on *her skin*, not on whatever the file contains: not on her own
clothes (``garment_inventory``), not on a Forge garment or a tattoo already on her, not on
anything that moves with her head (hair reaching her thighs was once read as her hips —
``geometry_checks.body_points``). Her skin is chosen by material, the way
``painted_clothing.skin_surface`` chooses it, but without needing a texture: a calibration
body or a fit form has none, and still has a skin.

The result is grouped by POSITION accessor, because that is the unit a glTF morph target
applies to. VRoid's Body mesh keeps skin, tops and shoes as primitives over *one* shared
position buffer; a displacement is computed once per buffer, on the skin triangles only, and
every primitive using that buffer gets the same target.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from wardrobe.engines.geometry_checks import _head_attached_nodes, _moved_by
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.garment_inventory import garment_inventory

#: A torso vertex is within this of her vertical axis (the same reach painted_clothing uses).
TORSO_RADIUS_M = 0.3


@dataclass
class SkinPart:
    """One POSITION buffer of her skin: its rest positions and the skin triangles over it."""

    accessor: int
    #: (mesh, primitive) pairs drawing skin from this buffer.
    primitives: list[tuple[int, int]]
    positions: np.ndarray  # (N, 3) float64, the buffer as stored (skinned: bind space)
    triangles: np.ndarray  # (M, 3) int64, skin triangles only
    material: int

    @property
    def used(self) -> np.ndarray:
        return np.unique(self.triangles)


def skin_parts(document: GltfDocument, bones: dict) -> list[SkinPart]:
    """Her skin, per position buffer. Empty when no skinned skin can be found."""
    hips, neck = bones.get("hips"), bones.get("neck")
    if hips is None or neck is None:
        return []
    legs = bones.get("leftUpperLeg", hips)
    low, high = float(legs[1]) - 0.08, float(neck[1]) - 0.02
    axis_x, axis_z = float(hips[0]), float(hips[2])
    clothing = {(g.mesh, g.primitive) for g in garment_inventory(document)}
    head_nodes = _head_attached_nodes(document)
    materials = document.gltf.get("materials") or []
    candidates: dict[int, list] = {}
    torso: dict[int, int] = {}
    for node_index in document.mesh_nodes():
        node = document.nodes[node_index]
        if "skin" not in node:
            continue  # a body that does not deform is not one a garment is fitted to
        extras = node.get("extras") if isinstance(node.get("extras"), dict) else {}
        if (extras.get("wardrobeForge") or {}).get("kind") in ("garment", "bodyArt"):
            continue
        mesh = document.meshes[node["mesh"]]
        for primitive_index, primitive in enumerate(mesh.get("primitives", [])):
            if (node["mesh"], primitive_index) in clothing or primitive.get("mode", 4) != 4:
                continue
            material_index = primitive.get("material")
            if material_index is None or "hair" in str(materials[material_index].get("name", "")).lower():
                continue
            position = primitive.get("attributes", {}).get("POSITION")
            if position is None or primitive.get("indices") is None:
                continue
            points = document.read_accessor(position).astype(np.float64)[:, :3]
            indices = document.read_accessor(primitive["indices"]).astype(np.int64).reshape(-1)
            triangles = indices[: indices.size // 3 * 3].reshape(-1, 3)
            triangles = triangles[(triangles < points.shape[0]).all(axis=1)]
            on_head = (_moved_by(document, node, primitive, head_nodes, points.shape[0])
                       if head_nodes else None)
            if on_head is not None:
                triangles = triangles[~on_head[triangles].any(axis=1)]
            if not len(triangles):
                continue
            used = np.unique(triangles)
            r = np.hypot(points[used, 0] - axis_x, points[used, 2] - axis_z)
            inside = (points[used, 1] > low) & (points[used, 1] < high) & (r < TORSO_RADIUS_M)
            torso[material_index] = torso.get(material_index, 0) + int(inside.sum())
            candidates.setdefault(material_index, []).append((node["mesh"], primitive_index, position, points,
                                                              triangles))
    if not torso or max(torso.values()) == 0:
        return []
    skin = max(torso, key=torso.get)
    parts: dict[int, SkinPart] = {}
    for mesh_index, primitive_index, position, points, triangles in candidates[skin]:
        part = parts.get(position)
        if part is None:
            parts[position] = SkinPart(position, [(mesh_index, primitive_index)], points, triangles, skin)
        else:
            part.primitives.append((mesh_index, primitive_index))
            part.triangles = np.vstack([part.triangles, triangles])
    return list(parts.values())


__all__ = ["SkinPart", "skin_parts"]
