"""BS1–BS5 through the real pipeline: asked for, gated, built, fitted to, exported — or not at all.

* a job without ``bodySurface`` has no body-surface block, and ``clothRelaxation`` alone does
  nothing (there is nothing to relax against);
* an unknown profile is refused before anything is built;
* an adult profile is refused by the model's terms, then the operator's switch, then the
  declaration — and runs only with all three;
* a collision-only profile fits to her collision body and reports every layer's signed
  clearance; nothing about her body is exported;
* ``detailLevel: "render"`` exports a made region as a morph target, her POSITION data untouched;
* an XPBD relaxation that would not have improved her clearance is not applied.

The adult-profile tests use a test profile in a temporary root; nothing intimate ships.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

from wardrobe.body_surface.surface import skin_parts
from wardrobe.config import Settings
from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.jobs import CreateJobRequest
from wardrobe.pipeline.orchestrator import Orchestrator
from wardrobe.queue.jobs import AsyncioJobQueue
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository
from wardrobe.storage.object_store import LocalObjectStore
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.fashion_body import build_fit_form, fit_form
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "body_surface"))
import install_template  # noqa: E402

DRESS = "navy bodycon dress"


def allowing(vrm1: bytes) -> bytes:
    """The VRM 1.0 calibration body with its author's terms allowing sexual expression.

    As shipped it says ``allowExcessivelySexualUsage: false`` — which the adult gate reads as a
    no, before asking anything else (test_an_adult_profile_is_refused_in_order).
    """
    document = GltfDocument.from_bytes(vrm1)
    document.gltf["extensions"]["VRMC_vrm"]["meta"]["allowExcessivelySexualUsage"] = True
    return document.to_bytes()


def run(source: bytes, prompt: str, *, adult: bool = True, settings: dict | None = None, **extra):
    """One job, on its own orchestrator and store: (record, output bytes or None, store root)."""

    async def go(tmp: Path):
        config = Settings(wardrobe_storage_root=str(tmp), wardrobe_engine="native", strict_licensing=True,
                          **(settings or {}))
        store = LocalObjectStore(config.storage_root_path, config)
        orchestrator = Orchestrator(settings=config, store=store, jobs=InMemoryJobRepository(),
                                    wardrobes=InMemoryWardrobeRepository(), queue=AsyncioJobQueue(concurrency=1),
                                    catalog=TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates"))
        await store.put("sources/a.vrm", source)
        options = {"renderPreview": False, "engine": "native", **extra.pop("options", {})}
        record = await orchestrator.run_now(CreateJobRequest.model_validate({
            "avatar": {"storageKey": "sources/a.vrm", "avatarId": "test-avatar", "depictsAdult": adult},
            "outfit": {"prompt": prompt, "mode": "template"}, "options": options, **extra}))
        data = await store.get(f"looks/{record.look.id}/look.vrm") if record.look else None
        return record, data, await store.get("sources/a.vrm")

    with tempfile.TemporaryDirectory() as tmp:
        return asyncio.run(go(Path(tmp)))


def report(record) -> dict:
    return record.fit_report.model_dump(by_alias=True, mode="json")


@pytest.fixture(scope="module")
def adult_root(tmp_path_factory) -> Path:
    """A test-only profile whose region is labelled intimate: a generic bump, nothing anatomical."""
    root = tmp_path_factory.mktemp("adult-profile")
    axis = np.linspace(-1, 1, 9)
    u, v = np.meshgrid(axis, axis)
    field = np.zeros((9, 9, 3))
    field[:, :, 0] = 0.002 * np.clip(1 - (u ** 2 + v ** 2), 0, 1) ** 2
    field[0, :] = field[-1, :] = field[:, 0] = field[:, -1] = 0
    install_template.install(field, template_id="test-bump/v1", region="chestDetail", anchor="sternum",
                             radius_m=0.04, license_id="CC0-1.0", source="test fixture", author="tests",
                             landmarks={"centre": {"uv": [0, 0]}}, reference_waist_m=0.26,
                             templates_dir=root / "templates")
    (root / "profiles").mkdir()
    (root / "profiles" / "test-adult.json").write_text(json.dumps({
        "schema": "wardrobe.bodySurface.v1", "profileId": "test-adult", "capability": "body_collision",
        "regions": {"chestDetail": {"templateId": "test-bump/v1"}}}))
    return root


# ---------------------------------------------------------------------------------------------
def test_without_a_body_surface_nothing_is_added(vrm_bytes):
    record, data, _ = run(vrm_bytes, DRESS, options={"clothRelaxation": "xpbd"})
    assert record.state == "completed", record.error
    dumped = report(record)
    assert "bodySurface" not in dumped
    assert all("relaxation" not in layer for layer in dumped["layers"])


def test_an_unknown_profile_is_refused_before_anything_is_built(vrm_bytes):
    record, data, _ = run(vrm_bytes, DRESS, bodySurface={"profileId": "no-such-profile"})
    assert record.state == "rejected" and record.reason == "body_surface_profile_unavailable"
    assert data is None


@pytest.mark.parametrize("enabled, adult, which, refused_by", [
    (True, True, "vrm0", "model-terms"),      # the VRM 0.x calibration body: sexualUssageName Disallow
    (True, True, "vrm1", "model-terms"),      # the VRM 1.0 one as shipped: allowExcessivelySexualUsage false
    (False, True, "allowing", "operator-disabled"),
    (True, False, "allowing", "adult-declaration"),
])
def test_an_adult_profile_is_refused_in_order(adult_root, vrm_bytes, vrm0_bytes, enabled, adult, which,
                                              refused_by):
    source = {"vrm0": vrm0_bytes, "vrm1": vrm_bytes, "allowing": allowing(vrm_bytes)}[which]
    settings = {"wardrobe_body_surface_root": str(adult_root), "wardrobe_adult_body_surface": enabled}
    record, data, _ = run(source, DRESS, adult=adult, settings=settings, bodySurface={"profileId": "test-adult"})
    assert record.state == "rejected" and record.reason == "body_surface_not_permitted"
    said = {"model-terms": "own terms", "operator-disabled": "not enabled", "adult-declaration": "declared"}
    assert said[refused_by] in record.error
    assert data is None


def test_an_adult_profile_runs_only_with_all_three(adult_root, vrm_bytes):
    settings = {"wardrobe_body_surface_root": str(adult_root), "wardrobe_adult_body_surface": True}
    record, _, _ = run(allowing(vrm_bytes), DRESS, settings=settings, bodySurface={"profileId": "test-adult"})
    assert record.state == "completed", record.error
    assert report(record)["bodySurface"]["capability"] == "adult_body_surface"


def test_a_collision_profile_fits_to_it_and_reports_clearance(vrm_bytes):
    record, data, source_after = run(vrm_bytes, DRESS, adult=False,
                                     bodySurface={"profileId": "collision-reference"})
    assert record.state == "completed", record.error
    surface = report(record)["bodySurface"]
    assert surface["built"] and surface["capability"] == "body_collision" and not surface["morphTargets"]
    (layer,) = surface["clearance"]
    assert layer["samples"] > 0 and "minimumSignedDistanceMm" in layer and "uncertainPenetratingSamples" in layer
    names = [n for m in GltfDocument.from_bytes(data).meshes for n in (m.get("extras") or {}).get("targetNames", [])]
    assert not any(n.startswith("Body") for n in names)
    assert source_after == vrm_bytes  # the source is never touched


@pytest.fixture(scope="module")
def fit_form_bytes() -> bytes:
    return build_fit_form(fit_form("fit-form-a-misses"))


def test_render_detail_exports_a_made_region_and_leaves_her_positions(fit_form_bytes):
    record, data, _ = run(fit_form_bytes, "black tailored briefs",
                          bodySurface={"profileId": "navel-reference", "detailLevel": "render"})
    assert record.state == "completed", record.error
    surface = report(record)["bodySurface"]
    (navel,) = surface["regions"]
    assert navel["made"] and navel["vertices"] >= 8 and surface["exportedMorphTargets"] == ["BodyNavel"]
    assert all(change < 0.005 for change in navel["measurements"].values())
    out = GltfDocument.from_bytes(data)
    mesh = next(m for m in out.meshes if "BodyNavel" in (m.get("extras") or {}).get("targetNames", []))
    assert len({len(p.get("targets", [])) for p in mesh["primitives"]}) == 1
    assert mesh["weights"][-1] == 1.0
    source = GltfDocument.from_bytes(fit_form_bytes)
    bones = measure_body(source, inspect_document(source)).bone_positions
    (before,), (after,) = skin_parts(source, bones), skin_parts(out, bones)
    assert np.array_equal(before.positions, after.positions)  # the region is a morph, not an edit


def test_a_relaxation_that_does_not_help_is_not_applied(fit_form_bytes):
    """On the fit form the brief's gusset sits in the hollow below her crotch, where contact is
    ill-posed: the relaxation is computed, found to make her clearance worse, and refused."""
    plain, plain_data, _ = run(fit_form_bytes, "black tailored briefs",
                               bodySurface={"profileId": "collision-reference"})
    relaxed, relaxed_data, _ = run(fit_form_bytes, "black tailored briefs",
                                   bodySurface={"profileId": "collision-reference"},
                                   options={"clothRelaxation": "xpbd"})
    (layer,) = report(relaxed)["layers"]
    relaxation = layer["relaxation"]
    assert relaxation["solver"] == "xpbd"
    if not relaxation.get("applied", True):
        assert "worse" in relaxation["reason"]
        garment = [n for n in GltfDocument.from_bytes(plain_data).nodes if "mesh" in n][-1]
        a = GltfDocument.from_bytes(plain_data)
        b = GltfDocument.from_bytes(relaxed_data)
        pa = a.read_accessor(a.meshes[garment["mesh"]]["primitives"][0]["attributes"]["POSITION"])
        pb = b.read_accessor(b.meshes[garment["mesh"]]["primitives"][0]["attributes"]["POSITION"])
        assert np.array_equal(pa, pb)  # kept exactly as fitted
    else:
        after = report(relaxed)["bodySurface"]["clearance"][0]["minimumSignedDistanceMm"]
        before = report(plain)["bodySurface"]["clearance"][0]["minimumSignedDistanceMm"]
        assert after >= before - 1e-3
