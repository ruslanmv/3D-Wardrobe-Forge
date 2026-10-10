"""DC2. Her surface as it is drawn: what an alpha-cut texture hides is not there.

VRoid clothes are cut out of their textures (``alphaMode: MASK``). AvatarSample A's Bottoms
carries a whole sheet of triangles round her shins and behind her heels that its texture
never shows — at every height, from 2 cm to 24 cm off her leg, as dense as her leg itself.
A boot cut round "her body" read that sheet as her calf and came out a drum. Here a
triangle counts only where all three corners are visible: the texture's alpha at each
corner's UV, times the material's own alpha, against the material's cutoff.

Used by the boots only. ``wardrobe.engines.geometry_checks.body_points`` keeps reading every
drawn triangle, as every fit made so far was measured against it.
"""

from __future__ import annotations

import io

import numpy as np

from wardrobe.vrm.document import GltfDocument


def _texture_alpha(document: GltfDocument, texture: int, cache: dict) -> np.ndarray | None:
    if texture in cache:
        return cache[texture]
    alpha = None
    try:
        from PIL import Image

        source = document.gltf["textures"][texture].get("source")
        image = document.gltf["images"][source]
        view = document.gltf["bufferViews"][image["bufferView"]]
        start = view.get("byteOffset", 0)
        data = bytes(document.binary[start : start + view["byteLength"]])
        picture = Image.open(io.BytesIO(data))
        if picture.mode in ("RGBA", "LA", "P"):
            alpha = np.asarray(picture.convert("RGBA"))[:, :, 3].astype(np.float32) / 255.0
    except (KeyError, IndexError, OSError, ValueError, TypeError):  # an odd texture: count it opaque
        alpha = None
    cache[texture] = alpha
    return alpha


def visible_vertices(document: GltfDocument, primitive: dict, cache: dict) -> np.ndarray | None:
    """Per vertex of ``primitive``: does its material show it? None when the whole thing shows."""
    material_index = primitive.get("material")
    if material_index is None:
        return None
    material = document.gltf["materials"][material_index]
    mode = material.get("alphaMode", "OPAQUE")
    if mode == "OPAQUE":
        return None
    pbr = material.get("pbrMetallicRoughness") or {}
    factor = float((pbr.get("baseColorFactor") or [1, 1, 1, 1])[3])
    cutoff = float(material.get("alphaCutoff", 0.5)) if mode == "MASK" else 0.1
    texture = (pbr.get("baseColorTexture") or {}).get("index")
    attributes = primitive.get("attributes", {})
    count = int(document.gltf["accessors"][attributes["POSITION"]]["count"])
    if texture is None or "TEXCOORD_0" not in attributes:
        return np.full(count, factor >= cutoff)
    alpha = _texture_alpha(document, texture, cache)
    if alpha is None:
        return np.full(count, factor >= cutoff)
    uv = document.read_accessor(attributes["TEXCOORD_0"]).astype(np.float64)
    h, w = alpha.shape
    px = np.clip((uv[:, 0] % 1.0) * w, 0, w - 1).astype(int)
    py = np.clip((uv[:, 1] % 1.0) * h, 0, h - 1).astype(int)
    return alpha[py, px] * factor >= cutoff


def drawn_surface(document: GltfDocument, *, y_max: float, spacing: float = 0.006) -> np.ndarray:
    """Samples across every visible triangle of every skinned mesh below ``y_max`` (not her head's)."""
    from wardrobe.engines.geometry_checks import _head_attached_nodes
    from wardrobe.hosiery.poses import surface_samples

    head = _head_attached_nodes(document)
    skins = document.gltf.get("skins") or []
    cache: dict = {}
    out = []
    for node_index in document.mesh_nodes():
        node = document.nodes[node_index]
        if ((node.get("extras") or {}).get("wardrobeForge") or {}).get("kind") == "bodyArt":
            continue
        if node.get("skin") is None or node["skin"] >= len(skins):
            continue
        joint_nodes = np.asarray(skins[node["skin"]].get("joints") or [0])
        for primitive in document.meshes[node["mesh"]].get("primitives", []):
            attributes = primitive.get("attributes", {})
            if primitive.get("indices") is None or "POSITION" not in attributes:
                continue
            positions = document.read_accessor(attributes["POSITION"]).astype(np.float64)[:, :3]
            triangles = document.read_accessor(primitive["indices"]).astype(np.int64).reshape(-1, 3)
            keep = positions[triangles][:, :, 1].min(axis=1) < y_max
            shown = visible_vertices(document, primitive, cache)
            if shown is not None:
                keep &= shown[triangles].all(axis=1)
            if head and "JOINTS_0" in attributes and "WEIGHTS_0" in attributes:
                joints = document.read_accessor(attributes["JOINTS_0"]).astype(np.int64)
                weights = document.read_accessor(attributes["WEIGHTS_0"]).astype(np.float64)
                dominant = joint_nodes[
                    np.clip(
                        joints[np.arange(joints.shape[0]), weights.argmax(axis=1)], 0, joint_nodes.size - 1
                    )
                ]
                keep &= ~np.isin(dominant, list(head))[triangles].any(axis=1)
            triangles = triangles[keep]
            if not triangles.size:
                continue
            normals = np.zeros_like(positions)
            normals[:, 1] = 1.0
            points, _ = surface_samples(positions, normals, triangles, spacing)
            out.append(np.vstack([points, positions[np.unique(triangles)]]))
    return np.vstack(out) if out else np.zeros((0, 3))


__all__ = ["drawn_surface", "visible_vertices"]
