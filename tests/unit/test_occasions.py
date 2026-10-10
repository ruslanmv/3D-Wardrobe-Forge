"""OC1. Occasions offer only what the dictionary can make, and never show a private look by accident."""

from __future__ import annotations

import pytest

from tests.conftest import job_request
from wardrobe.domain.jobs import CreateJobRequest
from wardrobe.pipeline import occasions as oc
from wardrobe.pipeline import outfit_dictionary as od
from wardrobe.pipeline.fashion_collections import COLLECTIONS


@pytest.fixture(scope="module")
def entries(template_catalog):
    return {entry["id"]: entry for entry in od.catalogue(template_catalog)["outfits"]}


def test_ids_are_unique_and_every_look_is_in_the_dictionary(entries):
    assert len({o.id for o in oc.OCCASIONS}) == len(oc.OCCASIONS)
    for occasion in oc.OCCASIONS:
        assert len(occasion.styles) >= 2, occasion.id
        assert len({s.id for s in occasion.styles}) == len(occasion.styles), occasion.id
        for style in occasion.styles:
            assert len(style.looks) >= 2, (occasion.id, style.id)
            assert len(set(style.looks)) == len(style.looks), (occasion.id, style.id)
            for look in style.looks:
                assert look in entries, (occasion.id, style.id, look)


def test_the_first_screen_is_the_occasions_asked_for():
    titles = [o.title for o in oc.OCCASIONS]
    assert titles == ["Night out", "Work", "Gym", "Sleep", "Shopping", "Vacation", "Campus", "Private"]


def test_without_private_mode_no_style_is_left_empty(entries):
    """A general occasion's every style has a look anyone may wear: hiding private looks never empties it."""
    for occasion in oc.OCCASIONS:
        if occasion.private:
            continue
        for style in occasion.styles:
            assert any(entries[look]["rating"] == "general" for look in style.looks), (occasion.id, style.id)


def test_private_is_hidden_as_a_whole_and_holds_the_private_looks(entries):
    private = oc.occasions()["private"]
    assert private.private and [o.id for o in oc.OCCASIONS if o.private] == ["private"]
    # Lingerie and stockings are there, rated private by the planner, not by this module.
    looks = {look for style in private.styles for look in style.looks}
    assert {"lace-lingerie-set", "italian-lace-thong", "stockings-pencil"} <= looks
    assert all(entries[look]["rating"] == "private" for look in ("lace-lingerie-set", "stockings-pencil"))


def test_campus_is_ordinary_clothes(entries):
    """Campus, not "school": nothing private, nothing mini, no corset, tube or halter top."""
    for style in oc.occasions()["campus"].styles:
        for look in style.looks:
            assert entries[look]["rating"] == "general", look
            for garment in entries[look]["garments"]:
                template = garment["template"]
                assert "mini" not in template and not any(
                    word in template for word in ("corset", "tube", "halter", "crop-cami")
                ), (look, template)


def test_discoteca_is_the_collection_and_its_four_boots(entries):
    style = next(s for s in oc.occasions()["night-out"].styles if s.id == "discoteca")
    assert style.collection == "sexy-discoteca-black" and style.collection in COLLECTIONS
    boots = [entries[look]["garments"][-1]["template"] for look in style.looks]
    assert boots == [boot["templateId"] for boot in COLLECTIONS[style.collection]["boots"]]


def test_the_served_catalogue_rates_each_style(template_catalog):
    served = od.catalogue(template_catalog)["occasions"]
    assert [o["id"] for o in served] == [o.id for o in oc.OCCASIONS]
    styles = {(o["id"], s["id"]): s for o in served for s in o["styles"]}
    assert styles[("vacation", "beach")]["rating"] == "mixed"
    assert styles[("private", "lingerie")]["rating"] == "private"
    assert styles[("work", "office")]["rating"] == "general"
    assert styles[("night-out", "discoteca")]["collection"] == "sexy-discoteca-black"
    assert "collection" not in styles[("work", "office")]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"occasion": "night-out", "style": "discoteca"}, ("night-out", "discoteca")),
        ({"occasion": "night-out", "style": "yoga"}, ("night-out", None)),
        ({"occasion": "night-out"}, ("night-out", None)),
        ({"occasion": "moon-landing", "style": "discoteca"}, (None, None)),
        (None, (None, None)),
        ("night-out", (None, None)),
    ],
)
def test_a_tag_is_checked_and_dropped_never_refused(value, expected):
    assert oc.tag(value) == expected


async def test_a_look_keeps_the_occasion_it_was_made_for(orchestrator, stored_avatar):
    for occasion in ({"occasion": "work", "style": "office"}, {"occasion": "nowhere"}):
        record = await orchestrator.run_now(
            CreateJobRequest.model_validate(
                job_request(
                    stored_avatar, "white blouse + black pencil skirt", avatar_id="oc", occasion=occasion
                )
            )
        )
        assert record.state == "completed", record.error
    looks = [look for look in (await orchestrator.wardrobes.get("oc")).looks if look.type == "vrmVariant"]
    assert [(look.occasion, look.style) for look in looks] == [("work", "office"), (None, None)]
    dumped = looks[0].model_dump(by_alias=True)
    assert dumped["occasion"] == "work" and dumped["style"] == "office"


async def test_a_change_on_a_look_draws_the_carried_garments_in_their_own_colour(
    orchestrator, store, stored_avatar
):
    """OC3. The shelf thumbnail of a change: the skirt it kept is black, not skin-coloured."""
    from types import SimpleNamespace

    from wardrobe.engines.native import NativeEngine
    from wardrobe.vrm.document import GltfDocument

    first = await orchestrator.run_now(
        CreateJobRequest.model_validate(job_request(stored_avatar, "white blouse + black pencil skirt"))
    )
    await store.put("sources/oc-look.vrm", await store.get(f"looks/{first.look.id}/look.vrm"))
    second = await orchestrator.run_now(
        CreateJobRequest.model_validate(job_request("sources/oc-look.vrm", "navy blouse"))
    )
    assert second.state == "completed", second.error
    document = GltfDocument.from_bytes(await store.get(f"looks/{second.look.id}/look.vrm"))
    colours = {
        layer.color
        for layer in NativeEngine._render_layers(None, SimpleNamespace(document=document, plan=second.plan))
    }
    navy = next(g for g in second.plan.garments).material.base_color[:3]
    assert tuple(float(c) for c in navy) in colours
    assert any(max(colour) < 0.1 for colour in colours), colours  # the carried black skirt
