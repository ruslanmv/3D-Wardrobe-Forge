"""BA4. The tattoo stages: clothes first, visible skin only, only ever appending.

On the dressed declared-adult calibration body (tests.body_art_support), never a library
character. The invariants are docs/BODY_ART_PLAN.md §0's.
"""

from __future__ import annotations

import json

import numpy as np

from tests.body_art_support import run
from wardrobe.body_art.catalog import BodyArtCatalog, BodyArtDesign
from wardrobe.body_art.contract import BodyArtRequest
from wardrobe.body_art.decorate import apply, decide
from wardrobe.engines.geometry_checks import body_points
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.garment_inventory import garment_inventory
from wardrobe.vrm.inspect import inspect_document

WINGS = {"design": "tribal-wings-01", "placement": "upper-back"}
LOTUS = {"design": "lotus-ornament-01", "placement": "lower-back"}
ARRAYS = (
    "nodes",
    "meshes",
    "materials",
    "accessors",
    "bufferViews",
    "images",
    "textures",
    "samplers",
    "skins",
)


def _without_look_ids(value):
    if isinstance(value, dict):
        return {k: _without_look_ids(v) for k, v in value.items() if k != "lookId"}
    if isinstance(value, list):
        return [_without_look_ids(v) for v in value]
    return value


def _decals(document: GltfDocument) -> list[dict]:
    return [
        n
        for n in document.nodes
        if ((n.get("extras") or {}).get("wardrobeForge") or {}).get("kind") == "bodyArt"
    ]


async def test_a_tattoo_only_appends_to_the_finished_outfit(orchestrator, store):
    """I2 + I5: the outfit is byte-for-byte the outfit; the tattoo is added after it."""
    plain_record, plain = await run(orchestrator, store, "underwear")
    inked_record, inked = await run(orchestrator, store, "underwear", bodyArt=[WINGS, LOTUS])
    a, b = GltfDocument.from_bytes(plain), GltfDocument.from_bytes(inked)
    for key in ARRAYS:
        before, after = _without_look_ids(a.gltf.get(key, [])), _without_look_ids(b.gltf.get(key, []))
        assert after[: len(before)] == before, key  # every entry of the outfit, unchanged and in place
    assert bytes(b.binary[: len(a.binary)]) == bytes(a.binary)
    assert len(_decals(b)) == 2 and not _decals(a)
    # The clothes were decided before the tattoo existed, and identically.
    for field in ("replaced_garments", "base_body", "layers"):
        assert getattr(inked_record.fit_report, field) == getattr(plain_record.fit_report, field), field
    assert [g.template_id for g in inked_record.plan.garments] == [
        g.template_id for g in plain_record.plan.garments
    ]
    report = inked_record.fit_report
    assert report.passed and report.weights_valid
    assert [e["applied"] for e in report.body_art] == [True, True]
    assert json.loads(report.model_dump_json(by_alias=True))["bodyArt"][0]["placement"] == "upper-back"


async def test_an_explicit_tattoo_never_changes_the_clothes(orchestrator, store):
    """I4: jacket + trousers + upper-back tattoo keeps the jacket and says why there is no tattoo."""
    plain_record, plain = await run(orchestrator, store, "black blazer + black trousers")
    record, output = await run(orchestrator, store, "black blazer + black trousers", bodyArt=[WINGS])
    assert record.state.value == "completed" and output is not None
    assert fingerprint_without_extras(output) == fingerprint_without_extras(plain)
    (entry,) = record.fit_report.body_art
    assert entry["applied"] is False
    assert entry["message"].startswith("Upper back tattoo not applied — that area is covered by the outfit")
    assert entry["message"] in record.fit_report.warnings
    assert not _decals(GltfDocument.from_bytes(output))


def fingerprint_without_extras(vrm: bytes):
    document = GltfDocument.from_bytes(vrm)
    gltf = _without_look_ids(document.gltf)
    gltf.get("extras", {}).get("wardrobeForge", {}).pop("bodyArt", None)
    return json.dumps(gltf, sort_keys=True), bytes(document.binary)


