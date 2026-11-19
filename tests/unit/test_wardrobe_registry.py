"""WS1. The registry's rules point at things that exist, and fill every curated collection."""

from __future__ import annotations

import pytest

from tests.conftest import TEMPLATE_ROOT
from wardrobe.domain.garments import TemplateCatalog
from wardrobe.pipeline.outfit_dictionary import catalogue
from wardrobe.registry import classify, registry
from wardrobe.registry.store import RegistryStore


@pytest.fixture(scope="module")
def world():
    catalog = TemplateCatalog.from_directory(TEMPLATE_ROOT)
    return catalog, catalogue(catalog)


def test_every_hand_picked_id_group_and_tag_exists(world):
    catalog, dictionary = world
    templates = {t.id for t in catalog.all()}
    groups = {g["id"] for g in dictionary["groups"]}
    outfit_tags = {tag for o in dictionary["outfits"] for tag in o.get("tags") or []}
    for c in classify.ALL:
        assert set(c.garments) <= templates, (c.id, set(c.garments) - templates)
        assert set(c.groups) <= groups, (c.id, set(c.groups) - groups)
        assert set(c.outfit_tags) <= outfit_tags, (c.id, set(c.outfit_tags) - outfit_tags)
        assert set(c.types) <= set(classify.CATEGORY_IDS), c.id


def test_every_curated_collection_is_filled_from_real_items(world):
    catalog, dictionary = world
    view = registry.build(catalog, dictionary, {}, admin=True, preview=lambda t: None)
    # These fill as the admin works (favourites, imports, the outfit lab), as rules flag items, or
    # (ready-to-wear) as thumbnails exist, which this fixture gives none of.
    by_use = {"favorites", "personal-favorites", "exclusive-imports", "private-outfit-lab",
              "unsorted-private", "unassigned", "needs-review", "ready-to-wear"}
    for c in view["collections"]:
        if c["id"] not in by_use:
            assert c["count"] > 0, f"{c['id']} is empty"


def test_private_collections_live_only_in_the_private_section(world):
    for c in classify.ALL:
        assert (c.section == "private") == c.private, c.id
    # Adult is what guests already enjoy, under its own name; it is never the admin-only tier.
    assert all(not c.private for c in classify.ALL if c.section == "adult")


def test_guests_keep_adult_content_and_never_get_private_body_content(world):
    catalog, dictionary = world
    guest = registry.build(catalog, dictionary, {}, admin=False, preview=lambda t: None)
    assert any(i.get("adult") for i in guest["items"])
    assert not any(i.get("private") or i["kind"] == "body" for i in guest["items"])
    assert {"adult"} <= {s["id"] for s in guest["sections"]} and "private" not in {s["id"] for s in guest["sections"]}
    admin = registry.build(catalog, dictionary, {}, admin=True, preview=lambda t: None)
    body = [i for i in admin["items"] if i["kind"] == "body"]
    assert body and all(i["private"] for i in body)
    counts = registry.dashboard(admin)
    assert counts["general"] + counts["adult"] + counts["private"] == counts["garments"]
    assert sum(counts["bodyContent"].values()) == len(body)


def test_nearly_every_garment_has_a_type_and_says_why(world):
    catalog, dictionary = world
    garments = registry.garments(catalog, {}, lambda t: None)
    wearable = [g for g in garments if not g["body"]]
    typed = [g for g in wearable if g["type"]]
    assert len(typed) >= len(wearable) - 3
    assert all(g["typeReason"] for g in wearable)
    # Adult follows the catalog's own rule: intimate categories and adult-only templates.
    assert all(g["adult"] for g in wearable if g["engineCategory"] in ("underwear", "swimwear"))


def test_a_rule_never_overrides_an_admins_decision(tmp_path, world):
    catalog, dictionary = world
    store = RegistryStore(tmp_path)
    store.set_garment("top-tee-v1", category="activewear", tags=["Gym"], visibility="private")
    store.assign("everyday-essentials", remove=["top-tee-v1"])
    view = registry.build(catalog, dictionary, store.read(), admin=True, preview=lambda t: None)
    tee = next(i for i in view["items"] if i["id"] == "top-tee-v1")
    assert tee["type"] == "activewear" and tee["private"] and "gym" in tee["tags"]
    everyday = next(c for c in view["collections"] if c["id"] == "everyday-essentials")
    assert "top-tee-v1" not in everyday["items"]
    guest = registry.build(catalog, dictionary, store.read(), admin=False, preview=lambda t: None)
    assert "top-tee-v1" not in {i["id"] for i in guest["items"]}


def test_a_damaged_store_reads_as_no_decisions(tmp_path):
    store = RegistryStore(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text("{not json", encoding="utf-8")
    data = store.read()
    assert data["damaged"] is True and data["garments"] == {}
