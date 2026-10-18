"""AN1/AN2. The Anime Fan Service collection, and the cuts and print it needed.

What must hold (docs/ANIME_FAN_SERVICE.md):

* twelve looks, each in the dictionary and in exactly one of the four sections;
* original designs: no title or prompt names a character or a franchise;
* rated by Forge, not by the collection: the bikini, the leotard and the bodysuit are
  private, the rest general, and the occasion is hidden as a whole without private mode;
* a slit and an open front are real cuts, asked for by name, and absent unless asked for.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from wardrobe.domain.looks import OutfitRequest
from wardrobe.geometry.procedural import (
    SLIT_ANGLE,
    FitParameters,
    build_garment,
    front_angle,
)
from wardrobe.materials.finishes import PATTERNS
from wardrobe.materials.textures import pattern_texture
from wardrobe.pipeline import occasions as oc
from wardrobe.pipeline import outfit_dictionary as od
from wardrobe.pipeline.plan_outfit_stack import plan_outfit_stack
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body

ROOT = Path(__file__).resolve().parents[2]
COLLECTION = json.loads((ROOT / "assets/anime/fan_service_collection.json").read_text(encoding="utf-8"))
LOOKS = {look["id"]: look for look in COLLECTION["looks"]}
PRIVATE = {"anime-ocean-navigator", "anime-moon-rabbit", "anime-ghost-operative"}


@pytest.fixture(scope="module")
def entries(template_catalog):
    return {entry["id"]: entry for entry in od.catalogue(template_catalog)["outfits"]}


def test_twelve_looks_each_in_the_dictionary_and_one_section(entries):
    assert len(LOOKS) == 12
    anime = oc.occasions()["anime"]
    by_style = {style.id: set(style.looks) for style in anime.styles}
    assert [s["style"] for s in COLLECTION["sections"]] == list(by_style)
    placed = [look for looks in by_style.values() for look in looks]
    assert sorted(placed) == sorted(LOOKS)  # every look once, no look twice
    for section in COLLECTION["sections"]:
        assert by_style[section["style"]] == {i for i, look in LOOKS.items() if look["section"] == section["id"]}
    assert set(LOOKS) <= set(entries)


def test_original_designs_name_no_character_and_no_franchise(entries):
    names = {word.lower() for look in LOOKS.values() for word in look["inspiredBy"].values() if isinstance(word, str)}
    for look_id in LOOKS:
        entry = entries[look_id]
        text = f"{entry['title']} {entry['prompt']} {look_id}".lower()
        assert not [name for name in names if name in text], look_id
    assert COLLECTION["design"] == "original"
    assert all(look["inspiredBy"]["adultCharacter"] for look in LOOKS.values())


def test_ratings_are_forges_and_the_occasion_is_private(entries):
    assert {i for i in LOOKS if entries[i]["rating"] == "private"} == PRIVATE
    assert oc.occasions()["anime"].private
    # A group's private flag is checked against the computed rating (test_outfit_dictionary).
    assert {entries[i]["group"] for i in PRIVATE} == {"anime-private"}
    assert {entries[i]["group"] for i in set(LOOKS) - PRIVATE} == {"anime"}


def test_every_look_plans_to_what_its_record_says_is_built(entries):
    for look_id, look in LOOKS.items():
        garments = entries[look_id]["garments"]
        assert len(garments) >= 2, look_id
        assert look["built"] and look["deferred"], look_id


def test_the_beach_style_is_on_vacation_too(entries):
    beach = next(s for s in oc.occasions()["vacation"].styles if s.id == "anime-beach")
    # Never empty without private mode: the sarong look is general.
    assert {entries[i]["rating"] for i in beach.looks} == {"general", "private"}


# ----------------------------------------------------------------------
# the cuts
# ----------------------------------------------------------------------
@pytest.mark.parametrize(("prompt", "field", "value"), [
    ("black satin halter evening gown with thigh slit", "slit", "high"),
    ("white pencil skirt with slit", "slit", "high"),
    ("red cropped jacket worn open", "front", "open"),
])
def test_cuts_are_asked_for_by_name(template_catalog, prompt, field, value):
    garment = plan_outfit_stack(OutfitRequest(prompt=prompt), template_catalog).garments[-1]
    assert getattr(garment.style, field) == value
    plain = plan_outfit_stack(OutfitRequest(prompt=prompt.split(" with ")[0].replace(" worn open", "")),
                              template_catalog).garments[-1]
    assert getattr(plain.style, field) == ""


@pytest.fixture(scope="module")
def measurements():
    document = GltfDocument.from_bytes(build_vrm(CALIBRATION_BODIES[1], spec="VRM1"))
    return measure_body(document, inspect_document(document))


def lowest_near(mesh, params, angle: float, width: float = 0.12) -> float:
    phi = front_angle(mesh.positions.astype(np.float64), params)
    near = np.abs((phi - angle + np.pi) % (2 * np.pi) - np.pi) < width
    return float(mesh.positions[near, 1].min())


def test_a_slit_raises_the_hem_over_her_left_thigh_only(measurements):
    plain = FitParameters(measurements=measurements, metadata={})
    slit = FitParameters(measurements=measurements, metadata={"slit": "high"})
    gown, cut = (build_garment("dress", p, hem="floor") for p in (plain, slit))
    angle = SLIT_ANGLE * (1.0 if slit.forward >= 0 else -1.0)
    rise = lowest_near(cut, slit, angle) - lowest_near(gown, plain, angle)
    assert rise > 0.3 * (slit.hip_y - slit.ankle_y)  # high on the thigh, not a kick pleat
    for elsewhere in (np.pi, -angle):  # the back and the other leg keep the hem
        assert lowest_near(cut, slit, elsewhere) == pytest.approx(lowest_near(gown, plain, elsewhere), abs=1e-4)
    assert cut.vertex_count == gown.vertex_count  # a cut, not a new mesh


def test_a_mini_has_no_slit_to_cut(measurements):
    slit = FitParameters(measurements=measurements, metadata={"slit": "high"})
    plain = FitParameters(measurements=measurements, metadata={})
    a, b = (build_garment("dress", p, hem="mini") for p in (plain, slit))
    assert np.allclose(a.positions, b.positions)


def test_an_open_front_shows_what_is_under_the_jacket(measurements):
    plain = FitParameters(measurements=measurements, metadata={})
    open_ = FitParameters(measurements=measurements, metadata={"front": "open"})
    closed, opened = (build_garment("cropped-jacket", p) for p in (plain, open_))
    band = opened.positions[: closed.positions.shape[0]]
    phi = front_angle(band.astype(np.float64), open_)
    front = np.abs(phi) < 0.05
    # At her front centre the jacket is down to a sliver at the hem; at the back it is whole.
    assert np.ptp(band[front, 1]) < 0.02
    back = np.abs(np.abs(phi) - np.pi) < 0.2
    assert np.ptp(band[back, 1]) > 0.1


# ----------------------------------------------------------------------
# the print
# ----------------------------------------------------------------------
def test_the_floral_print_is_two_colours_and_reproducible():
    assert PATTERNS["floral"].coloured
    first = pattern_texture("floral", (0.8, 0.1, 0.1), (1.0, 0.8, 0.9))
    assert first == pattern_texture("floral", (0.8, 0.1, 0.1), (1.0, 0.8, 0.9))
    assert first != pattern_texture("floral", (0.8, 0.1, 0.1), (1.0, 1.0, 1.0))


def test_a_floral_gown_is_planned_with_its_two_colours(template_catalog):
    gown = plan_outfit_stack(OutfitRequest(prompt="red and pink floral satin halter evening gown"),
                             template_catalog).garments[0]
    assert gown.material.pattern == "floral" and gown.material.pattern_color is not None
