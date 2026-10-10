"""BA1. Invariant I1: a job that asks for no body art produces what it produced before body art existed.

The hashes in ``tests/fixtures/body_art_golden.json`` were taken on the pipeline as it
was before any body-art code ran in it, for three outfits on the dressed declared-adult
body: separates, underwear and a one-piece. A later change that moves them for a reason
of its own re-baselines them with ``BODY_ART_GOLDEN=write pytest <this file>``, and
says why in its commit; body art alone never may.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.body_art_support import fingerprint, run
from wardrobe.body_art.catalog import BodyArtCatalog
from wardrobe.body_art.contract import PLACEMENTS
from wardrobe.body_art.raster import artwork_polygons, coverage
from wardrobe.domain.jobs import CreateJobRequest
from wardrobe.pipeline import orchestrator as orchestrator_module

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "body_art_golden.json"
ROOT = Path(__file__).resolve().parents[2] / "assets" / "body_art"
PROMPTS = ("black tee + blue jeans", "underwear", "red bodycon mini dress")


@pytest.fixture
def client(orchestrator, monkeypatch):
    from fastapi.testclient import TestClient

    from apps.api.main import app

    monkeypatch.setattr(orchestrator_module, "_orchestrator", orchestrator)
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("prompt", PROMPTS)
async def test_no_body_art_means_the_same_output(orchestrator, store, prompt):
    record, output = await run(orchestrator, store, prompt)
    assert output is not None, record.error
    got = fingerprint(output)
    if os.environ.get("BODY_ART_GOLDEN") == "write":
        golden = json.loads(GOLDEN.read_text()) if GOLDEN.exists() else {}
        golden[prompt] = got
        GOLDEN.write_text(json.dumps(golden, indent=2, sort_keys=True) + "\n")
    assert got == json.loads(GOLDEN.read_text())[prompt]
    assert "bodyArt" not in json.dumps(record.fit_report.model_dump(by_alias=True))


def test_the_request_fields_are_optional_and_bounded():
    base = {"avatar": {"storageKey": "k"}, "outfit": {"prompt": "red dress"}}
    request = CreateJobRequest.model_validate(base)
    assert request.body_art == [] and request.body_art_remove == []
    item = {"design": "tribal-wings-01", "placement": "upper-back"}
    for bad in (
        [item, item],  # two at one placement
        [{**item, "placement": "forehead"}],  # no such placement
        [{**item, "scale": 3}],  # out of range
        [{**item, "ink": "black"}],  # not a hex colour
        [{**item, "clothes": "off"}],
    ):  # nothing but the contract
        with pytest.raises(ValueError):
            CreateJobRequest.model_validate({**base, "bodyArt": bad})
    with pytest.raises(ValueError):
        CreateJobRequest.model_validate({**base, "bodyArt": [item], "bodyArtRemove": ["upper-back"]})


def test_the_catalogue_is_valid_and_every_design_is_its_stated_shape():
    catalog = BodyArtCatalog.from_directory(ROOT)
    assert len(catalog) >= 6 and not catalog.validate_all()
    for design in catalog.all():
        ink = coverage(catalog.artwork_path(design), 128)
        if design.source == "vector":
            artwork = json.loads(catalog.artwork_path(design).read_text())
            _shapes, width, height = artwork_polygons(artwork)
        else:  # raster: the picture's own shape
            height, width = ink.shape
        assert width / height == pytest.approx(design.aspect, rel=2e-2 if design.source == "raster" else 1e-3)
        assert 0.03 < ink.mean() < 0.7, design.id  # ink, but not a solid block
        assert set(design.placements) <= set(PLACEMENTS)
    # Every v1 placement has at least one design.
    assert all(catalog.for_placement(p) for p in PLACEMENTS)


def test_a_design_can_raise_a_placement_rating_and_never_lower_it():
    from wardrobe.body_art.catalog import BodyArtDesign

    design = {
        "id": "x",
        "name": "X",
        "family": "f",
        "placements": ["upper-back"],
        "aspect": 1.0,
        "paths": "none.json",
        "license": "Apache-2.0",
    }
    raised = BodyArtCatalog([BodyArtDesign.model_validate({**design, "rating": {"upper-back": "swimwear"}})])
    assert raised.rating("x", "upper-back") == "swimwear"
    assert not [i for i in raised.validate_all() if "rating" in i]
    lowered = BodyArtCatalog([BodyArtDesign.model_validate({**design, "rating": {"upper-back": "nope"}})])
    assert any("rating" in issue for issue in lowered.validate_all())


def test_the_api_lists_the_catalogue_and_refuses_an_unknown_design(client):
    capabilities = client.get("/v1/capabilities").json()
    assert capabilities["bodyArt"]["version"] == 1
    listing = client.get("/v1/body-art").json()
    assert {p["id"] for p in listing["placements"]} == set(PLACEMENTS)
    assert "paths" not in json.dumps(listing)  # no file paths leave the server
    png = client.get("/v1/body-art/designs/tribal-wings-01.png")
    assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"
    job = {
        "avatar": {"storageKey": "sources/none.vrm"},
        "outfit": {"prompt": "red dress"},
        "bodyArt": [{"design": "no-such-design", "placement": "upper-back"}],
    }
    refused = client.post("/v1/jobs", json=job)
    assert refused.status_code == 422 and "no-such-design" in refused.text
    job["bodyArt"] = [{"design": "tribal-wings-01", "placement": "lower-back"}]  # not drawn for it
    assert client.post("/v1/jobs", json=job).status_code == 422
