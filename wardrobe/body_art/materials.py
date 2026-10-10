"""BA4. The decal as glTF: its texture, its MToon material, its mesh and its node — all appended.

Everything here *adds* to the document (invariant I5): an image, a clamped texture, a
material, accessors, a mesh and a node. Nothing that was there is changed, with two
bookkeeping exceptions every Forge garment makes too — VRM 0.x ``materialProperties``
must stay aligned with ``materials``, and a new mesh gets a first-person annotation —
and both only append.

The node draws with the body's own ``skin``: no new joints, no inverse bind matrices.
The material borrows the avatar's toon shading from her own MToon, as garments do, so the
ink is lit like the skin it is on, and is transparent without an outline.
"""

from __future__ import annotations

import numpy as np

from wardrobe.body_art.project import Decal
from wardrobe.vrm.document import ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER, GltfDocument
from wardrobe.vrm.inspect import VrmInfo
from wardrobe.vrm.merge import (
    GarmentMaterial,
    _register_first_person,
    _register_vrm0_material,
    apply_toon_finish,
    borrow_toon_shading,
)

#: The material name's prefix. Matches neither garment-inventory pattern (``_Tops_01_CLOTH``,
#: ``[Forge_Tops_01_CLOTH]``), so a decal is never mistaken for clothing.
PREFIX = "[ForgeBodyArt]"


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def add_decal(
    document: GltfDocument,
    info: VrmInfo,
    decal: Decal,
    *,
    texture_png: bytes,
    uv_scale: np.ndarray,
    uv_offset: np.ndarray,
    ink_srgb: tuple[float, float, float],
    opacity: float,
    name: str,
    tag: dict,
) -> int:
    """Append the decal; return its node index."""
    image = document.add_image(texture_png, name=f"{PREFIX} {name}")
    texture = document.add_texture(image, repeat=False)
    ink = tuple(_srgb_to_linear(c) for c in ink_srgb)
    material = GarmentMaterial(
        name=f"{PREFIX} {name}",
        base_color=(*ink, float(opacity)),
        metallic=0.0,
        roughness=0.9,
        double_sided=False,
        alpha_mode="blend",
        texture_coloured=False,
    )
    material.texture_indices = {"baseColor": texture}
    material_index = document.add_material(material.to_gltf())
    _register_vrm0_material(document, info, material_index)
    if borrow_toon_shading(document, info, material_index, material.base_color) is not None:
        apply_toon_finish(document, info, material_index, material)

    uvs = decal.uvs.astype(np.float64) * uv_scale + uv_offset
    attributes = {
        "POSITION": document.add_accessor(decal.positions, target=ARRAY_BUFFER, include_bounds=True),
        "NORMAL": document.add_accessor(decal.normals, target=ARRAY_BUFFER),
        "TEXCOORD_0": document.add_accessor(uvs.astype(np.float32), target=ARRAY_BUFFER),
        "JOINTS_0": document.add_accessor(decal.joints, target=ARRAY_BUFFER),
        "WEIGHTS_0": document.add_accessor(decal.weights, target=ARRAY_BUFFER),
    }
    indices = document.add_accessor(decal.indices.reshape(-1, 1), target=ELEMENT_ARRAY_BUFFER)
    mesh = document.add_mesh(
        [{"attributes": attributes, "indices": indices, "material": material_index, "mode": 4}],
        name=f"{PREFIX} {name}",
    )
    node = document.add_node(
        {"name": f"{PREFIX} {name}", "mesh": mesh, "skin": decal.skin, "extras": {"wardrobeForge": tag}}
    )
    _register_first_person(document, info, node, mesh)
    return node


def remove_decals(document: GltfDocument, placements: set[str]) -> list[str]:
    """Take off Forge body art at ``placements`` — and nothing that is not Forge body art (I6)."""
    removed = []
    for node in document.nodes:
        tag = (
            ((node.get("extras") or {}).get("wardrobeForge") or {})
            if isinstance(node.get("extras"), dict)
            else {}
        )
        if tag.get("kind") == "bodyArt" and tag.get("placement") in placements and "mesh" in node:
            node.pop("mesh", None)
            node.pop("skin", None)
            removed.append(str(tag.get("placement")))
    document.invalidate_cache()
    return removed


__all__ = ["PREFIX", "add_decal", "remove_decals"]
