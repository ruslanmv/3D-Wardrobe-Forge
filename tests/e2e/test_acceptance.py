"""CI acceptance criteria.

From docs/PIPELINE.md — the bar is not "the exporter exited 0", it is::

    source VRM -> generate outfit -> output VRM -> REIMPORT OUTPUT
      file parses / humanoid mapping preserved / head still works /
      skeleton preserved / garment has valid weights / animation pose works /
      severe body intersections absent / original recoverable / preview renders

Every avatar here is generated from :mod:`wardrobe.vrm.build`, so the matrix
runs on four different body shapes in both VRM specs with no external assets.
"""

from __future__ import annotations

import pytest

from tests.conftest import job_request
from wardrobe.domain.jobs import CreateJobRequest, JobState
from wardrobe.domain.looks import ClippingCheck
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import REQUIRED_HUMANOID_BONES, inspect_document, validate_humanoid

#: One garment per category, so coverage of the library is part of the matrix.
PROMPTS = [
    "elegant dark red evening dress",
    "black satin cocktail dress",
    "cozy oversized wool coat",
    "slim blue denim jeans",
    "white cotton blouse",
    "flowing green maxi skirt",
    "black ankle boots",
]

SPECS = ["VRM1", "VRM0"]


@pytest.mark.parametrize("spec", SPECS)
@pytest.mark.parametrize("body", CALIBRATION_BODIES, ids=lambda b: b.name)
@pytest.mark.parametrize("prompt", PROMPTS)
async def test_generated_look_survives_a_reimport(orchestrator, store, spec, body, prompt):
    """The M2 criterion: one garment set, every body, both specs."""
    source = build_vrm(body, spec=spec)
    key = f"sources/{spec}-{body.name}.vrm"
    await store.put(key, source)

    record = await orchestrator.run_now(
        CreateJobRequest.model_validate(job_request(key, prompt, avatar_id=body.name))
    )

    assert record.state is JobState.COMPLETED, f"{prompt} on {body.name}: {record.error}"
    output = await orchestrator.store.get(f"looks/{record.look.id}/look.vrm")

    source_document = GltfDocument.from_bytes(source)
    source_info = inspect_document(source_document)

    # 1. the file parses
    document = GltfDocument.from_bytes(output)
    info = inspect_document(document)

    # 2. humanoid mapping preserved
    assert set(info.humanoid_bones) >= REQUIRED_HUMANOID_BONES
    assert validate_humanoid(document, info) == []

    # 3. head and face still work
    assert "head" in info.humanoid_bones
    assert set(source_info.expressions) <= set(info.expressions)

    # 4. skeleton preserved, node for node
    assert info.humanoid_bones == source_info.humanoid_bones
    assert len(document.nodes) >= len(source_document.nodes)

    # 5. the garment is there and is weighted
    assert info.mesh_count == source_info.mesh_count + 1
    report = record.fit_report
    assert report.weights_valid
    assert report.garment_triangles > 0
    assert report.bones_used

    # 6. animation poses work
    assert report.pose_tests.get("passed") is True

    # 7. severe body intersections absent
    assert report.clipping_check is not ClippingCheck.FAILED

    # 8. the original avatar is still recoverable
    assert report.source_recoverable
    assert await orchestrator.store.get(key) == source

    # 9. the whole report passes
    assert report.passed, report.warnings


@pytest.mark.parametrize("body", CALIBRATION_BODIES, ids=lambda b: b.name)
async def test_preview_renders_for_every_body(orchestrator, store, body):
    source = build_vrm(body, spec="VRM1")
    key = f"sources/preview-{body.name}.vrm"
    await store.put(key, source)

    record = await orchestrator.run_now(
        CreateJobRequest.model_validate(
            job_request(key, "elegant burgundy evening dress", render_preview=True)
        )
    )

    assert record.state is JobState.COMPLETED
    assert record.fit_report.preview_rendered
    preview = await orchestrator.store.get(f"looks/{record.look.id}/preview.webp")
    assert len(preview) > 512


async def test_looks_accumulate_into_one_wardrobe(orchestrator, store):
    """M7: an avatar collects looks it can switch between."""
    source = build_vrm(CALIBRATION_BODIES[1], spec="VRM1")
    key = "sources/haul.vrm"
    await store.put(key, source)

    for prompt in ("burgundy evening dress", "cozy oversized coat", "slim blue jeans"):
        record = await orchestrator.run_now(
            CreateJobRequest.model_validate(job_request(key, prompt, avatar_id="haul"))
        )
        assert record.state is JobState.COMPLETED

    manifest = await orchestrator.wardrobes.get("haul")
    assert len([look for look in manifest.looks if look.type == "vrmVariant"]) == 3
    assert all(look.fit_passed for look in manifest.looks if look.type == "vrmVariant")

    # Try-On Haul needs every look to be loadable by URL.
    rendered = manifest.to_avatar_manifest()
    assert len(rendered["items"]) == 3
