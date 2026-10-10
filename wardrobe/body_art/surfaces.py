"""BA2. Her skin, what covers it, and her hair — read from a finished document.

Exposure and projection both start here, on the *assembled* VRM: the new garments,
her own clothes the strip plan kept, and anything the Forge does not recognise are
all in it, exactly as they ship (docs/BODY_ART_PLAN.md §1). Every drawn primitive is
one of four things:

* **body art** — a Forge decal (``extras.wardrobeForge.kind == "bodyArt"``): ignored,
  it is neither skin nor clothing (invariant I7);
* **covering** — a Forge garment, anything the garment inventory recognises as
  clothing, and anything else drawn that is not her skin. Clothes win: a mesh the
  Forge cannot name is assumed to cover, never assumed to be skin;
* **skin** — the primitive(s) whose material says so (``Body``, ``…_Body_00_SKIN``),
  without what hangs from her head; when no material says so, the largest
  remaining skinned primitive;
* **head** — whatever moves mostly with her head: hair, face. Not a covering (hair
  moves), reported where it lies over a tattoo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from wardrobe.engines.geometry_checks import _head_attached_nodes
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.garment_inventory import garment_inventory

_SKIN = re.compile(r"skin|\bbody\b|_body_", re.IGNORECASE)


@dataclass
class Skin:
    """Her skin, concatenated over its primitives, in the rest pose."""

    positions: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    normals: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    joints: np.ndarray = field(default_factory=lambda: np.zeros((0, 4), dtype=np.int64))
    weights: np.ndarray = field(default_factory=lambda: np.zeros((0, 4)))
    triangles: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), dtype=np.int64))
    #: Per triangle: the mesh node it is drawn by and that node's skin.
    node: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    skin: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))

    def corners(self, index: np.ndarray | None = None) -> np.ndarray:
        tris = self.triangles if index is None else self.triangles[index]
        return self.positions[tris]


@dataclass
class Surfaces:
    skin: Skin
    #: ``(C, 3, 3)`` triangles of everything that covers her, and a label index per triangle.
    cover: np.ndarray
    cover_owner: np.ndarray
    owners: list[str]
    #: ``(H, 3, 3)`` triangles that hang from her head.
    head: np.ndarray


def _positions(document: GltfDocument, node_index: int, primitive: dict) -> np.ndarray:
    points = document.read_accessor(primitive["attributes"]["POSITION"]).astype(np.float64)[:, :3]
    node = document.nodes[node_index]
    if "skin" in node:
        return points  # a skinned mesh's positions are its rest pose
    matrix = document.world_matrices()[node_index]
    return (np.hstack([points, np.ones((points.shape[0], 1))]) @ matrix.T)[:, :3]


def _triangles(document: GltfDocument, primitive: dict, count: int) -> np.ndarray:
    if primitive.get("mode", 4) != 4:
        return np.zeros((0, 3), dtype=np.int64)
    if primitive.get("indices") is None:
        indices = np.arange(count - count % 3)
    else:
        indices = document.read_accessor(primitive["indices"]).astype(np.int64).reshape(-1)
    indices = indices[: indices.size // 3 * 3].reshape(-1, 3)
    return indices[(indices < count).all(axis=1)]


def _vertex_normals(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    normals = np.zeros_like(points)
    if triangles.size:
        face = np.cross(
            points[triangles[:, 1]] - points[triangles[:, 0]],
            points[triangles[:, 2]] - points[triangles[:, 0]],
        )
        for k in range(3):
            np.add.at(normals, triangles[:, k], face)
    return normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)


def _head_mask(document: GltfDocument, node: dict, primitive: dict, head: set[int], count: int) -> np.ndarray:
    """Per vertex: does the joint with the largest weight belong to her head?"""
    attributes = primitive.get("attributes", {})
    skins = document.gltf.get("skins") or []
    if not head or node.get("skin") is None or "JOINTS_0" not in attributes or "WEIGHTS_0" not in attributes:
        return np.zeros(count, dtype=bool)
    joint_nodes = np.asarray(skins[node["skin"]].get("joints") or [], dtype=np.int64)
    joints = document.read_accessor(attributes["JOINTS_0"]).astype(np.int64)
    weights = document.read_accessor(attributes["WEIGHTS_0"]).astype(np.float64)
    if joints.shape[0] != count or joint_nodes.size == 0:
        return np.zeros(count, dtype=bool)
    dominant = joint_nodes[np.clip(joints[np.arange(count), weights.argmax(axis=1)], 0, joint_nodes.size - 1)]
    return np.isin(dominant, np.fromiter(head, dtype=np.int64))


def read_surfaces(document: GltfDocument) -> Surfaces:
    clothing = {(g.mesh, g.primitive): g.slot for g in garment_inventory(document)}
    head_nodes = _head_attached_nodes(document)
    materials = document.materials

    candidates, cover, cover_owner, owners, head_tris = [], [], [], [], []

    def owner(label: str) -> int:
        if label not in owners:
            owners.append(label)
        return owners.index(label)

    for node_index in document.mesh_nodes():
        node = document.nodes[node_index]
        tag = (
            ((node.get("extras") or {}).get("wardrobeForge") or {})
            if isinstance(node.get("extras"), dict)
            else {}
        )
        if tag.get("kind") == "bodyArt":
            continue
        for p_index, primitive in enumerate(document.meshes[node["mesh"]].get("primitives", [])):
            if "POSITION" not in primitive.get("attributes", {}):
                continue
            points = _positions(document, node_index, primitive)
            triangles = _triangles(document, primitive, points.shape[0])
            if triangles.size == 0:
                continue
            m = primitive.get("material")
            name = str(materials[m].get("name") or "") if m is not None and m < len(materials) else ""
            on_head = _head_mask(document, node, primitive, head_nodes, points.shape[0])
            head_tri = on_head[triangles].all(axis=1)
            if head_tri.any():
                head_tris.append(points[triangles[head_tri]])
            rest = triangles[~head_tri]
            if rest.size == 0:
                continue
            if tag.get("kind") == "garment":
                label = f"forge:{tag.get('slot') or 'garment'}"
            elif (node["mesh"], p_index) in clothing:
                label = clothing[(node["mesh"], p_index)]
            else:
                label = None
            if label is not None:
                cover.append(points[rest])
                cover_owner.append(np.full(len(rest), owner(label)))
            else:
                candidates.append((node_index, primitive, points, rest, name))

    named = [c for c in candidates if _SKIN.search(c[4]) and "skin" in document.nodes[c[0]]]
    if not named:
        skinned = [c for c in candidates if "skin" in document.nodes[c[0]]]
        named = [max(skinned, key=lambda c: len(c[3]))] if skinned else []
    chosen = {id(c) for c in named}
    for c in candidates:
        if id(c) not in chosen:  # drawn, not skin, not recognised: it covers her
            cover.append(c[2][c[3]])
            cover_owner.append(np.full(len(c[3]), owner(c[4] or "unrecognised mesh")))

    skin = Skin()
    parts = {
        "positions": [],
        "normals": [],
        "joints": [],
        "weights": [],
        "triangles": [],
        "node": [],
        "skin": [],
    }
    offset = 0
    for node_index, primitive, points, triangles, _name in named:
        attributes = primitive["attributes"]
        normals = (
            document.read_accessor(attributes["NORMAL"]).astype(np.float64)[:, :3]
            if "NORMAL" in attributes
            else _vertex_normals(points, triangles)
        )
        normals = normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
        joints = document.read_accessor(attributes["JOINTS_0"]).astype(np.int64)
        weights = document.read_accessor(attributes["WEIGHTS_0"]).astype(np.float64)
        width = min(joints.shape[1], 4)
        j4 = np.zeros((points.shape[0], 4), dtype=np.int64)
        w4 = np.zeros((points.shape[0], 4))
        j4[:, :width], w4[:, :width] = joints[:, :width], weights[:, :width]
        parts["positions"].append(points)
        parts["normals"].append(normals)
        parts["joints"].append(j4)
        parts["weights"].append(w4)
        parts["triangles"].append(triangles + offset)
        parts["node"].append(np.full(len(triangles), node_index))
        parts["skin"].append(np.full(len(triangles), document.nodes[node_index]["skin"]))
        offset += points.shape[0]
    if named:
        skin = Skin(**{k: np.concatenate(v) for k, v in parts.items()})

    return Surfaces(
        skin=skin,
        cover=np.concatenate(cover) if cover else np.zeros((0, 3, 3)),
        cover_owner=np.concatenate(cover_owner) if cover_owner else np.zeros(0, dtype=np.int64),
        owners=owners,
        head=np.concatenate(head_tris) if head_tris else np.zeros((0, 3, 3)),
    )


__all__ = ["Skin", "Surfaces", "read_surfaces"]
