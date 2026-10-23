"""PS3. Measured in HomePilot's own poses: a close-cut mini follows her as she sits wide.

``tools/inspect/pose_contact.py`` poses the whole fitted file — her skin and every garment by
its own weights — with Pose Studio's quaternions (``tests/fixtures/homepilot-poses.json``) and
measures each garment against her posed skin. Bound to her pelvis, the bodycon mini let her
thighs rise through its lap and sides as she sat wide; bound like her skin it sinks in less.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from tests.conftest import job_request
from wardrobe.domain.jobs import CreateJobRequest
from wardrobe.engines import native
from wardrobe.vrm.fashion_body import build_fit_form, fit_form

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("pose_contact", ROOT / "tools/inspect/pose_contact.py")
pose_contact = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pose_contact)
POSES = {
    p["name"]: p for p in json.loads((ROOT / "tests/fixtures/homepilot-poses.json").read_text())["presets"]
}


@pytest.fixture(scope="module")
def body() -> bytes:
    # A fit form, not a calibration body: those are rings and cylinders weighted rigidly, on
    # which her skin's weights and the nearest bone are the same binding and nothing differs.
    return build_fit_form(fit_form("fit-form-a-misses"))


async def _dress(orchestrator, store, body, tmp_path) -> Path:
    await store.put("sources/pose.vrm", body)
    record = await orchestrator.run_now(
        CreateJobRequest.model_validate(
            job_request("sources/pose.vrm", "red bodycon mini dress", template_id="dress-mini-bodycon-v1")
        )
    )
    assert record.state == "completed", record.error
    out = tmp_path / f"{record.look.id}.vrm"
    out.write_bytes(await store.get(f"looks/{record.look.id}/look.vrm"))
    return out


def _inside(path: Path, pose: str) -> float:
    report = pose_contact.measure(path, [POSES[pose]], ["Red Bodycon Mini Dress"])
    (by_pose,) = report["garments"].values()
    return by_pose[pose]["penetratingPct"]


def test_the_fixture_holds_pose_studios_presets():
    assert {"sitting", "sittingCrossed", "sittingWide", "sittingDesk", "kneeling"} <= set(POSES)
    assert all(len(q) == 4 for p in POSES.values() for q in p["bones"].values())


async def test_a_bodycon_mini_sinks_in_less_bound_like_her_skin(
    orchestrator, store, body, tmp_path, monkeypatch
):
    skin = await _dress(orchestrator, store, body, tmp_path)
    monkeypatch.setattr(native, "fitted_short", lambda template, plan: False)
    pelvis = await _dress(orchestrator, store, body, tmp_path)
    # Measured: on VRoid Female (hand-rigged skin) her skin's weights sink the dress in far less
    # in every seated pose (sitting 12.6% -> 2.9% of its vertices inside her, crossed 15.3% ->
    # 3.1%, wide 11.5% -> 4.8%). On this fit form, whose weights are generated and very smooth,
    # the two bindings are close and mixed (sitting 1.88% vs 1.36%, wide 2.61% vs 3.55%): only
    # the wide seat, the case reported from HomePilot, holds on both, so it is what is pinned.
    assert _inside(skin, "sittingWide") < _inside(pelvis, "sittingWide")
