"""MG1–MG3. Model Girl's issues, and Auto Foundation (``options.ensureFoundation``).

Model Girl's dress is filed as a VRoid *Tops* and its hem is cut out of its texture's
alpha. Read as a top, it stayed on under a new skirt; read as body, its invisible hem
pushed the skirt out into a bell. Pinned here: what a texture hides is not her (MG1); a
Tops drawn to dress length covers her lower half too (MG2); and Auto Foundation adds only
the foundation halves she lacks, keeps one she already wears, lets a bikini replace it,
and carries it — with the jeans — when only the top changes (MG3).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests.conftest import job_request
from tests.vroid_support import dress_like_vroid
from wardrobe.domain.jobs import CreateJobRequest
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.garment_inventory import garment_inventory
from wardrobe.vrm.inspect import inspect_document

LIBRARY = Path(__file__).resolve().parents[2] / "assets" / "library"
MODEL_GIRL = LIBRARY / "vroid" / "vroid-model-girl.vrm"


@pytest.fixture(scope="module")
def body() -> bytes:
    return build_vrm(CALIBRATION_BODIES[1], spec="VRM1")


async def dress(orchestrator, store, source: bytes, prompt: str, *, adult: bool = False, **options):
    await store.put("sources/auto.vrm", source)
    payload = job_request("sources/auto.vrm", prompt, **options)
    payload["avatar"]["depictsAdult"] = adult
    record = await orchestrator.run_now(CreateJobRequest.model_validate(payload))
    assert record.state == "completed", record.error
    return record, await store.get(f"looks/{record.look.id}/look.vrm")


def worn(data: bytes) -> list[tuple[str, str, str]]:
    """(slot, role, name) of every garment she wears, her own and the Forge's."""
    return [
        (g.slot, g.role, g.material.split(" [")[0]) for g in garment_inventory(GltfDocument.from_bytes(data))
    ]


def foundation(data: bytes) -> dict[str, bytes]:
    """name -> the vertex bytes of each Forge foundation garment: equal bytes, the same garment."""
    document = GltfDocument.from_bytes(data)
    out = {}
    for node in document.nodes:
        tag = (node.get("extras") or {}).get("wardrobeForge") or {}
        if tag.get("kind") == "garment" and tag.get("role") == "foundation" and "mesh" in node:
            primitive = document.meshes[node["mesh"]]["primitives"][0]
            out[tag["templateId"]] = document.read_accessor(primitive["attributes"]["POSITION"]).tobytes()
    return out


def long_top(vrm_bytes: bytes) -> bytes:
    """Her own clothes as Model Girl's are: a Tops that hangs to mid-thigh, and Bottoms."""
    document = GltfDocument.from_bytes(dress_like_vroid(vrm_bytes))
    info = inspect_document(document)
    world = document.world_matrices()
    hip = float(world[info.humanoid_bones["leftUpperLeg"]][1, 3])
    knee = float(world[info.humanoid_bones["leftLowerLeg"]][1, 3])
    body = document.meshes[0]["primitives"][0]
    positions = document.read_accessor(body["attributes"]["POSITION"])
    triangles = document.read_accessor(body["indices"]).astype(np.uint32).reshape(-1, 3)
    # A coarse body's thigh is one triangle hip to knee: keep what reaches above mid-thigh.
    keep = triangles[positions[triangles][:, :, 1].max(axis=1) > hip - (hip - knee) * 0.6]
    tops = next(
        p
        for p in document.meshes[0]["primitives"]
        if "Tops" in document.materials[p["material"]].get("name", "")
    )
    tops["indices"] = document.add_accessor(keep.reshape(-1, 1))
    return document.to_bytes()


# ----------------------------------------------------------------------
# MG1 / MG2: what she wears, read from what is drawn
# ----------------------------------------------------------------------
def test_a_top_to_her_hips_is_a_top_and_one_to_mid_thigh_is_a_dress(body):
    short = {g.slot: g for g in garment_inventory(GltfDocument.from_bytes(dress_like_vroid(body)))}
    long = {g.slot: g for g in garment_inventory(GltfDocument.from_bytes(long_top(body)))}
    assert short["tops"].regions == {"upper"} and not short["tops"].dress_length
    assert long["tops"].regions == {"upper", "lower"} and long["tops"].dress_length


@pytest.mark.skipif(not MODEL_GIRL.exists(), reason="the library avatars are fetched by `make library`")
def test_model_girls_dress_is_a_dress_and_its_invisible_hem_is_not_her():
    from wardrobe.engines.geometry_checks import body_points

    document = GltfDocument.from_bytes(MODEL_GIRL.read_bytes())
    tops = next(g for g in garment_inventory(document) if g.slot == "tops")
    assert tops.dress_length and tops.regions == {"upper", "lower"}
    info = inspect_document(document)
    knee = float(document.world_matrices()[info.humanoid_bones["leftLowerLeg"]][1, 3])
    points = body_points(document)
    shins = points[points[:, 1] < knee]
    # Her own legs only: the dress's alpha-cut hem 20+ cm out round her shins is gone.
    assert np.abs(shins[:, 0]).max() < 0.16 and np.abs(shins[:, 2]).max() < 0.16


