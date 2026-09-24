"""The material layer: vocabulary, generated textures, and what each engine is handed."""

from __future__ import annotations

import numpy as np
import pytest

from wardrobe.domain.looks import OutfitRequest
from wardrobe.geometry.procedural import Ring, _ellipse_perimeter, loft, sweep
from wardrobe.materials.png import decode_png, encode_png, png_size
from wardrobe.materials.textures import matcap, pattern_texture
from wardrobe.pipeline.plan_outfit import plan_outfit
from wardrobe.vrm.merge import GarmentMaterial


def plan(prompt: str, catalog, **overrides):
    return plan_outfit(OutfitRequest(prompt=prompt, **overrides), catalog)


# ----------------------------------------------------------------------
# textures
# ----------------------------------------------------------------------
def test_png_round_trips():
    pixels = np.random.default_rng(1).integers(0, 256, (5, 7, 4), dtype=np.uint8)
    data = encode_png(pixels)
    assert png_size(data) == (7, 5)
    np.testing.assert_array_equal(decode_png(data), pixels)


def alpha(name: str, **kwargs) -> np.ndarray:
    return decode_png(pattern_texture(name, **kwargs))[..., 3] / 255.0


def test_fishnet_and_lace_are_mostly_holes_and_threads():
    for name in ("fishnet", "lace"):
        a = alpha(name)
        assert (a < 0.5).mean() > 0.4, name  # holes
        assert (a > 0.5).mean() > 0.05, name  # threads


def test_lined_lace_and_the_other_patterns_are_opaque():
    assert alpha("lace", lined=True).min() == 1.0
    for name in ("sequin", "stripes", "dots", "gingham", "plaid"):
        assert alpha(name).min() == 1.0, name


def test_a_two_colour_pattern_carries_both_colours():
    rgb = decode_png(pattern_texture("stripes", (1.0, 0.0, 0.0), (1.0, 1.0, 1.0)))[..., :3]
    assert (rgb == [255, 0, 0]).all(axis=2).any() and (rgb == [255, 255, 255]).all(axis=2).any()


def test_textures_are_deterministic():
    assert pattern_texture("sequin") == pattern_texture.__wrapped__("sequin")
    assert matcap("latex", 0.9) == matcap.__wrapped__("latex", 0.9)


@pytest.mark.parametrize("style", ["gloss", "latex", "satin", "metal", "sparkle"])
def test_a_matcap_adds_nothing_outside_the_sphere_and_something_inside(style):
    rgb = decode_png(matcap(style, 0.8))[..., :3].astype(int)
    assert rgb[0, 0].sum() == 0 and rgb[-1, -1].sum() == 0
    assert rgb.max() > 100


def test_the_seam_is_at_her_back_whichever_way_she_faces():
    for front in (1.0, -1.0):
        mesh = loft([Ring(0.0, 0.1, 0.08), Ring(0.3, 0.1, 0.08)], segments=16, front=front)
        # The first and last vertex of each ring coincide: that is the seam.
        assert mesh.positions[0, 2] == pytest.approx(-0.08 * front, abs=1e-6)


def test_uvs_are_metres_of_fabric():
    mesh = loft([Ring(0.0, 0.1, 0.08), Ring(0.3, 0.1, 0.08)], segments=16)
    perimeter = _ellipse_perimeter(0.1, 0.08)
    # Measured from her front centre, so the back seam is at ±half the perimeter.
    assert mesh.uvs[:, 0].min() == pytest.approx(-perimeter / 2, rel=1e-4)
    assert mesh.uvs[:, 0].max() == pytest.approx(perimeter / 2, rel=1e-4)
    front = np.argmin(np.abs(mesh.uvs[:, 0]))
    assert mesh.positions[front, 2] > 0.07  # u = 0 is at +Z, her front on a VRM 1.0 rig
    assert mesh.uvs[:, 1].max() == pytest.approx(0.3, rel=1e-4)
    tube = sweep(np.array([[0.0, 0.0, 0.0], [0.0, 0.5, 0.0]]), [0.02, 0.02], segments=8)
    assert tube.uvs[:, 1].max() == pytest.approx(0.5, rel=1e-4)


