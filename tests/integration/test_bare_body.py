"""Bare is private, gated, authored-only, and never calls the garment/proxy builders."""
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.conftest import job_request
from wardrobe.domain.jobs import CreateJobRequest, JobState
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.garment_inventory import garment_inventory


def request(key, **options):
    payload = job_request(key, "Bare authored body", template_id="body-bare-v1",
                          baseBody="bare", private=True, **options)
    payload["avatar"]["depictsAdult"] = True
    return payload


async def test_gate_order_and_no_generation(orchestrator, store, vrm_bytes):
    await store.put("sources/bare.vrm", vrm_bytes)
    payload = request("sources/bare.vrm")
    # VRM1 calibration fixture refuses explicit usage; this must win over switch/declaration.
    with patch("wardrobe.vrm.body_completion.complete_body", side_effect=AssertionError("no proxy")), \
         patch("wardrobe.pipeline.generate_garment.generate", side_effect=AssertionError("no garment")):
        result = await orchestrator.run_now(CreateJobRequest.model_validate(payload))
    assert result.state is JobState.REJECTED
    assert result.reason == "body_surface_not_permitted"
    assert result.look is None
    doc = GltfDocument.from_bytes(vrm_bytes)
    doc.gltf["extensions"]["VRMC_vrm"]["meta"]["allowExcessivelySexualUsage"] = True
    await store.put("sources/bare.vrm", doc.to_bytes())
    result = await orchestrator.run_now(CreateJobRequest.model_validate(payload))
    assert "WARDROBE_ADULT_BODY_SURFACE" in result.error
    orchestrator.settings.wardrobe_adult_body_surface = True
    payload["avatar"]["depictsAdult"] = False
    result = await orchestrator.run_now(CreateJobRequest.model_validate(payload))
    assert "depictsAdult" in result.error


@pytest.mark.parametrize("change", [{"baseBody": "preserve"}, {"ensureFoundation": True},
                                     {"foundationColor": "red"}])
def test_conflicting_requests_refused(change):
    payload = request("sources/a.vrm")
    payload["options"].update(change)
    with pytest.raises(ValueError):
        CreateJobRequest.model_validate(payload)


async def test_incomplete_o_refused_without_proxy(orchestrator, store):
    path = Path(__file__).parents[2] / "assets/library/vroid/vroid-avatar-sample-o.vrm"
    if not path.exists():
        pytest.skip("library AvatarSample_O unavailable")
    await store.put("sources/o.vrm", path.read_bytes())
    orchestrator.settings.wardrobe_adult_body_surface = True
    with patch("wardrobe.vrm.body_completion.complete_body", side_effect=AssertionError("no proxy")), \
         patch("wardrobe.pipeline.generate_garment.generate", side_effect=AssertionError("no garment")):
        result = await orchestrator.run_now(CreateJobRequest.model_validate(request("sources/o.vrm")))
    assert result.reason == "body-incomplete-for-bare", result.error
    assert result.look is None


async def test_complete_bare_tag_and_no_garments(orchestrator, store, vrm_bytes):
    # Isolate assembly from geometric coverage, which is exercised on the real library matrix.
    from wardrobe.vrm.body_integrity import BodyIntegrity, RegionCheck
    doc = GltfDocument.from_bytes(vrm_bytes)
    doc.gltf["extensions"]["VRMC_vrm"]["meta"]["allowExcessivelySexualUsage"] = True
    await store.put("sources/a.vrm", doc.to_bytes())
    orchestrator.settings.wardrobe_adult_body_surface = True
    with patch("wardrobe.pipeline.bare_body.check_body", return_value=BodyIntegrity({"upper": RegionCheck(True, 1)})), \
         patch("wardrobe.pipeline.generate_garment.generate", side_effect=AssertionError("no garment")):
        result = await orchestrator.run_now(CreateJobRequest.model_validate(request("sources/a.vrm")))
    assert result.state is JobState.COMPLETED, result.error
    output = GltfDocument.from_bytes(await store.get(f"looks/{result.look.id}/look.vrm"))
    assert output.gltf["extras"]["wardrobeForge"]["bare"] is True
    assert not garment_inventory(output)
    assert not any("bodyProxy" in str(m.get("extras", {})) for m in output.meshes)
    assert result.request.options.private