# ----------------------------------------------------------------------
# MG3: Auto Foundation
# ----------------------------------------------------------------------
async def test_off_by_default_the_plan_is_what_it_always_was(orchestrator, store, body):
    record, _ = await dress(
        orchestrator, store, dress_like_vroid(body), "white crop top + blue straight jeans"
    )
    assert [g.role for g in record.plan.garments] == ["main", "main"]


async def test_the_proposal_crop_top_and_jeans_then_only_the_top_changes(orchestrator, store, body):
    first, look = await dress(
        orchestrator,
        store,
        dress_like_vroid(body),
        "white crop top + blue straight jeans",
        ensureFoundation=True,
    )
    assert set(first.fit_report.replaced_garments) == {"tops", "bottoms"}
    names = [name for _slot, _role, name in worn(look)]
    assert "F00_000_01_Tops_01_CLOTH" not in names and "F00_000_01_Bottoms_01_CLOTH" not in names
    assert {(slot, role) for slot, role, _ in worn(look) if role == "foundation"} == {
        ("tops", "foundation"),
        ("bottoms", "foundation"),
    }
    before = foundation(look)
    assert set(before) == {"top-tube-v1", "shorts-slip-v1"}  # clothes, not underwear: no declaration needed

    second, changed = await dress(orchestrator, store, look, "pink fitted tee", ensureFoundation=True)
    assert [g.template_id for g in second.plan.garments] == ["top-tee-v1"]  # nothing added: she has one
    assert second.fit_report.replaced_garments == ["tops"]
    assert foundation(changed) == before  # the same foundation, carried
    names = [name for _slot, _role, name in worn(changed)]
    assert "Blue Straight Jeans" in names and "Pink Basic Tee" in names
    assert not any("Crop" in name for name in names)


async def test_an_avatar_declared_adult_gets_bralette_and_briefs(orchestrator, store, body):
    record, look = await dress(
        orchestrator,
        store,
        dress_like_vroid(body),
        "red bodycon mini dress",
        adult=True,
        ensureFoundation=True,
    )
    assert [g.template_id for g in record.plan.garments] == [
        "under-bralette-v2",
        "under-briefs-v2",
        "dress-mini-bodycon-v1",
    ]
    assert set(foundation(look)) == {"under-bralette-v2", "under-briefs-v2"}


async def test_a_bikini_replaces_the_foundation_rather_than_going_over_it(orchestrator, store, body):
    _first, look = await dress(
        orchestrator,
        store,
        dress_like_vroid(body),
        "red bodycon mini dress",
        adult=True,
        ensureFoundation=True,
    )
    record, swim = await dress(
        orchestrator, store, look, "red triangle bikini", adult=True, ensureFoundation=True
    )
    assert all(g.category == "swimwear" for g in record.plan.garments)  # no neutral half under it
    assert not {"under-bralette-v2", "under-briefs-v2"} & set(foundation(swim))


async def test_a_dress_length_top_comes_off_under_a_skirt(orchestrator, store, body):
    record, look = await dress(
        orchestrator, store, long_top(body), "grey a-line skirt", ensureFoundation=True
    )
    assert "tops" in record.fit_report.replaced_garments
    assert "F00_000_01_Tops_01_CLOTH" not in [name for _s, _r, name in worn(look)]
    assert set(foundation(look)) == {"top-tube-v1", "shorts-slip-v1"}


async def test_without_it_a_dress_length_top_stays_on_under_a_skirt(orchestrator, store, body):
    record, look = await dress(orchestrator, store, long_top(body), "grey a-line skirt")
    assert "tops" not in record.fit_report.replaced_garments  # a skirt alone cannot bare her chest
    assert "F00_000_01_Tops_01_CLOTH" in [name for _s, _r, name in worn(look)]


async def test_shoes_alone_want_no_foundation(orchestrator, store, body):
    record, _ = await dress(
        orchestrator, store, dress_like_vroid(body), "black stiletto ankle boots", ensureFoundation=True
    )
    assert [g.category for g in record.plan.garments] == ["shoes"]


async def test_the_source_is_never_touched(orchestrator, store, body):
    source = dress_like_vroid(body)
    await dress(orchestrator, store, source, "white crop top + blue straight jeans", ensureFoundation=True)
    assert await store.get("sources/auto.vrm") == source
