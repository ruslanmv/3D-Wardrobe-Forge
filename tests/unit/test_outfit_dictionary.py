"""OD1. The outfit dictionary says only what the planner can make, and rates it as the gate does."""

from __future__ import annotations

import pytest

from wardrobe.domain.garments import INTIMATE_CATEGORIES
from wardrobe.hosiery.presets import PRESETS as HOSIERY_PRESETS
from wardrobe.pipeline import outfit_dictionary as od
from wardrobe.pipeline.look_presets import LOOK_PRESETS


@pytest.fixture(scope="module")
def planned(template_catalog):
    return {entry["id"]: entry for entry in od.catalogue(template_catalog)["outfits"]}


def test_ids_titles_and_groups_are_sound():
    ids = [o.id for o in od.OUTFITS]
    assert len(ids) == len(set(ids))
    assert len({o.title for o in od.OUTFITS}) == len(ids)
    groups = od.groups()
    for outfit in od.OUTFITS:
        assert outfit.group in groups, outfit.id
        assert 0 < len(outfit.prompt) <= 300
        assert outfit.preset is None or outfit.preset in LOOK_PRESETS or outfit.preset in HOSIERY_PRESETS
    for group in od.GROUPS:
        assert any(o.group == group.id for o in od.OUTFITS), f"empty group {group.id}"


def test_every_entry_plans_to_real_templates(planned, template_catalog):
    for outfit_id, entry in planned.items():
        templates = [g["template"] for g in entry["garments"] if g["template"]]
        assert templates, outfit_id
        for template_id in templates:
            assert template_catalog.get(template_id) is not None, (outfit_id, template_id)
        assert set(entry["slots"]) <= set(od.SLOT_OF_CATEGORY.values()), (outfit_id, entry["slots"])


@pytest.mark.parametrize("outfit", od.OUTFITS, ids=lambda o: o.id)
def test_a_group_claim_matches_the_rating_forge_computes(planned, outfit):
    """Both ways: no gated garment in a general group, nothing ungated passed off as private."""
    entry = planned[outfit.id]
    gated = any(g["category"] in INTIMATE_CATEGORIES or g["adultGate"] for g in entry["garments"])
    assert entry["rating"] == ("private" if gated else "general")
    assert od.groups()[outfit.group].private == gated, (outfit.id, entry["garments"])


def test_the_request_is_the_body_a_job_sends(planned):
    entry = planned["stockings-mini-dress"]
    assert entry["request"] == {"prompt": "black bodycon mini dress", "preset": "classic_black_mini_dress"}
    assert planned["little-black-dress"]["request"] == {"prompt": "black satin cocktail dress"}


def test_the_pajamas_are_pajamas(planned):
    """'pajama trousers' planned office trousers: the category word beat the template's tags."""
    templates = [g["template"] for g in planned["pajamas"]["garments"]]
    assert templates == ["night-pajama-top-v1", "night-pajama-trousers-v1"]
