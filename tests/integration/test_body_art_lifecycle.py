"""BA6. Tattoo-only jobs, and a tattoo's life across the looks built on it (docs/BODY_ART_PLAN.md §3).

The chain the plan's exit names, on the dressed declared-adult calibration body: lingerie
with a lower-back tattoo → a tattoo-only job adding the upper back → a tee over it (both
decals dropped, both recipes kept) → lingerie again (both re-applied, as they were). A tee
rather than a jacket: on this body a later top layers *under* a jacket rather than taking it
off, so after a jacket her back stays covered — which is the rule working, not the test.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from tests.body_art_support import run
from tests.conftest import job_request
from wardrobe.body_art.lifecycle import json_chunk, live_placements
from wardrobe.domain.jobs import CreateJobRequest, FailureReason, JobState
from wardrobe.vrm.document import GltfDocument

LOTUS = {"design": "lotus-ornament-01", "placement": "lower-back"}
WINGS = {"design": "tribal-wings-01", "placement": "upper-back", "ink": "#2a1030"}


async def tattoo_only(orchestrator, store, source: bytes, **fields):
    """A job with no outfit: body art on the look ``source`` is."""
    await store.put("sources/body-art.vrm", source)
    payload = job_request("sources/body-art.vrm", "unused")
    del payload["outfit"]
    payload["avatar"]["depictsAdult"] = True
    payload.update(fields)
    record = await orchestrator.run_now(CreateJobRequest.model_validate(payload))
    output = await store.get(f"looks/{record.look.id}/look.vrm") if record.look else None
    return record, output


def states(output: bytes) -> dict[str, str]:
    return {r["placement"]: r["state"] for r in json_chunk(output)["extras"]["wardrobeForge"]["bodyArt"]}


def decal_positions(output: bytes, placement: str) -> np.ndarray:
    document = GltfDocument.from_bytes(output)
    for node in document.nodes:
        tag = (node.get("extras") or {}).get("wardrobeForge") or {}
        if tag.get("kind") == "bodyArt" and tag.get("placement") == placement and "mesh" in node:
            primitive = document.meshes[node["mesh"]]["primitives"][0]
            return document.read_accessor(primitive["attributes"]["POSITION"])
    raise AssertionError(f"no live decal at {placement}")


def without_root_extras(output: bytes) -> dict:
    gltf = json.loads(json.dumps(json_chunk(output)))
    gltf.pop("extras", None)
    return gltf


async def test_a_tattoo_follows_her_through_the_looks(orchestrator, store):
    record_a, a = await run(orchestrator, store, "black lace lingerie set", bodyArt=[LOTUS])
    assert a is not None, record_a.error
    assert states(a) == {"lower-back": "applied"}

    # Tattoo-only: the clothes are the look's, untouched; only body art is appended (I2, I5).
    record_b, b = await tattoo_only(orchestrator, store, a, bodyArt=[WINGS])
    assert b is not None, record_b.error
    assert record_b.plan is None and record_b.state is JobState.COMPLETED
    doc_a, doc_b = GltfDocument.from_bytes(a), GltfDocument.from_bytes(b)
    assert bytes(doc_b.binary)[: len(doc_a.binary)] == bytes(doc_a.binary)
    gltf_a, gltf_b = without_root_extras(a), without_root_extras(b)
    for key in ("nodes", "meshes", "materials", "accessors", "skins"):
        assert gltf_b[key][: len(gltf_a[key])] == gltf_a[key], key  # nothing of hers or the outfit's changed
    forge = json_chunk(b)["extras"]["wardrobeForge"]
    assert forge["baseLookId"] == record_a.look.id and forge["lookId"] == record_b.look.id
    assert live_placements(doc_b) == {"lower-back", "upper-back"}
    assert states(b) == {"upper-back": "applied", "lower-back": "applied"}
    by_placement = {entry["placement"]: entry for entry in record_b.fit_report.body_art}
    assert by_placement["lower-back"]["inherited"] and by_placement["lower-back"]["message"].endswith("kept")
    assert record_b.look.name == f"{record_a.look.name} · Tribal Wings"
    look_a = json.loads(await store.get(f"looks/{record_a.look.id}/look.json"))
    look_b = json.loads(await store.get(f"looks/{record_b.look.id}/look.json"))
    assert look_b["garments"] == look_a["garments"] and look_b["rating"] == look_a["rating"]
    assert look_b["baseLookId"] == record_a.look.id

    # A tee over it: both decals leave the geometry (no ink under clothes), both recipes stay.
    record_c, c = await run(orchestrator, store, "white tee", source=b)
    assert c is not None, record_c.error
    assert live_placements(GltfDocument.from_bytes(c)) == set()
    assert states(c) == {"upper-back": "covered", "lower-back": "covered"}
    assert any("comes back on a look that shows it" in w for w in record_c.fit_report.warnings)

    # Lingerie again: both back, the same tattoo — same design, placement, settings, geometry.
    record_d, d = await run(orchestrator, store, "black lace lingerie set", source=c)
    assert d is not None, record_d.error
    assert states(d) == {"upper-back": "applied", "lower-back": "applied"}
    for placement in ("upper-back", "lower-back"):
        np.testing.assert_allclose(decal_positions(d, placement), decal_positions(b, placement), atol=1e-6)
    recipe = next(
        r for r in json_chunk(d)["extras"]["wardrobeForge"]["bodyArt"] if r["placement"] == "upper-back"
    )
    assert recipe["ink"] == WINGS["ink"]

    # Removing one takes off that decal and its recipe, and nothing else (I6).
    record_e, e = await tattoo_only(orchestrator, store, d, bodyArtRemove=["lower-back"])
    assert e is not None, record_e.error
    assert live_placements(GltfDocument.from_bytes(e)) == {"upper-back"}
    assert states(e) == {"upper-back": "applied"}
    assert record_e.look.name.endswith("· without lower back")


async def test_a_tattoo_only_job_needs_a_finished_look_and_a_change(orchestrator, store):
    from tests.body_art_support import dressed_body

    # Straight onto an avatar as uploaded: clothes come first.
    record, output = await tattoo_only(orchestrator, store, dressed_body(), bodyArt=[WINGS])
    assert output is None and record.state is JobState.REJECTED
    assert record.reason is FailureReason.BODY_ART_NEEDS_LOOK

    # On a look whose clothes cover the spot: refused, with the reason, and no copy of the look.
    record_t, tee = await run(orchestrator, store, "white tee")
    assert tee is not None, record_t.error
    record, output = await tattoo_only(orchestrator, store, tee, bodyArt=[WINGS])
    assert output is None and record.state is JobState.REJECTED
    assert record.reason is FailureReason.BODY_ART_NOT_APPLIED
    assert "covered by the outfit" in record.error
    record, output = await tattoo_only(orchestrator, store, tee, bodyArtRemove=["nape"])
    assert output is None and record.reason is FailureReason.BODY_ART_NOT_APPLIED


def test_only_a_body_art_job_may_leave_out_the_outfit():
    avatar = {"storageKey": "k"}
    with pytest.raises(ValueError, match="outfit is required"):
        CreateJobRequest.model_validate({"avatar": avatar})
    request = CreateJobRequest.model_validate({"avatar": avatar, "bodyArt": [WINGS]})
    assert request.body_art_only
    assert not CreateJobRequest.model_validate({"avatar": avatar, "outfit": {"prompt": "tee"}}).body_art_only

    from apps.api.routes.studio import LibraryJobRequest

    with pytest.raises(ValueError, match="baseLookId"):
        LibraryJobRequest.model_validate({"bodyArt": [WINGS]})
    with pytest.raises(ValueError, match="outfit is required"):
        LibraryJobRequest.model_validate({"baseLookId": "look_x"})
    assert LibraryJobRequest.model_validate({"bodyArt": [WINGS], "baseLookId": "look_x"}).outfit is None
