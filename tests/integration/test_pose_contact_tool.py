"""The pose-contact research tools measure what they say (docs/POSE_CONTACT_QA.md)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from tests.conftest import job_request
from wardrobe.domain.jobs import CreateJobRequest
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.fashion_body import build_fit_form, fit_form

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("pose_contact", ROOT / "tools/inspect/pose_contact.py")
pose_contact = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pose_contact)
POSES = {p["name"]: p for p in json.loads((ROOT / "tests/fixtures/homepilot-poses.json").read_text())["presets"]}


@pytest.fixture
async def look(orchestrator, store, tmp_path) -> Path:
    await store.put("sources/form.vrm", build_fit_form(fit_form("fit-form-a-misses")))
    record = await orchestrator.run_now(CreateJobRequest.model_validate(
        job_request("sources/form.vrm", "red bodycon mini dress", template_id="dress-mini-bodycon-v1")))
    assert record.state == "completed", record.error
    path = tmp_path / "look.vrm"
    path.write_bytes(await store.get(f"looks/{record.look.id}/look.vrm"))
    return path


def test_the_fixture_is_pose_studios_non_adult_presets():
    assert {"standing", "sitting", "sittingCrossed", "sittingWide", "sittingDesk", "kneeling"} <= set(POSES)
    assert all(len(q) == 4 and abs(np.linalg.norm(q) - 1) < 1e-6 for p in POSES.values() for q in p["bones"].values())


async def test_standing_at_rest_nothing_is_inside_and_nothing_stretches(look):
    (by_pose,) = pose_contact.measure(look, [], ["Red Bodycon Mini Dress"])["garments"].values()
    rest = by_pose["rest"]
    assert rest["penetratingPct"] == 0.0 and rest["maxEdgeStretch"] == 1.0


async def test_a_seated_pose_moves_the_garment_and_is_measured(look):
    (by_pose,) = pose_contact.measure(look, [POSES["sittingWide"]], ["Red Bodycon Mini Dress"])["garments"].values()
    assert by_pose["sittingWide"]["maxEdgeStretch"] > 1.0  # the pose was applied


async def test_a_coloured_copy_carries_one_colour_per_garment_vertex_and_leaves_the_source(look, tmp_path):
    source = look.read_bytes()
    out = tmp_path / "coloured.vrm"
    pose_contact.coloured(look, POSES["sittingWide"], ["Red Bodycon Mini Dress"], "clearance", out)
    assert look.read_bytes() == source
    document = GltfDocument.from_bytes(out.read_bytes())
    names = [m.get("name", "") for m in document.gltf["materials"]]
    coloured = [p for m in document.meshes for p in m["primitives"] if "COLOR_0" in p["attributes"]]
    assert coloured and all(names[p["material"]].startswith("Red Bodycon Mini Dress") for p in coloured)
    for primitive in coloured:
        assert (document.read_accessor(primitive["attributes"]["COLOR_0"]).shape[0]
                == document.read_accessor(primitive["attributes"]["POSITION"]).shape[0])
