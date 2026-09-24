"""Garments shade like the avatar's own clothes: MToon borrowed, never invented."""

from __future__ import annotations

import pytest

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


# ----------------------------------------------------------------------
# the garment's own finish, alpha and texture win over what it borrowed
# ----------------------------------------------------------------------
def dressed_with(spec: str, material: GarmentMaterial):
    from wardrobe.vrm.merge import _register_vrm0_material, apply_toon_finish

    document = GltfDocument.from_bytes(
        dress_like_vroid(build_vrm(CALIBRATION_BODIES[1], spec=spec), slots=("Tops",), mtoon=True)
    )
    info = inspect_document(document)
    index = material.add_to(document)
    _register_vrm0_material(document, info, index)
    assert borrow_toon_shading(document, info, index, material.base_color) is not None
    apply_toon_finish(document, info, index, material)
    return document, index


def material_for(prompt: str) -> GarmentMaterial:
    from pathlib import Path

    from wardrobe.domain.garments import TemplateCatalog
    from wardrobe.domain.looks import OutfitRequest
    from wardrobe.pipeline.plan_outfit import plan_outfit

    catalog = TemplateCatalog.from_directory(Path(__file__).resolve().parents[2] / "assets/garment_templates")
    return GarmentMaterial.from_plan("Garment", plan_outfit(OutfitRequest(prompt=prompt), catalog).material)


def test_vrm0_latex_keeps_her_toon_ramp_and_gains_a_highlight():
    document, index = dressed_with("VRM0", material_for("black latex bodycon mini dress"))
    entry = document.extension("VRM")["materialProperties"][index]
    assert entry["floatProperties"]["_ShadeToony"] == 0.9  # still hers
    assert entry["floatProperties"]["_BlendMode"] == 0 and entry["renderQueue"] == 2000
    matcap = entry["textureProperties"]["_SphereAdd"]
    assert document.gltf["samplers"][document.gltf["textures"][matcap]["sampler"]]["wrapS"] == 33071
    assert entry["vectorProperties"]["_RimColor"][0] > 0.3


def test_vrm0_sheer_lace_blends_without_an_outline():
    document, index = dressed_with("VRM0", material_for("sheer black lace bodysuit"))
    entry = document.extension("VRM")["materialProperties"][index]
    floats, keywords = entry["floatProperties"], entry["keywordMap"]
    assert floats["_BlendMode"] == 2 and floats["_ZWrite"] == 0 and entry["renderQueue"] == 3000
    assert keywords["_ALPHABLEND_ON"] and keywords["MTOON_OUTLINE_NONE"]
    assert not any(k.startswith("MTOON_OUTLINE_WIDTH") for k in keywords)
    assert entry["vectorProperties"]["_Color"][3] == pytest.approx(0.45)
    assert entry["textureProperties"]["_MainTex"] == entry["textureProperties"]["_ShadeTexture"]
    assert entry["tagMap"] == {"RenderType": "Transparent"} and floats["_CullMode"] == 0


def test_vrm0_fishnet_is_cut_out():
    document, index = dressed_with("VRM0", material_for("black fishnet thigh-highs"))
    entry = document.extension("VRM")["materialProperties"][index]
    assert entry["floatProperties"]["_BlendMode"] == 1 and entry["floatProperties"]["_Cutoff"] == 0.5
    assert entry["keywordMap"]["_ALPHATEST_ON"] and entry["renderQueue"] == 2450


def test_vrm1_metallic_tints_its_highlight_and_stays_opaque():
    document, index = dressed_with("VRM1", material_for("shiny gold mini dress"))
    target = document.materials[index]
    mtoon = target["extensions"]["VRMC_materials_mtoon"]
    assert target["alphaMode"] == "OPAQUE" and "matcapTexture" in mtoon
    rim = mtoon["parametricRimColorFactor"]
    assert rim[0] > rim[2]  # gold, not white
