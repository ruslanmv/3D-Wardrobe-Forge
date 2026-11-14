"""The four dark-fashion garments, fitted and exported.

A plan that names the right template is not the garment. Each look has to come
back as a valid VRM on a humanoid rig, with skin weights that sum to one, and
with the pieces that make it that garment still in the file.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.conftest import job_request
from wardrobe.domain.jobs import CreateJobRequest, JobState
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document, validate_humanoid


async def _dress(orchestrator, store, key, prompt, *, adult=False):
    payload = job_request(key, prompt)
    payload["avatar"]["depictsAdult"] = adult
    record = await orchestrator.run_now(CreateJobRequest.model_validate(payload))
    data = await store.get(f"looks/{record.look.id}/look.vrm") if record.look else None
    return record, data


def _garments(document: GltfDocument) -> list[dict]:
    found = []
    for node in document.nodes:
        forge = (node.get("extras") or {}).get("wardrobeForge") or {}
        if forge.get("kind") == "garment" and "mesh" in node:
            found.append({"name": node.get("name"), "forge": forge, "mesh": document.meshes[node["mesh"]]})
    return found


def _weights_sum(document: GltfDocument, mesh: dict) -> bool:
    primitive = mesh["primitives"][0]
    weights = document.read_accessor(primitive["attributes"]["WEIGHTS_0"])
    return bool(np.allclose(weights.sum(axis=1), 1.0, atol=1e-3))


@pytest.mark.parametrize(
    ("prompt", "adult", "template_id"),
    [
        ("high-neck latex catsuit", False, "jumpsuit-high-neck-latex-v1"),
        ("buckle-front leather mini dress", False, "dress-buckle-leather-mini-v1"),
        ("structured leather corset", False, "top-structured-leather-corset-v1"),
    ],
)
async def test_the_fashion_garment_fits_without_an_adult_gate(orchestrator, store, stored_avatar, prompt, adult, template_id):
    record, data = await _dress(orchestrator, store, stored_avatar, prompt, adult=adult)
    assert record.state is JobState.COMPLETED, record.error
    assert record.fit_report.passed, record.fit_report.model_dump()
    assert record.plan.template_id == template_id
    assert record.plan.requires_adult is False
    document = GltfDocument.from_bytes(data)
    info = inspect_document(document)
    assert validate_humanoid(document, info) == []
    garments = _garments(document)
    assert len(garments) == 1
    assert _weights_sum(document, garments[0]["mesh"])
    if template_id != "jumpsuit-high-neck-latex-v1":
        # Buckles and busk studs are their own silver primitive.
        assert any("Hardware" in str(document.materials[p["material"]].get("name"))
                   for p in garments[0]["mesh"]["primitives"])


async def test_the_leather_garter_is_a_belt_stockings_and_clips(orchestrator, store, stored_avatar):
    refused, _ = await _dress(orchestrator, store, stored_avatar, "leather garter belt with stockings", adult=False)
    assert refused.state is JobState.REJECTED

    record, data = await _dress(orchestrator, store, stored_avatar, "leather garter belt with stockings", adult=True)
    assert record.state is JobState.COMPLETED, record.error
    assert record.fit_report.passed, record.fit_report.model_dump()
    assert record.plan.requires_adult is True
    ids = {g.template_id for g in record.plan.garments}
    assert "under-suspender-belt-v1" in ids and "legwear-thigh-highs-v1" in ids
    document = GltfDocument.from_bytes(data)
    assert validate_humanoid(document, inspect_document(document)) == []
    garments = _garments(document)
    roles = {g["forge"].get("role") for g in garments}
    assert "connector" in roles
    assert all(_weights_sum(document, g["mesh"]) for g in garments)
    connector = next(g for g in garments if g["forge"].get("role") == "connector")
    assert any("Hardware" in str(document.materials[p["material"]].get("name"))
               for p in connector["mesh"]["primitives"])
