"""FC2. Her foundation in another colour, on the look she has on — and nothing else changed.

The Try-On scenario: a black bodycon mini dress and boots over a white foundation, on the
declared-adult calibration body; she asks whether black would look better underneath, and
the look comes back with a black foundation. Pinned here: every buffer byte, every mesh and
every material but the foundation's is the base look's — the dress and the boots are not
remade — the foundation's colour is black in both its PBR factor and its toon shade, with its
alpha and shade ratio kept; the tag records black so the next look keeps it; asking for the
colour it already is, or recolouring a look with no Forge foundation, is refused with the
reason; and a job without an outfit still needs one of the things such a job can do.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.body_art_support import dressed_body
from tests.conftest import job_request
from wardrobe.domain.jobs import CreateJobRequest
from wardrobe.pipeline.plan_outfit import COLORS, hex_to_linear_rgba
from wardrobe.vrm.document import GltfDocument

OUTFIT = "black bodycon mini dress + black stretch leather over-the-knee boots"


async def dress(orchestrator, store, prompt: str, source: bytes | None = None, **options):
    await store.put("sources/fc2.vrm", source if source is not None else dressed_body())
    payload = job_request("sources/fc2.vrm", prompt, **options)
    payload["avatar"]["depictsAdult"] = True
    record = await orchestrator.run_now(CreateJobRequest.model_validate(payload))
    return record, (await store.get(f"looks/{record.look.id}/look.vrm") if record.look else None)


async def recolour(orchestrator, store, source: bytes, colour: str):
    """A job with no outfit: only the foundation of the look ``source`` is, in ``colour``."""
    await store.put("sources/fc2-look.vrm", source)
    payload = job_request("sources/fc2-look.vrm", "unused", foundationColor=colour)
    del payload["outfit"]
    payload["avatar"]["depictsAdult"] = True
    record = await orchestrator.run_now(CreateJobRequest.model_validate(payload))
    return record, (await store.get(f"looks/{record.look.id}/look.vrm") if record.look else None)


def foundation(document: GltfDocument) -> dict[int, dict]:
    """material index -> its node tag, for every Forge foundation material."""
    out = {}
    for node in document.nodes:
        tag = (node.get("extras") or {}).get("wardrobeForge") or {}
        if tag.get("kind") == "garment" and tag.get("role") == "foundation" and "mesh" in node:
            for primitive in document.meshes[node["mesh"]]["primitives"]:
                out[primitive["material"]] = tag
    return out


@pytest.fixture
async def white_under_the_dress(orchestrator, store):
    record, look = await dress(orchestrator, store, OUTFIT, ensureFoundation=True, foundationColor="white")
    assert look is not None, record.error
    document = GltfDocument.from_bytes(look)
    assert foundation(document), "the dress went on without a foundation under it"
    return look


async def test_black_underneath_changes_only_the_foundation(orchestrator, store, white_under_the_dress):
    record, black = await recolour(orchestrator, store, white_under_the_dress, "black")
    assert black is not None, record.error
    before, after = GltfDocument.from_bytes(white_under_the_dress), GltfDocument.from_bytes(black)

    # Not refitted: the same geometry, weights and images, byte for byte, and the same meshes.
    assert bytes(after.binary) == bytes(before.binary)
    assert after.gltf["meshes"] == before.gltf["meshes"]
    assert after.gltf["accessors"] == before.gltf["accessors"]

    under = foundation(after)
    for index, material in enumerate(after.materials):
        if index not in under:
            assert material == before.materials[index], material.get("name")  # the dress, the boots
    black_linear = hex_to_linear_rgba(COLORS["black"])[:3]
    for index, tag in under.items():
        assert tag["foundationColor"] == "black"
        new, old = after.materials[index], before.materials[index]
        factor = new["pbrMetallicRoughness"]["baseColorFactor"]
        assert factor[:3] == pytest.approx(black_linear, abs=1e-4)
        assert factor[3] == old["pbrMetallicRoughness"]["baseColorFactor"][3]  # alpha kept
        mtoon_new = (new.get("extensions") or {}).get("VRMC_materials_mtoon")
        mtoon_old = (old.get("extensions") or {}).get("VRMC_materials_mtoon")
        if mtoon_old:
            ratio_old = mtoon_old["shadeColorFactor"][0] / old["pbrMetallicRoughness"]["baseColorFactor"][0]
            assert mtoon_new["shadeColorFactor"][0] / factor[0] == pytest.approx(ratio_old, rel=1e-3)
            rest = {k: v for k, v in mtoon_new.items() if k != "shadeColorFactor"}
            assert rest == {k: v for k, v in mtoon_old.items() if k != "shadeColorFactor"}

    look = record.look
    assert look.name and "·" not in look.name  # her look's own name, not a tattoo suffix


async def test_the_same_colour_again_is_refused_with_the_reason(orchestrator, store, white_under_the_dress):
    record, output = await recolour(orchestrator, store, white_under_the_dress, "white")
    assert output is None
    assert record.reason == "foundation_not_recoloured"
    assert "already white" in record.error


async def test_a_look_without_a_forge_foundation_has_nothing_to_recolour(orchestrator, store):
    record, plain = await dress(orchestrator, store, OUTFIT)  # no ensureFoundation
    assert plain is not None, record.error
    if foundation(GltfDocument.from_bytes(plain)):
        pytest.skip("this body got a foundation without asking; the refusal is covered elsewhere")
    refused, output = await recolour(orchestrator, store, plain, "black")
    assert output is None and refused.reason == "foundation_not_recoloured"


def test_a_job_without_an_outfit_must_change_something():
    payload = job_request("sources/x.vrm", "unused")
    del payload["outfit"]
    with pytest.raises(ValidationError):
        CreateJobRequest.model_validate(payload)
    payload["options"]["foundationColor"] = "black"
    assert CreateJobRequest.model_validate(payload).recolours_foundation


def test_the_library_route_takes_a_recolour_only_on_a_named_look():
    from apps.api.routes.studio import LibraryJobRequest

    body = {"options": {"foundationColor": "black"}}
    with pytest.raises(ValidationError):
        LibraryJobRequest.model_validate(body)  # which look?
    assert LibraryJobRequest.model_validate({**body, "baseLookId": "look_1"}).outfit is None
    with pytest.raises(ValidationError):
        LibraryJobRequest.model_validate({"baseLookId": "look_1"})  # and changing what?
