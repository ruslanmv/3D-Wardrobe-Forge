"""Garments shade like the avatar's own clothes: MToon borrowed, never invented."""

from __future__ import annotations

from tests.vroid_support import dress_like_vroid
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.merge import GarmentMaterial, _linear_to_srgb, borrow_toon_shading

RED_LINEAR = (0.45, 0.02, 0.03, 1.0)


def add_garment_material(document: GltfDocument, info) -> int:
    index = document.add_material(GarmentMaterial(name="Garment", base_color=RED_LINEAR).to_gltf())
    block = document.extension("VRM")
    if block is not None:
        block["materialProperties"].append({"name": "Garment", "shader": "VRM_USE_GLTFSHADER"})
    return index


def test_vrm0_borrows_the_cloth_material_not_the_skin():
    document = GltfDocument.from_bytes(
        dress_like_vroid(build_vrm(CALIBRATION_BODIES[1], spec="VRM0"), slots=("Tops",), mtoon=True)
    )
    info = inspect_document(document)
    index = add_garment_material(document, info)

    assert borrow_toon_shading(document, info, index, RED_LINEAR) == "F00_000_01_Tops_01_CLOTH"
    entry = document.extension("VRM")["materialProperties"][index]
    assert entry["shader"] == "VRM/MToon"
    assert entry["textureProperties"] == {}  # the avatar's textures map its UVs, not ours
    assert "_ALPHATEST_ON" not in entry["keywordMap"] and "_NORMALMAP" not in entry["keywordMap"]
    assert entry["keywordMap"]["MTOON_OUTLINE_WIDTH_WORLD"] is True  # its outline style is kept
    assert entry["floatProperties"]["_ShadeToony"] == 0.9  # and its toon ramp
    assert entry["floatProperties"]["_BlendMode"] == 0 and entry["renderQueue"] == 2000
    # VRM 0.x colours are gamma-encoded; the plan's are linear.
    assert entry["vectorProperties"]["_Color"][:3] == [_linear_to_srgb(c) for c in RED_LINEAR[:3]]
    assert entry["vectorProperties"]["_ShadeColor"][0] < entry["vectorProperties"]["_Color"][0]


def test_vrm1_borrows_the_extension_without_its_textures():
    document = GltfDocument.from_bytes(
        dress_like_vroid(build_vrm(CALIBRATION_BODIES[1], spec="VRM1"), slots=("Tops",), mtoon=True)
    )
    info = inspect_document(document)
    index = add_garment_material(document, info)

    assert borrow_toon_shading(document, info, index, RED_LINEAR) == "F00_000_01_Tops_01_CLOTH"
    mtoon = document.materials[index]["extensions"]["VRMC_materials_mtoon"]
    assert not any(key.endswith("Texture") for key in mtoon)
    assert mtoon["shadingToonyFactor"] == 0.9
    assert mtoon["shadeColorFactor"][0] < RED_LINEAR[0]
    assert "VRMC_materials_mtoon" in document.gltf["extensionsUsed"]


def test_a_model_without_mtoon_keeps_its_pbr_garment(vrm0_bytes):
    document = GltfDocument.from_bytes(vrm0_bytes)
    info = inspect_document(document)
    index = add_garment_material(document, info)
    assert borrow_toon_shading(document, info, index, RED_LINEAR) is None
    assert document.extension("VRM")["materialProperties"][index]["shader"] == "VRM_USE_GLTFSHADER"
