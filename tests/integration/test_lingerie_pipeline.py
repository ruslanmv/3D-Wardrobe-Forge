"""Pattern-block lingerie through the real pipeline, on the fashion-fit forms the repository declares adult.

What the unit tests hold for the block as drafted, these hold for the garment
as delivered: after the shell's passes, the gusset seated under her, skinning
and export. One garment, three openings, the gusset across the midline under
her crotch, every vertex outside her surface. The declaration comes from
``assets/calibration/policy.json`` through the job's avatar block, as for every
intimate-wear test here, and the same request without it is refused.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest

from wardrobe.config import Settings
from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.jobs import CreateJobRequest, FailureReason, JobState
from wardrobe.geometry.mesh import Mesh
from wardrobe.hosiery.poses import posed_body
from wardrobe.lingerie.fit import _depth
from wardrobe.lingerie.landmarks import measure_document
from wardrobe.lingerie.seams import boundary_loops, components
from wardrobe.pipeline.orchestrator import Orchestrator
from wardrobe.policy.calibration import declared_adult
from wardrobe.queue.jobs import AsyncioJobQueue
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository
from wardrobe.storage.object_store import LocalObjectStore
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.fashion_body import FASHION_FIT_BODIES, build_fit_form
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body

ROOT = Path(__file__).resolve().parents[2]
FORMS = {form.name: form for form in FASHION_FIT_BODIES}


def run(tmp: Path, form: str, prompt: str, *, adult: bool | None = None):
    settings = Settings(wardrobe_storage_root=str(tmp), wardrobe_engine="native", strict_licensing=True)
    store = LocalObjectStore(settings.storage_root_path, settings)
    orchestrator = Orchestrator(settings=settings, store=store, jobs=InMemoryJobRepository(),
                                wardrobes=InMemoryWardrobeRepository(), queue=AsyncioJobQueue(concurrency=1),
                                catalog=TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates"))
    declared = declared_adult(form) if adult is None else adult

    async def go():
        await store.put("sources/form.vrm", build_fit_form(FORMS[form]))
        request = CreateJobRequest.model_validate({
            "avatar": {"storageKey": "sources/form.vrm", "avatarId": form, "depictsAdult": declared},
            "outfit": {"prompt": prompt, "mode": "template"},
            "options": {"renderPreview": False, "engine": "native"},
        })
        record = await orchestrator.run_now(request)
        data = await store.get(f"looks/{record.look.id}/look.vrm") if record.look else None
        return record, data

    return asyncio.run(go())


def garment_meshes(data: bytes) -> dict[str, Mesh]:
    """Each garment node's primitives as one mesh (sections export as separate primitives)."""
    document = GltfDocument.from_bytes(data)
    out = {}
    for node in document.nodes:
        forge = (node.get("extras") or {}).get("wardrobeForge") or {}
        if forge.get("kind") != "garment" or "mesh" not in node:
            continue
        positions, indices, offset = [], [], 0
        for primitive in document.meshes[node["mesh"]]["primitives"]:
            p = document.read_accessor(primitive["attributes"]["POSITION"]).astype(np.float32)
            indices.append(document.read_accessor(primitive["indices"]).reshape(-1).astype(np.int64) + offset)
            positions.append(p)
            offset += p.shape[0]
        out[node.get("name", "garment")] = Mesh(positions=np.vstack(positions),
                                                indices=np.concatenate(indices).astype(np.uint32))
    return out


@pytest.fixture(scope="module", params=sorted(FORMS))
def brief(request, tmp_path_factory):
    record, data = run(tmp_path_factory.mktemp("brief"), request.param, "black tailored briefs")
    source = GltfDocument.from_bytes(build_fit_form(FORMS[request.param]))
    return request.param, record, data, source


def test_the_tailored_brief_is_built_and_fits(brief):
    _form, record, data, _source = brief
    assert record.look is not None, record.error
    assert [g.template_id for g in record.plan.garments] == ["under-briefs-v2"]
    assert record.fit_report.passed


def test_delivered_it_is_one_garment_with_three_openings(brief):
    _form, _record, data, _source = brief
    (mesh,) = garment_meshes(data).values()
    assert components(mesh) == 1
    assert sorted(len(loop) for loop in boundary_loops(mesh))[:2] == [24, 24]
    assert len(boundary_loops(mesh)) == 3


def test_the_gusset_crosses_under_her_on_the_midline(brief):
    _form, _record, data, source = brief
    (mesh,) = garment_meshes(data).values()
    marks = measure_document(source).landmarks
    points = mesh.positions.astype(np.float64)
    under = points[points[:, 1] < marks.crotch_y]
    assert under.shape[0] >= 10  # it goes under her, not round her
    assert abs(float(under[:, 0].mean()) - marks.centre_x) < 0.005


def test_every_vertex_is_outside_her(brief):
    _form, _record, data, source = brief
    (mesh,) = garment_meshes(data).values()
    info = inspect_document(source)
    measurements = measure_body(source, info)
    points, normals = posed_body(source, info, "stand", 1.0, measurements.bone_positions, spacing=0.006)
    garment = mesh.positions.astype(np.float64)
    near = np.all((points >= garment.min(axis=0) - 0.05) & (points <= garment.max(axis=0) + 0.05), axis=1)
    signed, _ = _depth(garment, points[near], normals[near])
    assert signed.min() >= 0.0005, signed.min()


@pytest.fixture(scope="module", params=sorted(FORMS))
def bralette(request, tmp_path_factory):
    record, data = run(tmp_path_factory.mktemp("bra"), request.param, "black tailored bralette")
    source = GltfDocument.from_bytes(build_fit_form(FORMS[request.param]))
    return request.param, record, data, source


def test_the_tailored_bralette_is_built_and_fits(bralette):
    _form, record, data, _source = bralette
    assert record.look is not None, record.error
    assert [g.template_id for g in record.plan.garments] == ["under-bralette-v2"]
    assert record.fit_report.passed


def test_delivered_it_is_the_bra_and_two_straps(bralette):
    _form, _record, data, _source = bralette
    (mesh,) = garment_meshes(data).values()
    assert components(mesh) == 3
    assert len(boundary_loops(mesh)) == 2


def test_every_bra_vertex_is_outside_her(bralette):
    _form, _record, data, source = bralette
    (mesh,) = garment_meshes(data).values()
    info = inspect_document(source)
    measurements = measure_body(source, info)
    points, normals = posed_body(source, info, "stand", 1.0, measurements.bone_positions, spacing=0.006)
    garment = mesh.positions.astype(np.float64)
    near = np.all((points >= garment.min(axis=0) - 0.05) & (points <= garment.max(axis=0) + 0.05), axis=1)
    signed, _ = _depth(garment, points[near], normals[near])
    assert signed.min() >= 0.0005, signed.min()


def test_the_gate_refuses_it_without_a_declaration(tmp_path):
    record, data = run(tmp_path, "fit-form-a-misses", "black tailored briefs", adult=False)
    assert data is None
    assert record.state is JobState.REJECTED
    assert record.reason is FailureReason.ADULT_DECLARATION_REQUIRED