# ----------------------------------------------------------------------
# planning
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("prompt", "finish"),
    [
        ("black latex bodycon mini dress", "latex"),
        ("red pvc skirt", "latex"),
        ("shiny black mini skirt", "gloss"),
        ("shiny silver mini dress", "metallic"),  # a shiny metal colour is metal
        ("champagne satin slip dress", "satin"),
        ("pink sequin bodysuit", "sequin"),
        ("navy cotton tee", "matte"),
    ],
)
def test_finish_words(template_catalog, prompt, finish):
    assert plan(prompt, template_catalog).material.finish == finish


def test_a_second_colour_is_the_patterns(template_catalog):
    material = plan("red and white striped bikini top", template_catalog).material
    assert material.color_name == "red" and material.pattern == "stripes"
    assert material.pattern_color is not None and min(material.pattern_color[:3]) > 0.8


def test_navy_blue_is_one_colour_not_two(template_catalog):
    material = plan("navy blue plaid pleated mini skirt", template_catalog).material
    assert material.color_name == "navy" and material.pattern == "plaid"
    assert material.pattern_color is not None and min(material.pattern_color[:3]) > 0.8  # white on dark


@pytest.mark.parametrize(
    ("prompt", "opacity", "alpha", "requires_adult"),
    [
        ("black bodycon mini dress", 1.0, "opaque", False),
        ("sheer black bodycon mini dress", 0.55, "blend", True),
        ("transparent white mini dress", 0.45, "blend", True),
        ("slightly sheer black thigh-high stockings", 0.8, "blend", True),
        ("very sheer chiffon dress", 0.35, "blend", True),
        ("black sheer lace bodysuit", 1.0, "mask", True),  # sheer lace: open holes, not a veil
        ("white lace crop cami", 1.0, "opaque", False),  # lined
        ("white unlined lace crop cami", 1.0, "mask", True),
        ("black lace bralette", 1.0, "mask", True),  # lingerie is not lined, and is gated anyway
        ("black fishnet thigh-highs", 1.0, "mask", True),
    ],
)
def test_the_gate_follows_what_will_render(template_catalog, prompt, opacity, alpha, requires_adult):
    result = plan(prompt, template_catalog)
    assert result.material.opacity == opacity
    assert result.material.alpha_mode == alpha
    assert result.requires_adult is requires_adult


def test_explicit_choices_override_the_prompt(template_catalog):
    result = plan("black mini dress", template_catalog, finish="latex", pattern="dots", opacity=0.5, coverage="micro")
    assert (result.material.finish, result.material.pattern, result.material.alpha_mode) == ("latex", "dots", "blend")
    assert result.style.coverage == "micro" and result.requires_adult


def test_a_template_that_forbids_transparency_stays_opaque(template_catalog):
    from wardrobe.domain.garments import GarmentTemplate
    from wardrobe.pipeline.plan_outfit import parse_prompt, resolve_material

    base = template_catalog.get("dress-mini-bodycon-v1").model_dump(by_alias=True)
    base["materials"]["supportsTransparency"] = False
    template = GarmentTemplate.model_validate(base)
    text = "sheer black fishnet dress"
    material = resolve_material(parse_prompt(text), OutfitRequest(prompt=text), template, text)
    assert material.alpha_mode == "opaque" and material.opacity == 1.0 and not material.exposes_body


def test_micro_is_a_coverage_not_a_category(template_catalog):
    result = plan("red micro bikini", template_catalog)
    assert result.category == "swimwear" and result.style.coverage == "micro"
    assert result.name == "Red Micro Triangle Bikini"


