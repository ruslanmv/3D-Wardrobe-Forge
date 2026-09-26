"""The try-on haul through the whole pipeline: change clothes, shade like her, stay valid."""

from __future__ import annotations

from tests.conftest import job_request
from tests.vroid_support import dress_like_vroid, primitive_materials
from wardrobe.domain.garments import INTIMATE_CATEGORIES, TemplateCatalog
from wardrobe.domain.jobs import CreateJobRequest
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument

BOTTOMS = "F00_000_01_Bottoms_01_CLOTH"
TOPS = "F00_000_01_Tops_01_CLOTH"


async def run(orchestrator, store, source: bytes, prompt: str):
    key = "sources/dressed.vrm"
    await store.put(key, source)
    record = await orchestrator.run_now(CreateJobRequest.model_validate(job_request(key, prompt)))
    output = await store.get(f"looks/{record.look.id}/look.vrm") if record.look else None
    return record, output


async def test_a_skirt_replaces_her_bottoms_and_keeps_her_top(orchestrator, store, vrm0_bytes):
    record, output = await run(orchestrator, store, dress_like_vroid(vrm0_bytes), "navy a-line skirt")
    assert record.state == "completed", record.error
    assert record.fit_report.replaced_garments == ["bottoms"]
    worn = primitive_materials(output)
    assert BOTTOMS not in worn and TOPS in worn


async def test_a_dress_replaces_both(orchestrator, store, vrm0_bytes):
    record, output = await run(orchestrator, store, dress_like_vroid(vrm0_bytes), "red cocktail dress")
    assert record.fit_report.replaced_garments == ["tops", "bottoms"]
    assert TOPS not in primitive_materials(output) and BOTTOMS not in primitive_materials(output)


async def test_replacement_can_be_turned_off_to_layer(orchestrator, store, vrm0_bytes):
    source = dress_like_vroid(vrm0_bytes)
    key = "sources/layered.vrm"
    await store.put(key, source)
    payload = job_request(key, "navy a-line skirt")
    payload["options"]["replaceGarments"] = False
    record = await orchestrator.run_now(CreateJobRequest.model_validate(payload))
    assert record.state == "completed" and record.fit_report.replaced_garments == []
    worn = primitive_materials(await store.get(f"looks/{record.look.id}/look.vrm"))
    assert BOTTOMS in worn and TOPS in worn


async def test_the_garment_is_toon_shaded_and_the_output_still_validates(orchestrator, store, vrm0_bytes):
    record, output = await run(orchestrator, store, dress_like_vroid(vrm0_bytes, mtoon=True), "red cocktail dress")
    assert record.state == "completed", record.error  # validate_output re-imported it
    document = GltfDocument.from_bytes(output)
    outer = record.plan.garments[-1].name  # the dress, over the liner a clothed avatar gets (S2)
    garment = next(i for i, m in enumerate(document.materials) if m.get("name", "").startswith(outer))
    entry = document.extension("VRM")["materialProperties"][garment]
    assert entry["shader"] == "VRM/MToon" and entry["textureProperties"] == {}


async def test_every_template_completes_and_passes(orchestrator, store, template_catalog: TemplateCatalog):
    """The acceptance bar for the whole library: generated, re-imported, fit report passed.

    On the VRM 1.0 calibration body — the VRM 0.x one's own terms disallow sexual
    usage, so it could not prove that swimwear and underwear fit.
    """
    await store.put("sources/haul.vrm", build_vrm(CALIBRATION_BODIES[2], spec="VRM1"))
    failures = []
    for template in template_catalog.all():
        payload = job_request("sources/haul.vrm", template.name, template_id=template.id)
        payload["avatar"]["depictsAdult"] = template.category in INTIMATE_CATEGORIES
        record = await orchestrator.run_now(CreateJobRequest.model_validate(payload))
        if record.state != "completed" or not record.fit_report.passed:
            failures.append((template.id, record.state, record.error, record.fit_report.clipping_check))
    assert not failures, failures


async def test_swimwear_is_refused_by_a_model_that_disallows_it(orchestrator, store, vrm0_bytes):
    await store.put("sources/v0.vrm", vrm0_bytes)
    payload = job_request("sources/v0.vrm", "red triangle bikini")
    payload["avatar"]["depictsAdult"] = True
    record = await orchestrator.run_now(CreateJobRequest.model_validate(payload))
    assert record.state == "rejected"
    assert record.reason == "intimate_garments_not_permitted_by_model"


async def test_swimwear_without_a_declaration_is_refused_and_nothing_is_removed(orchestrator, store, vrm_bytes):
    await store.put("sources/v1.vrm", dress_like_vroid(vrm_bytes))
    record = await orchestrator.run_now(CreateJobRequest.model_validate(job_request("sources/v1.vrm", "red triangle bikini")))
    assert record.state == "rejected" and record.reason == "requires_adult_declaration"
    assert record.look is None and record.fit_report.replaced_garments == []
