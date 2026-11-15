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


async def test_anatomy_labelled_material_detected_as_clothing_is_kept(settings):
    """AF4. A primitive whose own material the author labelled anatomical stays on her body.

    A garment detector reads shape and colour; a dark, tight surface between her thighs reads like
    briefs. The author's material label wins: the primitive is not stripped, the job does not refuse
    for it, its geometry is byte-identical afterwards, and the report names what was kept.
    """
    import hashlib
    from types import SimpleNamespace

    from wardrobe.domain.jobs import JobRecord
    from wardrobe.pipeline.bare_body import prepare
    from wardrobe.vrm.inspect import inspect_document
    from wardrobe.vrm.measure import measure_body
    path = Path(__file__).parents[2] / "assets/library/AvatarSample_C.vrm"
    if not path.exists():
        pytest.skip("library AvatarSample C unavailable")
    doc = GltfDocument.from_bytes(path.read_bytes())
    detected = garment_inventory(doc)
    assert detected, "the fixture must have clothing to take off"
    # The garment with a material of its own (not shared with any other detected primitive).
    counts = {}
    for g in detected:
        m = doc.meshes[g.mesh]["primitives"][g.primitive]["material"]
        counts[m] = counts.get(m, 0) + 1
    target = next(g for g in detected if g.slot == "bottoms"
                  and counts[doc.meshes[g.mesh]["primitives"][g.primitive]["material"]] == 1)
    material = doc.meshes[target.mesh]["primitives"][target.primitive]["material"]
    # The author marks the material anatomical; its name still reads like clothing to the detector.
    doc.materials[material].setdefault("extras", {})["authoredAnatomy"] = True
    assert any(g.mesh == target.mesh and g.primitive == target.primitive for g in garment_inventory(doc))
    position = doc.meshes[target.mesh]["primitives"][target.primitive]["attributes"]["POSITION"]
    before = hashlib.sha256(doc.read_accessor(position).tobytes()).hexdigest()
    settings.wardrobe_adult_body_surface = True
    info = inspect_document(doc)
    context = SimpleNamespace(document=doc, info=info, measurements=measure_body(doc, info),
                              settings=settings,
                              fit_report=SimpleNamespace(base_body=None),
                              record=JobRecord.queued(CreateJobRequest.model_validate(request("sources/a.vrm"))))
    await prepare(context)
    kept = [p for m in doc.meshes for p in m["primitives"] if p.get("material") == material]
    assert kept, "the anatomy-labelled primitive was stripped"
    assert hashlib.sha256(doc.read_accessor(kept[0]["attributes"]["POSITION"]).tobytes()).hexdigest() == before
    assert material in context.fit_report.base_body["keptAnatomicalMaterials"]
    assert material in context.fit_report.base_body["protectedAnatomicalMaterials"]
    # Every other detected garment is gone.
    others = [g for g in garment_inventory(doc)
              if doc.meshes[g.mesh]["primitives"][g.primitive].get("material") != material]
    assert not others


def _painted_feet_share(doc):
    """Share of her foot/ankle skin vertices whose texel is dark paint (socks, painted shoes)."""
    import io

    import numpy as np
    from PIL import Image

    from wardrobe.body_surface.surface import skin_parts
    from wardrobe.vrm.inspect import inspect_document
    from wardrobe.vrm.measure import measure_body
    bones = {k: np.asarray(v, float) for k, v in dict(measure_body(doc, inspect_document(doc)).bone_positions).items()}
    dark, total = 0, 0
    for part in skin_parts(doc, bones):
        material = doc.materials[part.material]
        info = (material.get("pbrMetallicRoughness") or {}).get("baseColorTexture")
        attrs = doc.meshes[part.primitives[0][0]]["primitives"][part.primitives[0][1]]["attributes"]
        if not info or "TEXCOORD_0" not in attrs:
            continue
        image = doc.gltf["images"][doc.gltf["textures"][info["index"]]["source"]]
        view = doc.gltf["bufferViews"][image["bufferView"]]
        start = view.get("byteOffset", 0)
        tex = np.asarray(Image.open(io.BytesIO(doc.binary[start:start + view["byteLength"]])).convert("RGB"))
        uv = doc.read_accessor(attrs["TEXCOORD_0"])[part.used]
        feet = part.positions[part.used][:, 1] < bones["leftFoot"][1] + 0.05
        h, w = tex.shape[:2]
        rgb = tex[np.clip(((uv[:, 1] % 1) * h).astype(int), 0, h - 1), np.clip(((uv[:, 0] % 1) * w).astype(int), 0, w - 1)]
        dark += int((rgb[feet].max(1) < 64).sum())
        total += int(feet.sum())
    return dark / max(total, 1)


async def test_bare_is_barefoot_and_other_modes_still_stop_at_the_ankles(settings):
    """AF4. Rinna's feet are painted black (socks): the bare body takes them off with the rest of her
    painted clothing; the shared restorer, called as every other mode calls it, leaves feet alone."""
    from types import SimpleNamespace

    from wardrobe.domain.jobs import JobRecord
    from wardrobe.pipeline.bare_body import prepare
    from wardrobe.vrm.inspect import inspect_document
    from wardrobe.vrm.measure import measure_body
    from wardrobe.vrm.skin_restore import restore_skin
    path = Path(__file__).parents[2] / "assets/library/vroid/vroid-rinna.vrm"
    if not path.exists():
        pytest.skip("library Rinna unavailable")
    assert _painted_feet_share(GltfDocument.from_bytes(path.read_bytes())) > 0.5
    other = GltfDocument.from_bytes(path.read_bytes())
    restore_skin(other, measure_body(other, inspect_document(other)), set())
    assert _painted_feet_share(other) > 0.5
    doc = GltfDocument.from_bytes(path.read_bytes())
    settings.wardrobe_adult_body_surface = True
    info = inspect_document(doc)
    context = SimpleNamespace(document=doc, info=info, measurements=measure_body(doc, info), settings=settings,
                              fit_report=SimpleNamespace(base_body=None),
                              record=JobRecord.queued(CreateJobRequest.model_validate(request("sources/a.vrm"))))
    await prepare(context)
    assert _painted_feet_share(doc) == 0
