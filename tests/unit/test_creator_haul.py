"""CR1/CR2. The Try-on haul: recipes, how they are filmed, the body art they suggest, and stockings.

Occasions only *recommend* body art: the Studio offers a design after the look is made and its
exposure says the placement is bare. These tests hold the recommendations to the catalogue they
name, and the three flagship recommendations to the geometry: the finished look really leaves that
skin bare. The stockings add-ons are read from what the planner builds, never from a look's name.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wardrobe.body_art.catalog import BodyArtCatalog
from wardrobe.body_art.contract import PLACEMENTS
from wardrobe.domain.jobs import CreateJobRequest
from wardrobe.domain.looks import OutfitRequest
from wardrobe.pipeline import occasions as oc
from wardrobe.pipeline import outfit_dictionary as od
from wardrobe.pipeline.plan_outfit_stack import plan_outfit_stack


@pytest.fixture(scope="module")
def entries(template_catalog):
    return {entry["id"]: entry for entry in od.catalogue(template_catalog)["outfits"]}


@pytest.fixture(scope="module")
def designs():
    root = Path(__file__).resolve().parents[2] / "assets" / "body_art"
    return {d.id: d for d in BodyArtCatalog.from_directory(root).all()}


def test_every_recommendation_names_a_real_design_at_a_placement_it_can_go(designs):
    styles = [s for o in oc.OCCASIONS for s in o.styles if s.content]
    assert len(styles) >= 19
    for style in styles:
        content = style.content
        assert set(content.shots) <= set(oc.SHOTS) and content.detail in oc.DETAILS, style.id
        assert set(content.body_art_placements) <= set(PLACEMENTS), style.id
        for design in content.body_art_designs:
            assert design in designs, (style.id, design)
            # Somewhere it is recommended, it can actually be put.
            assert set(designs[design].placements) & set(content.body_art_placements), (style.id, design)
    for title, members in oc.BODY_ART_MOODS.values():
        assert title and all(d in designs for d in members)


def test_the_served_catalogue_carries_the_profiles(template_catalog):
    served = {o["id"]: o for o in od.catalogue(template_catalog)["occasions"]}
    club = next(s for s in served["creator"]["styles"] if s["id"] == "club-waistline")
    assert club["content"]["bodyArt"]["placements"][0] == "waistline"
    assert club["content"]["shots"] == list(oc.SHOTS) and club["content"]["detail"] == "waist"
    private = [s["id"] for s in served["private"]["styles"]]
    # AB. The styles that were there keep their order; the Anime Beachwear collection is added after.
    assert private == ["fan-service", "y2k-reveal", "lingerie", "corsetry", "glamour", "sheer-layering",
                       "body-art-focus", "anime-beachwear"]


def test_the_cropped_corset_is_chosen_only_when_named(template_catalog):
    def template(prompt):
        return plan_outfit_stack(OutfitRequest(prompt=prompt), template_catalog).garments[0].template_id

    assert template("black cropped corset top") == "top-corset-cropped-v1"
    assert template("black corset top") == "top-corset-v1"
    assert template("black bustier") == "top-corset-v1"


@pytest.mark.parametrize(
    ("look", "expected"),
    [
        ("discoteca-stiletto-ankle", ["hold-ups", "suspenders"]),  # a hem the reveal can move
        ("club-waistline", ["hold-ups", "suspenders"]),
        ("italian-lace-brazilian", ["hold-ups", "suspenders"]),  # underwear alone: a garter set in view
        ("cami-denim-shorts", ["hold-ups"]),  # shorts: no straps over them
        ("discoteca-over-knee", []),  # the boots would hide the tops
        ("corset-slim-jeans", []),  # her legs are covered
        ("catsuit-boots", []),
        ("triangle-bikini", []),  # not at the beach
        ("stockings-mini-dress", []),  # she already wears them
    ],
)
def test_stockings_are_offered_by_what_she_wears(entries, look, expected):
    assert [a["id"] for a in entries[look]["addOns"]] == expected


def test_add_ons_are_rated_by_the_planner_and_say_how_they_show(entries):
    for entry in entries.values():
        for add_on in entry["addOns"]:
            assert add_on["rating"] == "private", (entry["id"], add_on["id"])  # sheer shows her body
    lace = {a["id"]: a for a in entries["italian-lace-brazilian"]["addOns"]}
    assert lace["suspenders"]["blocks"]["suspenderBelt"]["visibility"] == "full"
    assert "reveal" not in lace["suspenders"]["blocks"]
    dress = {a["id"]: a for a in entries["discoteca-stiletto-ankle"]["addOns"]}
    assert dress["suspenders"]["blocks"]["reveal"]["level"] == "statement"
    assert dress["hold-ups"]["blocks"]["reveal"]["level"] == "glimpse"
    assert "suspenderBelt" not in dress["hold-ups"]["blocks"]
    # The whole request a client sends: the look's own, the stockings named, the blocks merged.
    request = dress["suspenders"]["request"]
    assert request["prompt"].startswith(entries["discoteca-stiletto-ankle"]["prompt"] + " + ")
    assert request["suspenderBelt"]["style"] == "classic" and request["reveal"]["level"] == "statement"


@pytest.mark.parametrize(
    ("look", "placement"),
    [("club-waistline", "waistline"), ("y2k-low-rise", "waistline"), ("discoteca-open-back", "upper-back")],
)
async def test_the_flagship_recommendations_are_true_on_the_finished_look(
    orchestrator, store, entries, look, placement
):
    from wardrobe.body_art.exposure import exposure_map, read_body
    from wardrobe.vrm.document import GltfDocument
    from wardrobe.vrm.fashion_body import build_fit_form, fit_form

    await store.put("sources/form.vrm", build_fit_form(fit_form("fit-form-b-curvy")))
    record = await orchestrator.run_now(CreateJobRequest.model_validate({
        "avatar": {"storageKey": "sources/form.vrm", "avatarId": "fit-form-b-curvy"},
        "outfit": {**entries[look]["request"], "mode": "template"},
        "options": {"renderPreview": False, "engine": "native"},
    }))
    assert record.state == "completed", record.error
    surfaces, body = read_body(GltfDocument.from_bytes(await store.get(f"looks/{record.look.id}/look.vrm")))
    assert exposure_map(surfaces, body)[placement].applies, (look, placement)
