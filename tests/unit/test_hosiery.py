"""Hosiery: the data model, the planner, the poses, and the parts built without a body.

The pipeline half — stockings publishing their tops, straps clipped to them,
tension in each pose, the reveal — is tests/integration/test_hosiery_pipeline.py.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from pydantic import ValidationError

from wardrobe.domain.looks import OutfitRequest
from wardrobe.engines.geometry_checks import POSE_TESTS
from wardrobe.hosiery import hardware
from wardrobe.hosiery.materials import SIDE_DARKENING, falloff, sheer_texture
from wardrobe.hosiery.options import (
    DENIER_STEPS,
    HosieryOptions,
    RevealOptions,
    denier_to_opacity,
)
from wardrobe.hosiery.poses import rotations, transforms
from wardrobe.hosiery.presets import PRESETS, expand
from wardrobe.hosiery.suspender_straps import STRETCH_ERROR, STRETCH_WARN, Strap, ribbon
from wardrobe.pipeline.plan_outfit_stack import plan_outfit_stack


# ----------------------------------------------------------------------
# the data model
# ----------------------------------------------------------------------
@pytest.mark.parametrize("bad", [
    {"hosiery": {"topStyle": "velvet"}},
    {"hosiery": {"denier": 1}},
    {"hosiery": {"transparency": 0.95}},
    {"suspenderBelt": {"style": "corset"}},
    {"suspenderBelt": {"strapCount": 5}},
    {"suspenderBelt": {"strapWidthMm": 40}},
    {"suspenderBelt": {"hardware": {"color": "rose"}}},
    {"reveal": {"level": "everything"}},
    {"reveal": {"explicitHemLength": "thigh"}},
    {"reveal": {"explicitHemLength": 500}},
    {"hosiery": {"unknownField": 1}},
])
def test_out_of_range_options_are_refused_when_the_request_is_made(bad):
    with pytest.raises(ValidationError):
        OutfitRequest.model_validate({"prompt": "black mini dress", **bad})


def test_snake_case_and_camel_case_are_the_same_field():
    a = HosieryOptions.model_validate({"top_style": "wide", "top_width_cm": 6})
    b = HosieryOptions.model_validate({"topStyle": "wide", "topWidthCm": 6})
    assert a == b


def test_denier_maps_onto_the_opacity_scale():
    values = [denier_to_opacity(d) for d in DENIER_STEPS]
    assert values == sorted(values) and len(set(values)) == len(values)
    assert denier_to_opacity(20) == pytest.approx(0.45)
    assert denier_to_opacity(60) == 1.0  # opaque: the ungated form of the look
    assert 0.2 <= denier_to_opacity(10) < denier_to_opacity(40) < 1.0


def test_an_explicit_hem_length_accepts_words_and_centimetres():
    assert RevealOptions(explicitHemLength="knee").explicit_hem_length == "knee"
    assert RevealOptions(explicitHemLength=42).explicit_hem_length == 42


# ----------------------------------------------------------------------
# planning: additive, and only when asked
# ----------------------------------------------------------------------
@pytest.mark.parametrize("prompt", [
    "red bodycon mini dress", "black thigh-high stockings + red skater mini dress",
    "black suspender belt", "black garter belt + black stockings", "blue straight jeans + white crop top",
])
def test_a_request_without_hosiery_plans_exactly_as_before(prompt, template_catalog):
    plan = plan_outfit_stack(OutfitRequest(prompt=prompt), template_catalog)
    assert plan.hosiery is None
    assert all(g.hosiery is None and g.set_id is None and g.role != "connector" for g in plan.garments)


def test_the_garter_set_still_answers_to_suspender_belt(template_catalog):
    plan = plan_outfit_stack(OutfitRequest(prompt="black suspender belt"), template_catalog)
    assert plan.template_id == "under-garter-set-v1"


@pytest.mark.parametrize(("prompt", "template_id"), [
    ("black waspie", "under-waspie-v1"),
    ("black guêpière", "under-guepiere-v1"),
    ("black high-waisted suspender belt", "under-suspender-belt-high-v1"),
])
def test_the_new_belts_answer_to_their_own_names(prompt, template_id, template_catalog):
    plan = plan_outfit_stack(OutfitRequest(prompt=prompt), template_catalog)
    assert template_id in [g.template_id for g in plan.garments]
    assert plan.hosiery is not None  # choosing one engages the hosiery design


def test_the_new_templates_validate_and_are_underwear(template_catalog):
    for template_id in ("under-suspender-belt-v1", "under-suspender-belt-high-v1", "under-waspie-v1",
                        "under-guepiere-v1"):
        template = template_catalog.get(template_id)
        assert template is not None and not template.validate_semantics()
        assert template.category == "underwear" and template.opt_in


def test_a_hosiery_request_plans_belt_stockings_straps_then_the_dress(template_catalog):
    plan = plan_outfit_stack(OutfitRequest.model_validate({
        "prompt": "black bodycon mini dress", "hosiery": {"denier": 20, "topStyle": "wide"},
        "suspenderBelt": {"style": "classic"}, "reveal": {"level": "glimpse"},
    }), template_catalog)
    roles = [g.role for g in plan.garments]
    assert roles == ["foundation", "legwear", "connector", "one-piece"]
    belt, stockings, straps, dress = plan.garments
    assert belt.template_id == "under-suspender-belt-v1"
    assert stockings.material.opacity == pytest.approx(0.45) and stockings.material.alpha_mode == "blend"
    assert straps.template_id is None and straps.requires_adult
    assert all(g.hosiery == plan.hosiery for g in plan.garments)
    assert plan.requires_adult  # the gate is the existing one: underwear, and sheer stockings
    assert plan.hosiery.reveal.level == "glimpse" and plan.hosiery.reveal.prompt_hem == "mini"


def test_opaque_stockings_without_a_belt_are_not_gated(template_catalog):
    plan = plan_outfit_stack(OutfitRequest.model_validate({
        "prompt": "black bodycon mini dress", "hosiery": {"type": "opaque"},
    }), template_catalog)
    stockings = next(g for g in plan.garments if g.category == "legwear")
    assert not stockings.requires_adult and stockings.material.opacity == 1.0
    assert not any(g.role == "connector" for g in plan.garments)


def test_a_preset_fills_what_the_request_leaves_empty(template_catalog):
    request = OutfitRequest.model_validate({"prompt": "classic_black_mini_dress",
                                            "preset": "classic_black_mini_dress",
                                            "reveal": {"level": "discreet"}})
    expanded = expand(request)
    assert expanded.prompt == PRESETS["classic_black_mini_dress"]["prompt"]
    assert expanded.reveal.level == "discreet"  # the request's own block wins
    assert expanded.hosiery.top_style == "wide" and expanded.suspender_belt.hardware.color == "silver"
    for name in PRESETS:
        plan = plan_outfit_stack(OutfitRequest(prompt=name, preset=name), template_catalog)
        assert plan.hosiery is not None and plan.hosiery.preset == name


def test_a_matching_set_id_reaches_the_belt_and_straps(template_catalog):
    plan = plan_outfit_stack(OutfitRequest.model_validate({
        "prompt": "black lace bralette + black mini skirt", "hosiery": {},
        "suspenderBelt": {"matchingSetId": "noir-01"},
    }), template_catalog)
    ids = {g.role: g.set_id for g in plan.garments}
    assert ids["foundation"] == "noir-01" and ids["connector"] == "noir-01"
    assert ids["main"] is None


# ----------------------------------------------------------------------
# poses
# ----------------------------------------------------------------------
@pytest.mark.parametrize("forward", [1.0, -1.0])
def test_sitting_brings_the_knees_forward_whichever_way_she_faces(forward):
    hip, knee = np.array([0.1, 0.9, 0.0]), np.array([0.1, 0.5, 0.0])
    table = transforms("sit", forward, {"leftUpperLeg": hip, "hips": np.zeros(3)}, ["leftUpperLeg"])
    moved = (table["leftUpperLeg"] @ np.append(knee, 1.0))[:3]
    assert moved[2] * forward > 0.35  # in front of her, not behind
    assert rotations("sit", -1.0) == POSE_TESTS["sit"]  # the stress test's own table is untouched


# ----------------------------------------------------------------------
# parts built without a body
# ----------------------------------------------------------------------
def test_a_ribbon_is_flat_with_its_wide_face_on_the_surface():
    path = np.column_stack([np.zeros(11), np.linspace(1.0, 0.7, 11), np.full(11, 0.1)])
    normals = np.tile([0.0, 0.0, 1.0], (11, 1))
    mesh = ribbon(path, normals, width=0.009, thickness=0.0012)
    extent = mesh.positions.max(axis=0) - mesh.positions.min(axis=0)
    assert extent[0] == pytest.approx(0.009, abs=1e-6) and extent[2] == pytest.approx(0.0012, abs=1e-6)
    assert not mesh.validate()


@pytest.mark.parametrize("part", [hardware.clasp_local, hardware.slider_local, hardware.ring_local])
def test_every_hardware_part_stays_within_the_triangle_budget(part):
    mesh = part()
    assert 0 < mesh.triangle_count < hardware.MAX_PART_TRIANGLES
    assert not mesh.validate()


def test_hardware_is_placed_in_the_frame_it_is_given():
    clasp = hardware.clasp_local()
    origin = np.array([0.1, 0.8, 0.07])
    placed = hardware.place(clasp, origin, np.array([1.0, 0, 0]), np.array([0, 1.0, 0]), np.array([0, 0, 1.0]),
                            "hardware-clasp")
    centre = (placed.positions.max(axis=0) + placed.positions.min(axis=0)) / 2
    assert np.allclose(centre[:2], origin[:2], atol=0.003)
    assert placed.positions[:, 2].min() >= origin[2] - 1e-6  # stands on the surface, not in it


def test_strap_status_follows_the_thresholds():
    strap = Strap("left-front", "left", "front", np.zeros((2, 3)), 1.0, [], [])
    strap.stretch = {"stand": -0.015, "walk": STRETCH_WARN + 0.01, "sit": STRETCH_ERROR + 0.01}
    assert (strap.status("stand"), strap.status("walk"), strap.status("sit")) == ("ok", "warning", "error")
    strap.stretch["sit"] = -0.3
    assert strap.status("sit") == "slack"


# ----------------------------------------------------------------------
# materials
# ----------------------------------------------------------------------
def test_side_darkening_is_more_opaque_at_the_sides_than_the_front():
    base = denier_to_opacity(20)
    front, side, back = falloff(np.array([0.0, 0.25, 0.5]), base)
    assert front == pytest.approx(base) and back == pytest.approx(base)
    assert side == pytest.approx(base + SIDE_DARKENING)


def test_the_sheer_texture_is_deterministic_and_carries_the_falloff():
    import io

    from PIL import Image

    a = sheer_texture((0.08, 0.08, 0.1), 0.45)
    assert a == sheer_texture((0.08, 0.08, 0.1), 0.45)
    alpha = np.asarray(Image.open(io.BytesIO(a)))[0, :, 3] / 255.0
    assert alpha[len(alpha) // 4] > alpha[0] + 0.2  # a quarter turn round: her side
    assert math.isclose(alpha[0], 0.45, abs_tol=0.02)