async def test_real_authored_body_and_painted_skin(orchestrator, store):
    path = Path(__file__).parents[2] / "assets/library/fem_vroid.vrm"
    if not path.exists():
        pytest.skip("library VRoid Female unavailable")
    await store.put("sources/fem.vrm", path.read_bytes())
    orchestrator.settings.wardrobe_adult_body_surface = True
    from wardrobe.library import AvatarLibrary
    payload = request("sources/fem.vrm")
    entry = next(a for a in AvatarLibrary.from_directory(path.parent).avatars if a.slug == "fem-vroid")
    own = entry.avatar_input()
    own.pop("url", None)
    own["storageKey"] = "sources/fem.vrm"
    payload["avatar"] = own
    result = await orchestrator.run_now(CreateJobRequest.model_validate(payload))
    assert result.state is JobState.COMPLETED, result.error
    assert result.fit_report.base_body["paintedSkin"]["shows"] is False
    output = GltfDocument.from_bytes(await store.get(f"looks/{result.look.id}/look.vrm"))
    original = GltfDocument.from_bytes(path.read_bytes())
    # Texture restoration is allowed; no authored POSITION data is changed or invented.
    sources = {p["attributes"]["POSITION"] for m in original.meshes for p in m["primitives"]}
    for mesh in output.meshes:
        for primitive in mesh["primitives"]:
            accessor = primitive["attributes"]["POSITION"]
            assert accessor in sources
            assert (original.read_accessor(accessor) == output.read_accessor(accessor)).all()
    assert not garment_inventory(output)
    for i, material in enumerate(original.materials):
        assert output.materials[i].get("normalTexture") == material.get("normalTexture")
    assert output.gltf["extras"]["wardrobeForge"]["bare"]


def test_protected_anatomical_material_is_never_repainted():
    from wardrobe.vrm.inspect import inspect_document
    from wardrobe.vrm.measure import measure_body
    from wardrobe.vrm.skin_restore import restore_skin
    path = Path(__file__).parents[2] / "assets/library/fem_vroid.vrm"
    if not path.exists():
        pytest.skip("library VRoid Female unavailable")
    doc = GltfDocument.from_bytes(path.read_bytes())
    protected = {i for i, m in enumerate(doc.materials) if "Body" in m.get("name", "") and "SKIN" in m.get("name", "")}
    assert protected
    original = doc.to_bytes()
    result = restore_skin(doc, measure_body(doc, inspect_document(doc)), set(),
                          preserve_normals=True, protected_materials=protected)
    assert result is None
    assert doc.to_bytes() == original


async def test_authored_anatomy_cannot_be_stripped_as_garment(settings):
    from types import SimpleNamespace

    from wardrobe.domain.jobs import JobRecord
    from wardrobe.errors import BodyIncompleteForBare
    from wardrobe.pipeline.bare_body import prepare
    from wardrobe.vrm.inspect import inspect_document
    from wardrobe.vrm.measure import measure_body
    path = Path(__file__).parents[2] / "assets/library/fem_vroid.vrm"
    if not path.exists():
        pytest.skip("library VRoid Female unavailable")
    doc = GltfDocument.from_bytes(path.read_bytes())
    node = next(n for n in doc.nodes if "mesh" in n and any(
        "Body" in doc.materials[p.get("material", 0)].get("name", "")
        for p in doc.meshes[n["mesh"]]["primitives"]))
    extras = node.setdefault("extras", {})
    extras["authoredAnatomy"] = True
    extras["wardrobeForge"] = {"kind": "garment", "slot": "tops"}
    original = doc.to_bytes()
    settings.wardrobe_adult_body_surface = True
    info = inspect_document(doc)
    context = SimpleNamespace(document=doc, info=info, measurements=measure_body(doc, info),
                              settings=settings, record=JobRecord.queued(
                                  CreateJobRequest.model_validate(request("sources/a.vrm"))))
    with pytest.raises(BodyIncompleteForBare, match="anatomy was classified as clothing"):
        await prepare(context)
    assert doc.to_bytes() == original
