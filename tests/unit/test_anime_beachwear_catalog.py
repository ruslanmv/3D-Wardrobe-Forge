"""Original anime-inspired beachwear: only real, gated swimsuits are advertised."""
from __future__ import annotations

import json
from pathlib import Path

from wardrobe.pipeline import occasions as oc
from wardrobe.pipeline import outfit_dictionary as od

CATALOG = json.loads(
    (Path(__file__).resolve().parents[2] / "assets/swimwear/anime_beachwear_catalog.json").read_text()
)


def test_beachwear_catalog_has_twelve_original_designs():
    ids = [item["id"] for item in CATALOG]
    assert len(ids) == len(set(ids)) == 12
    assert all(item["adultOnly"] for item in CATALOG)
    assert all(item["rights"]["franchise"] == "none" for item in CATALOG)
    assert all(item["implementationStatus"] == "existing-swimwear-proxy" for item in CATALOG)


def test_all_twelve_are_swimwear_and_discoverable(template_catalog):
    ids = {item["id"] for item in CATALOG}
    outfits = {item["id"]: item for item in od.catalogue(template_catalog)["outfits"]}
    private_style = next(s for s in oc.occasions()["private"].styles if s.id == "anime-beachwear")
    beach_style = next(s for s in oc.occasions()["vacation"].styles if s.id == "beach")
    assert set(private_style.looks) == ids
    assert ids <= set(beach_style.looks)
    for look_id in ids:
        entry = outfits[look_id]
        assert entry["group"] == "swim"
        assert entry["rating"] == "private"
        assert "anime-beachwear" in entry["tags"]
        assert entry["garments"]
        assert all(garment["category"] == "swimwear" for garment in entry["garments"])


def test_vacation_beach_has_general_alternative(template_catalog):
    outfits = {item["id"]: item for item in od.catalogue(template_catalog)["outfits"]}
    beach_style = next(s for s in oc.occasions()["vacation"].styles if s.id == "beach")
    assert any(outfits[look]["rating"] == "general" for look in beach_style.looks)
