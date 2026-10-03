"""OD1. GET /v1/outfits, and its ratings against the gate a real job meets."""

from __future__ import annotations

from tests.integration.test_studio_api import make_client
from tests.library_support import write_library
from wardrobe.library import AvatarLibrary
from wardrobe.pipeline.outfit_dictionary import OUTFITS


def test_the_dictionary_is_served_and_its_ratings_are_the_job_gate(
    orchestrator, monkeypatch, tmp_path, vrm_bytes
):
    library = AvatarLibrary.from_directory(write_library(tmp_path / "library", {"Mira.vrm": vrm_bytes}))
    with make_client(orchestrator, monkeypatch, library) as client:
        body = client.get("/v1/outfits").json()
        assert body["version"] == 1
        assert [o["id"] for o in body["outfits"]] == [o.id for o in OUTFITS]
        assert {g["id"] for g in body["groups"]} == {o["group"] for o in body["outfits"]}
        # Mira is not declared adult: a general entry is allowed, a private one refused.
        for entry in body["outfits"]:
            plan = client.post("/v1/library/mira/plan", json={"outfit": entry["request"]})
            assert plan.status_code == 200, (entry["id"], plan.text)
            assert plan.json()["allowed"] == (entry["rating"] == "general"), entry["id"]
