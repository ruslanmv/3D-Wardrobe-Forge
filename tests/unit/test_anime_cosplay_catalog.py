"""Anime reference collection: all 12 entries are discoverable without bypassing safety gates."""
from __future__ import annotations

import json
from pathlib import Path

from wardrobe.pipeline import outfit_dictionary as od
from wardrobe.pipeline import occasions as oc

CATALOG = json.loads((Path(__file__).resolve().parents[2] / "assets/cosplay/anime_reference_catalog.json").read_text())


def test_anime_reference_catalog_is_unique_and_pending_rights():
    ids = [row["id"] for row in CATALOG]
    assert len(ids) == len(set(ids)) == 12
    assert all(row["rights"]["status"] == "unreviewed" and row["adultOnly"] for row in CATALOG)
    assert all(row["fitFidelity"] == "silhouette-proxy" for row in CATALOG)


def test_all_twelve_looks_are_in_private_cosplay_style(template_catalog):
    ids = {row["id"] for row in CATALOG}
    outfits = {entry["id"]: entry for entry in od.catalogue(template_catalog)["outfits"]}
    assert ids <= outfits.keys()
    occasion = oc.occasions()["private"]
    style = next(s for s in occasion.styles if s.id == "anime-cosplay")
    assert set(style.looks) == ids
    for look in style.looks:
        assert outfits[look]["garments"], look
        assert "cosplay" in outfits[look]["tags"]
        assert od.groups()[outfits[look]["group"]].private == (outfits[look]["rating"] == "private")
