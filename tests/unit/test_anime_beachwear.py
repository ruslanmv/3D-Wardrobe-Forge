"""AB5. Anime Beachwear: a new, independent collection, and nothing that existed changed by it.

What must hold (docs/ANIME_BEACHWEAR.md):

1. exactly twelve unique swimsuit designs, the ones specified;
2. every catalogue, id and garment template that existed is exactly as it was — checked
   against ``tests/fixtures/anime_beachwear_preserved.json``, taken from ``main`` before;
3. every design resolves to swimwear templates, and every construction it names is built;
4. the collection is discoverable on its own: its API, its dictionary group, its Private style;
5. the new geometry is opt-in: without a design asking, a block builds what it built.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from wardrobe import collections as registry
from wardrobe.domain.looks import OutfitRequest
from wardrobe.geometry.procedural import FitParameters, build_garment
from wardrobe.lingerie.collections import merge_lingerie
from wardrobe.pipeline import occasions as oc
from wardrobe.pipeline import outfit_dictionary as od
from wardrobe.pipeline.plan_outfit_stack import plan_outfit_stack
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body

ROOT = Path(__file__).resolve().parents[2]
PRESERVED = json.loads((ROOT / "tests/fixtures/anime_beachwear_preserved.json").read_text(encoding="utf-8"))
COLLECTION = registry.get("anime-beachwear")
SPECIFIED = [
    "beach-ocean-stripe", "beach-sakura-ties", "beach-midnight-string", "beach-violet-halter",
    "beach-sunset-bandeau", "beach-pearl-bandeau", "beach-scarlet-scoop", "beach-indigo-highcut",
    "beach-noir-cutout", "beach-rose-ruffle", "beach-aqua-skirt", "beach-sport-racer",
]
SWIM_TEMPLATES = {"swim-bikini-top-v2", "swim-bikini-bottom-v2", "swim-string-bikini-bottom-v2", "top-tube-v1",
                  "swim-one-piece-v2", "swim-skirted-v1"}


@pytest.fixture(scope="module")
def entries(template_catalog):
    return {entry["id"]: entry for entry in od.catalogue(template_catalog)["outfits"]}


# ---------------------------------------------------------------- 1. twelve designs
def test_exactly_the_twelve_specified_designs():
    ids = [d["id"] for d in COLLECTION["designs"]]
    assert ids == SPECIFIED and len(set(ids)) == 12
    assert COLLECTION["title"] == "Anime Beachwear"
    assert COLLECTION["subtitle"] == "Japanese Anime-Inspired Swimsuits"
    assert COLLECTION["categories"] == ["Bikini", "One-Piece", "Sporty", "Kawaii", "Beach Glamour"]
    assert registry.validate_all() == []


def test_statuses_are_honest():
    for d in COLLECTION["designs"]:
        assert d["status"] in registry.STATUSES
        # Validated means its pictures exist to have been validated against.
        if d["status"] == "visually-validated":
            for view in ("front", "side", "back"):
                assert (Path(COLLECTION["_dir"]) / d["preview"][view]).is_file(), (d["id"], view)


# ---------------------------------------------------------------- 2. nothing that existed changed
def test_every_existing_entry_is_exactly_as_it_was(entries):
    for before in PRESERVED["outfits"]:
        outfit_id = before["id"]
        now = entries[outfit_id]
        assert now["title"] == before["title"] and now["group"] == before["group"], outfit_id
        assert now["request"] == before["request"], outfit_id
        assert now["rating"] == before["rating"], outfit_id
        assert [g["template"] for g in now["garments"]] == before["garments"], outfit_id


def test_existing_groups_and_templates_are_untouched():
    groups = [[g.id, g.title, g.private] for g in od.GROUPS]
    assert groups[: len(PRESERVED["groups"])] == PRESERVED["groups"]
    for relative, digest in PRESERVED["templates"]:
        path = ROOT / "assets" / "garment_templates" / relative
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, relative


def test_existing_occasions_keep_their_styles_and_looks():
    now = {o.id: [(s.id, list(s.looks)) for s in o.styles] for o in oc.OCCASIONS}
    before = {o["id"]: [(s["id"], s["looks"]) for s in o["styles"]] for o in PRESERVED["occasions"]}
    # Every occasion that existed is still here, in the same order; the only one added is the
    # Anime Fan Service collection's own (docs/ANIME_FAN_SERVICE.md), never by this collection.
    ids = [o.id for o in oc.OCCASIONS]
    assert [i for i in ids if i in before] == list(before)
    assert set(ids) - set(before) <= {"anime"}
    for occasion, styles in before.items():
        # Every style that existed keeps its looks and its place among the others. The only
        # styles added are the Anime Fan Service collection's (anime-*) and this one.
        kept = [style for style in now[occasion] if style[0] in dict(styles)]
        assert kept == styles, occasion
        added = {sid for sid, _ in now[occasion]} - {sid for sid, _ in styles}
        assert all(sid.startswith("anime-") for sid in added), (occasion, added)
    # Vacation -> Beach exactly as it was; this collection is only added, last, in Private.
    beach = dict(before["vacation"])["beach"]
    assert dict(now["vacation"])["beach"] == beach
    assert [s for s, _ in now["private"]][-1] == "anime-beachwear"
    assert "anime-beachwear" not in {sid for o in now if o != "private" for sid, _ in now[o]}


def test_new_ids_never_reuse_an_existing_one():
    assert not set(SPECIFIED) & {o["id"] for o in PRESERVED["outfits"]}


# ---------------------------------------------------------------- 3. real swimwear, real construction
def test_every_design_plans_to_swimwear_with_its_construction(template_catalog, entries):
    for d in COLLECTION["designs"]:
        plan = plan_outfit_stack(OutfitRequest.model_validate(
            {"prompt": d["id"], "design": {"collection": "anime-beachwear", "id": d["id"]}}), template_catalog)
        templates = [g.template_id for g in plan.garments]
        assert sorted(templates) == sorted(p["template"] for p in d["pieces"]), d["id"]
        assert set(templates) <= SWIM_TEMPLATES and all(template_catalog.get(t) for t in templates)
        assert all(g.style.design and g.style.design["id"] == d["id"] for g in plan.garments)
        assert entries[d["id"]]["rating"] == "private"  # swimwear: the adult gate decides


@pytest.mark.parametrize("design_id, feature", [
    ("beach-violet-halter", ("straps", "style", "halter")),
    ("beach-sport-racer", ("straps", "style", "racerback")),
    ("beach-noir-cutout", ("bodysuit", "cutouts", "waist-sides")),
    ("beach-midnight-string", ("brief", "preset", "string")),
    ("beach-indigo-highcut", ("brief", "preset", "french-cut")),
])
def test_the_named_construction_is_in_the_design(design_id, feature):
    part, key, value = feature
    design = registry.design("anime-beachwear", design_id)
    assert any((p.get("lingerie") or {}).get(part, {}).get(key) == value for p in design["pieces"])
    assert any(g.startswith("new:") or g.startswith("existing:") for g in design["geometry"])


def test_a_customised_design_recolours_every_piece(template_catalog):
    plan = plan_outfit_stack(OutfitRequest.model_validate(
        {"prompt": "x-variant", "design": {"collection": "anime-beachwear", "id": "beach-ocean-stripe",
                                           "color": "navy", "finish": "gloss"}}), template_catalog)
    assert {g.material.color_name for g in plan.garments} == {"navy"}
    assert {g.material.finish for g in plan.garments} == {"gloss"}


def test_an_unknown_design_is_refused_before_any_job():
    with pytest.raises(ValueError):
        OutfitRequest.model_validate({"prompt": "nope", "design": {"collection": "anime-beachwear", "id": "x"}})


# ---------------------------------------------------------------- 4. discoverable on its own
def test_the_api_lists_and_serves_the_collection():
    with TestClient(app) as client:
        listed = client.get("/v1/collections").json()["collections"]
        assert [c["id"] for c in listed] == ["anime-beachwear"] and listed[0]["designs"] == 12
        served = client.get("/v1/collections/anime-beachwear").json()
        assert [d["id"] for d in served["designs"]] == SPECIFIED
        assert all(d["rating"] == "private" and d["request"]["design"]["id"] == d["id"] for d in served["designs"])
        assert "_dir" not in served
        assert client.get("/v1/collections/nope").status_code == 404
        assert client.get("/v1/collections/anime-beachwear/previews/..%2Fcollection.json").status_code == 404


def test_its_own_group_and_its_own_private_style(entries):
    assert od.groups()["anime-beachwear"].private
    assert {entries[i]["group"] for i in SPECIFIED} == {"anime-beachwear"}
    style = next(s for s in oc.occasions()["private"].styles if s.id == "anime-beachwear")
    assert list(style.looks) == SPECIFIED and style.gallery == "anime-beachwear"
    served = {o["id"]: o for o in oc.catalogue(entries)}
    assert served["private"]["styles"][-1]["gallery"] == "anime-beachwear"


# ---------------------------------------------------------------- 5. new geometry is opt-in
@pytest.fixture(scope="module")
def measurements():
    document = GltfDocument.from_bytes(build_vrm(CALIBRATION_BODIES[1], spec="VRM1"))
    return measure_body(document, inspect_document(document))


def _template_lingerie(name: str) -> dict:
    path = next((ROOT / "assets/garment_templates").rglob(f"{name}.json"))
    return json.loads(path.read_text(encoding="utf-8"))["lingerie"]


def _build(measurements, kind, lingerie=None, **meta):
    return build_garment(kind, FitParameters(measurements=measurements,
                                             metadata={"forward": 1.0, **({"lingerie": lingerie} if lingerie else {}),
                                                       **meta}))


def test_defaults_build_exactly_what_they_built(measurements):
    """A spec that names the new fields at their defaults is the spec without them."""
    base = _template_lingerie("swim-one-piece-v2")
    explicit = merge_lingerie(base, {"bodysuit": {"cutouts": "none", "sideEaseMm": 0}})
    a, b = _build(measurements, "bodysuit-block", base), _build(measurements, "bodysuit-block", explicit)
    assert np.array_equal(a.positions, b.positions) and np.array_equal(a.indices, b.indices)
    plain, ruffled = _build(measurements, "swim-dress"), _build(measurements, "swim-dress", design={"hem": "none"})
    assert np.array_equal(plain.positions, ruffled.positions)


def test_cutouts_open_two_clean_windows_and_leave_the_rest(measurements):
    base = _template_lingerie("swim-one-piece-v2")
    plain = _build(measurements, "bodysuit-block", base)
    cut = _build(measurements, "bodysuit-block", merge_lingerie(base, {"bodysuit": {"cutouts": "waist-sides"}}))
    record = cut.metadata["lingerieBodysuit"]
    assert record["cutouts"] == "waist-sides" and record["cutTriangles"] > 0
    assert cut.vertex_count == plain.vertex_count  # triangles, not vertices: the records keep their meaning
    assert cut.indices.size < plain.indices.size and not cut.validate()


def test_racerback_straps_meet_beside_her_spine(measurements):
    base = _template_lingerie("swim-one-piece-v2")
    racer = _build(measurements, "bodysuit-block",
                   merge_lingerie(base, {"straps": {"style": "racerback"}, "bodysuit": {"back": "high"}}))
    plain = _build(measurements, "bodysuit-block", base)
    backs = [abs(a["back"]["position"][0]) for a in racer.metadata["lingerieBodysuit"]["anchors"].values()]
    plain_backs = [abs(a["back"]["position"][0]) for a in plain.metadata["lingerieBodysuit"]["anchors"].values()]
    assert len(backs) == 2 and max(backs) < 0.03 < min(plain_backs)


def test_a_ruffle_flutes_the_hem_only_when_asked(measurements):
    plain = _build(measurements, "swim-dress")
    ruffled = _build(measurements, "swim-dress", design={"hem": "ruffle"})
    moved = np.linalg.norm(ruffled.positions - plain.positions, axis=1)
    assert moved.max() > 0.01
    top = plain.positions[:, 1].max()
    assert moved[plain.positions[:, 1] > top - 0.05].max() < 1e-6  # the bodice is untouched
