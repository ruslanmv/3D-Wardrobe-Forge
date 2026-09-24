"""What the verification gallery (assets/gallery) caught, pinned so it stays fixed.

Each of these was visible in a rendered look before it was a failing test: a
crop tee collapsing off her chest in the A-pose, a top sitting inside her
chest, windows of skin down a legging, matching briefs that lost the set's
fabric, the planner picking the wrong garment, black lace vanishing on its
lining. The pictures are the evidence; these are the guard.
"""

from __future__ import annotations

import numpy as np
import pytest

from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.looks import OutfitRequest
from wardrobe.engines.geometry_checks import BodyRadialIndex, conform_limbs
from wardrobe.engines.shell import on_axis_mask
from wardrobe.geometry.mesh import Mesh
from wardrobe.geometry.procedural import FitParameters, build_garment
from wardrobe.materials.png import decode_png
from wardrobe.materials.textures import pattern_texture
from wardrobe.pipeline.plan_outfit import plan_outfit
from wardrobe.pipeline.plan_outfit_stack import _carry_matching, plan_outfit_stack
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body
from wardrobe.vrm.merge import GarmentMaterial
from wardrobe.vrm.skinning import ARM_BONES, bind_mesh, bones_for_coverage, build_bone_segments


@pytest.fixture(scope="module")
def measured():
    document = GltfDocument.from_bytes(build_vrm(CALIBRATION_BODIES[1], spec="VRM1"))
    info = inspect_document(document)
    return info, measure_body(document, info)


# ----------------------------------------------------------------------
# binding: the garment's body never follows her arms
# ----------------------------------------------------------------------
def _arm_weight(mesh: Mesh, segments, rows: np.ndarray) -> float:
    arm = np.array([segment.name in ARM_BONES for segment in segments])
    joints, weights = mesh.joints[rows], mesh.weights[rows]
    return float((weights * arm[joints.astype(int)]).sum(axis=1).max())


def test_a_crop_tee_body_takes_no_arm_weight_when_its_torso_is_marked(measured):
    info, measurements = measured
    params = FitParameters(measurements=measurements, sleeve_length="short")
    segments = build_bone_segments(
        info.humanoid_bones, measurements, bones_for_coverage(["chest", "upperArms"])
    )
    assert any(segment.name in ARM_BONES for segment in segments)

    unmasked = build_garment("crop-top", params)
    bind_mesh(unmasked, segments)
    torso = on_axis_mask(unmasked, measurements)
    assert torso.any() and not torso.all(), "the sleeves are off the body's axis, the body is on it"
    # Without the mask the side panels, nearest the upper arms, followed them.
    assert _arm_weight(unmasked, segments, torso) > 0.05

    masked = build_garment("crop-top", params)
    bind_mesh(masked, segments, torso=on_axis_mask(masked, measurements))
    assert _arm_weight(masked, segments, torso) == 0.0
    # The sleeves still follow the arms.
    assert _arm_weight(masked, segments, ~torso) > 0.5
    assert np.allclose(masked.weights.sum(axis=1), 1.0, atol=1e-4)


# ----------------------------------------------------------------------
# clearance: no band and no leg cell is left without a body to clear
# ----------------------------------------------------------------------
def test_an_empty_hull_band_between_two_filled_ones_is_filled():
    hull = np.zeros((8, 4))
    hull[2] = [0.10, 0.11, 0.10, 0.09]
    hull[4] = [0.12, 0.10, 0.10, 0.10]
    filled = BodyRadialIndex._fill_empty_bands(hull)
    np.testing.assert_allclose(filled[3], [0.12, 0.11, 0.10, 0.10])
    # Beyond the body's ends stays empty: a garment there has nothing to clear.
    assert not filled[:2].any() and not filled[5:].any()


def test_a_gap_wider_than_the_reach_is_not_bridged():
    hull = np.zeros((10, 4))
    hull[1] = hull[8] = 0.1
    assert not BodyRadialIndex._fill_empty_bands(hull, reach=3)[2:8].any()


def _tube(radius: float, x: float, y0: float, y1: float, rows: int, around: int) -> tuple[np.ndarray, np.ndarray]:
    theta = np.linspace(0, 2 * np.pi, around, endpoint=False)
    ys = np.linspace(y0, y1, rows)
    positions = np.array([[x + radius * np.cos(t), y, radius * np.sin(t)] for y in ys for t in theta])
    faces = []
    for r in range(rows - 1):
        for k in range(around):
            a, b = r * around + k, r * around + (k + 1) % around
            faces += [a, b, a + around, b, b + around, a + around]
    return positions, np.asarray(faces, dtype=np.uint32)