async def test_a_tattoo_is_never_her_body_and_never_her_clothes(orchestrator, store):
    """I7: the inventory, the strip plan's input and body sampling do not see it."""
    _r, plain = await run(orchestrator, store, "underwear")
    _r, inked = await run(orchestrator, store, "underwear", bodyArt=[WINGS])
    a, b = GltfDocument.from_bytes(plain), GltfDocument.from_bytes(inked)
    assert [(g.slot, g.mesh, g.primitive) for g in garment_inventory(b)] == [
        (g.slot, g.mesh, g.primitive) for g in garment_inventory(a)
    ]
    assert np.array_equal(body_points(b), body_points(a))
    # And building the next outfit on the tattooed look takes off exactly what it would have.
    over_plain, _ = await run(orchestrator, store, "red bodycon mini dress", source=plain)
    over_inked, _ = await run(orchestrator, store, "red bodycon mini dress", source=inked)
    assert over_inked.fit_report.replaced_garments == over_plain.fit_report.replaced_garments
    assert over_inked.fit_report.base_body == over_plain.fit_report.base_body


async def test_removing_takes_off_forge_body_art_and_nothing_else(orchestrator, store):
    """I6."""
    _r, inked = await run(orchestrator, store, "underwear", bodyArt=[WINGS, LOTUS])
    document = GltfDocument.from_bytes(inked)
    before = json.loads(json.dumps(document.gltf))
    apply(
        document,
        inspect_document(document),
        [],
        BodyArtCatalog.from_directory("assets/body_art"),
        ["upper-back"],
    )
    changed = [
        i for i, (x, y) in enumerate(zip(before["nodes"], document.gltf["nodes"], strict=True)) if x != y
    ]
    assert len(changed) == 1
    tag = before["nodes"][changed[0]]["extras"]["wardrobeForge"]
    assert tag["kind"] == "bodyArt" and tag["placement"] == "upper-back"
    assert "mesh" not in document.gltf["nodes"][changed[0]]
    assert [n["extras"]["wardrobeForge"]["placement"] for n in _decals(document) if "mesh" in n] == [
        "lower-back"
    ]


async def test_a_rated_placement_is_gated_like_a_garment(orchestrator, store):
    """I9: a design raised to swimwear needs the declaration; the outfit is delivered either way."""
    _r, plain = await run(orchestrator, store, "underwear")
    base = BodyArtCatalog.from_directory("assets/body_art")
    raised = BodyArtDesign.model_validate(
        {**base.get("tribal-wings-01").model_dump(by_alias=True), "rating": {"upper-back": "swimwear"}}
    )
    catalog = BodyArtCatalog([raised if d.id == raised.id else d for d in base.all()], base.root)
    document = GltfDocument.from_bytes(plain)
    terms = inspect_document(document).license
    item = BodyArtRequest(**WINGS)
    (refused,) = decide(document, [item], catalog, depicts_adult=False, terms=terms)
    assert refused.decal is None and "adult" in refused.reason.lower()
    (allowed,) = decide(document, [item], catalog, depicts_adult=True, terms=terms)
    assert allowed.decal is not None and allowed.rating == "swimwear"


async def test_a_job_with_no_body_art_never_reads_it(orchestrator, store, monkeypatch):
    """I1, at the stage: neither body-art stage parses anything for a job that asked for none."""
    from wardrobe.body_art import decorate

    def boom(*_args, **_kwargs):
        raise AssertionError("body art ran for a job that asked for none")

    monkeypatch.setattr(decorate, "decide", boom)
    monkeypatch.setattr("wardrobe.pipeline.analyze_exposed_skin.decide", boom)
    record, output = await run(orchestrator, store, "underwear")
    assert output is not None and record.fit_report.body_art is None