@pytest.mark.parametrize(
    ("prompt", "field", "value"),
    [
        ("string bikini", "straps", "string"),
        ("black garter belt", "straps", "garter"),
        ("red harness bralette", "straps", "harness"),
        ("white v-neck tee", "neckline", "v"),
        ("black plunging bodysuit", "neckline", "plunge"),
        ("red backless mini dress", "back", "low"),
        ("black high-cut one-piece swimsuit", "leg_cut", "high"),
    ],
)
def test_cut_and_strap_words(template_catalog, prompt, field, value):
    assert getattr(plan(prompt, template_catalog).style, field) == value


# ----------------------------------------------------------------------
# what the engines are handed
# ----------------------------------------------------------------------
def test_a_coloured_pattern_leaves_the_factor_white_and_keeps_opacity(template_catalog):
    material = GarmentMaterial.from_plan("Look", plan("red and white striped mini dress", template_catalog).material)
    assert material.texture is not None and material.texture_coloured
    assert material.base_color == (1.0, 1.0, 1.0, 1.0)
    sheer = GarmentMaterial.from_plan("Look", plan("sheer red mini dress", template_catalog).material)
    assert sheer.base_color[3] == pytest.approx(0.55) and sheer.alpha_mode == "blend"


def test_without_mtoon_the_pbr_material_carries_alpha_and_texture(template_catalog):
    from wardrobe.vrm.document import GltfDocument

    document = GltfDocument({"asset": {"version": "2.0"}, "buffers": [{"byteLength": 0}]}, b"")
    material = GarmentMaterial.from_plan("Net", plan("black fishnet thigh-highs", template_catalog).material)
    gltf = document.materials[material.add_to(document)]
    assert gltf["alphaMode"] == "MASK" and gltf["alphaCutoff"] == 0.5
    texture = document.gltf["textures"][gltf["pbrMetallicRoughness"]["baseColorTexture"]["index"]]
    assert document.gltf["samplers"][texture["sampler"]]["wrapS"] == 10497  # tiles


def test_blender_is_handed_the_same_resolved_material(template_catalog, tmp_path):
    from wardrobe.engines.blender import BlenderEngine

    material = GarmentMaterial.from_plan("Look", plan("black lace bodysuit", template_catalog, opacity=0.6).material)
    spec = BlenderEngine._material_spec(material, tmp_path)
    assert spec["alphaMode"] == "blend" and spec["baseColorFactor"][3] == pytest.approx(0.6)
    assert set(spec["textures"]) == {"baseColor"}
    assert (tmp_path / "baseColor.png").read_bytes() == material.texture


def test_an_opacity_below_the_minimum_is_clamped_and_reported(template_catalog):
    result = plan("black mini dress", template_catalog, opacity=0.05)
    assert result.material.opacity == 0.2
    assert any("clamped to 0.2" in note for note in result.notes)


@pytest.mark.parametrize(
    ("prompt", "lined", "alpha"),
    [
        ("black lined lace bralette", True, "opaque"),  # asked for: honoured, lingerie included
        ("black lace bralette", False, "mask"),
        ("black sheer lace bralette", False, "mask"),  # sheer lace: open holes
        ("white lace crop cami", True, "opaque"),
        ("white unlined lace crop cami", False, "mask"),
    ],
)
def test_lining(template_catalog, prompt, lined, alpha):
    material = plan(prompt, template_catalog).material
    assert (material.lined, material.alpha_mode) == (lined, alpha)


def test_a_see_through_garment_tells_blender_not_to_mask_the_body(template_catalog):
    from wardrobe.engines.blender import mask_policy

    assert mask_policy(plan("black fishnet thigh-highs", template_catalog).material) == "none"
    assert mask_policy(plan("sheer red mini dress", template_catalog).material) == "none"
    assert mask_policy(plan("red mini dress", template_catalog).material) == "body-only"


@pytest.mark.parametrize(("prompt", "field", "value"), [
    ("black balconette bra", "neckline", "balconette"),
    ("black demi-cup bra", "neckline", "demi"),
    ("black high-waisted briefs", "rise", "high"),
    ("black low-rise briefs", "rise", "low"),
])
def test_cup_and_rise_words(template_catalog, prompt, field, value):
    assert getattr(plan(prompt, template_catalog).style, field) == value