def test_a_legging_over_a_patch_of_unsampled_leg_is_still_outside_it():
    """Cells with no body sample used to keep the formula radius — inside the leg."""
    bones = {"leftUpperLeg": (0.1, 0.9, 0.0), "leftLowerLeg": (0.1, 0.5, 0.0), "leftFoot": (0.1, 0.1, 0.0)}
    body, _ = _tube(0.07, 0.1, 0.12, 0.88, 77, 72)
    # A 60° window of her thigh with no vertices in it: sparse sampling, not a hole.
    angle = np.degrees(np.arctan2(body[:, 2], body[:, 0] - 0.1))
    body = body[~((body[:, 1] > 0.6) & (body[:, 1] < 0.72) & (np.abs(angle - 90) < 30))]

    positions, indices = _tube(0.05, 0.1, 0.15, 0.85, 36, 48)
    mesh = Mesh(positions=positions.astype(np.float32), indices=indices)
    conform_limbs(mesh, np.ones(mesh.vertex_count, dtype=bool), body, bones, 0.004, strength=1.0)

    radius = np.hypot(mesh.positions[:, 0] - 0.1, mesh.positions[:, 2])
    inner = (mesh.positions[:, 1] > 0.2) & (mesh.positions[:, 1] < 0.8)
    assert radius[inner].min() >= 0.07


# ----------------------------------------------------------------------
# planning
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("prompt", "template_id"),
    [
        # Both tied with the Lingerie Set ("lace") or the Oversized Coat and fell
        # to alphabetical order; a garment named outright now wins.
        ("black lace bodysuit", "under-bodysuit-v1"),
        ("black unlined lace high-leg bodysuit", "under-bodysuit-v1"),
        ("black cropped jacket", "jacket-cropped-cardigan-v1"),
    ],
)
def test_the_garment_named_in_the_prompt_is_the_one_planned(template_catalog: TemplateCatalog, prompt, template_id):
    assert plan_outfit(OutfitRequest(prompt=prompt), template_catalog).template_id == template_id


def test_matching_carries_the_fabric_not_only_the_colour(template_catalog: TemplateCatalog):
    pieces = _carry_matching(["burgundy mesh bralette", "matching briefs"])
    assert "mesh" in pieces[1] and "burgundy" in pieces[1] and "matching" not in pieces[1]

    garments = plan_outfit_stack(OutfitRequest(prompt="burgundy mesh bralette + matching briefs"), template_catalog)
    bralette, briefs = garments.garments
    assert briefs.template_id == "under-briefs-v1"
    assert briefs.material.opacity == bralette.material.opacity < 1.0
    assert briefs.material.alpha_mode == bralette.material.alpha_mode


def test_matching_keeps_the_finish_word_the_prompt_used(template_catalog: TemplateCatalog):
    garments = plan_outfit_stack(OutfitRequest(prompt="black satin bralette + matching briefs"), template_catalog)
    assert {g.material.finish for g in garments.garments} == {"satin"}


def test_champagne_is_a_colour(template_catalog: TemplateCatalog):
    colour = plan_outfit(OutfitRequest(prompt="champagne satin slip dress"), template_catalog).material.base_color
    assert colour[0] > 0.6 and colour[0] > colour[2]  # warm and pale, not the default grey


# ----------------------------------------------------------------------
# geometry and surface
# ----------------------------------------------------------------------
def test_rise_moves_the_top_of_shorts(measured):
    _, measurements = measured

    def top(rise: str) -> float:
        params = FitParameters(measurements=measurements, metadata={"rise": rise})
        return float(build_garment("shorts", params, silhouette="slim", hem="mini").bounds()[1][1])

    assert top("high") > top("") > top("low")


def test_lined_black_lace_keeps_its_motif_on_the_lining():
    """Black lace on a black lining was black on black: the lace disappeared."""
    tile = decode_png(pattern_texture("lace", (0.0, 0.0, 0.0), (0.3, 0.3, 0.3), lined=True))
    assert (tile[..., 3] == 255).all(), "lined lace hides the body"
    grey = tile[..., :3].mean(axis=2)
    assert (grey < 20).mean() > 0.05 and (grey > 60).mean() > 0.05


def test_lined_lace_material_colours_its_own_texture(template_catalog: TemplateCatalog):
    material = GarmentMaterial.from_plan(
        "Dress", plan_outfit(OutfitRequest(prompt="black lined lace bodycon mini dress"), template_catalog).material
    )
    assert material.texture is not None and material.texture_coloured
    assert material.base_color[:3] == (1.0, 1.0, 1.0), "the colour is in the texture, not tinted over it"
    assert material.alpha_mode == "opaque"
