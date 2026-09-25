"""Calibration avatars dressed the way VRoid Studio dresses its exports.

The suite's avatars are generated, never shipped, and a generated body wears
nothing. Replacement and toon shading both depend on how a VRoid export is laid
out — each outfit slot its own primitive with a ``…_<Slot>_01_CLOTH`` material, and
MToon materials throughout — so this adds exactly that to a calibration body:
one primitive per slot, sharing the body's own geometry, so there is something
real to remove and something real to borrow shading from.
"""

from __future__ import annotations

from wardrobe.vrm.document import GltfDocument

VRM0 = "VRM"


def _mtoon_vrm0(name: str) -> dict:
    return {
        "name": name,
        "shader": "VRM/MToon",
        "renderQueue": 2450,
        "floatProperties": {"_ShadeShift": -0.4, "_ShadeToony": 0.9, "_OutlineWidth": 0.08, "_BlendMode": 1},
        "vectorProperties": {
            "_Color": [1, 1, 1, 1],
            "_ShadeColor": [0.8, 0.8, 0.8, 1],
            "_OutlineColor": [0.2, 0.1, 0.1, 1],
            "_MainTex": [0, 0, 1, 1],
        },
        "textureProperties": {"_MainTex": 0, "_BumpMap": 0},
        "keywordMap": {"_ALPHATEST_ON": True, "_NORMALMAP": True, "MTOON_OUTLINE_WIDTH_WORLD": True},
        "tagMap": {"RenderType": "TransparentCutout"},
    }


def _mtoon_vrm1() -> dict:
    return {
        "specVersion": "1.0",
        "shadingShiftFactor": -0.4,
        "shadingToonyFactor": 0.9,
        "outlineWidthMode": "worldCoordinates",
        "outlineWidthFactor": 0.0008,
        "shadeColorFactor": [0.8, 0.8, 0.8],
        "shadeMultiplyTexture": {"index": 0},
        "rimMultiplyTexture": {"index": 0},
    }


def dress_like_vroid(vrm_bytes: bytes, *, slots: tuple[str, ...] = ("Tops", "Bottoms"), mtoon: bool = False) -> bytes:
    """Return ``vrm_bytes`` wearing one VRoid-style cloth primitive per slot."""
    document = GltfDocument.from_bytes(vrm_bytes)
    body_mesh = document.meshes[0]
    body = body_mesh["primitives"][0]
    vrm0 = document.extension(VRM0)

    if mtoon:
        if vrm0 is not None:
            vrm0["materialProperties"][0] = _mtoon_vrm0(document.materials[0].get("name", "Body"))
        else:
            document.materials[0].setdefault("extensions", {})["VRMC_materials_mtoon"] = _mtoon_vrm1()
            document.declare_extension("VRMC_materials_mtoon")

    for slot in slots:
        name = f"F00_000_01_{slot}_01_CLOTH"
        material = {"name": name, "pbrMetallicRoughness": {"baseColorFactor": [0.3, 0.3, 0.4, 1.0]}}
        if mtoon and vrm0 is None:
            material["extensions"] = {"VRMC_materials_mtoon": _mtoon_vrm1()}
        index = document.add_material(material)
        if vrm0 is not None:
            vrm0["materialProperties"].append(
                _mtoon_vrm0(name) if mtoon else {"name": name, "shader": "VRM_USE_GLTFSHADER", "renderQueue": 2000}
            )
        body_mesh["primitives"].append({**body, "material": index})
    return document.to_bytes()


def primitive_materials(vrm_bytes: bytes) -> list[str]:
    document = GltfDocument.from_bytes(vrm_bytes)
    names = [m.get("name", "") for m in document.materials]
    # What she is wearing is what is drawn: a garment taken off earlier in an
    # outfit set stays in the file as a mesh no node references.
    drawn = sorted({node["mesh"] for node in document.nodes if "mesh" in node})
    meshes = [document.meshes[i] for i in drawn]
    return [names[p["material"]] for mesh in meshes for p in mesh["primitives"] if "material" in p]


__all__ = ["dress_like_vroid", "primitive_materials"]
