"""The second test mannequin: AvatarSample_A's body as a faceless grey dress form.

A real VRoid export's topology, skin weights and clothing slots, for the tests the
lofted calibration mannequin cannot stand in for. It is not declared adult (its
measured spans fall below the calibration bodies', and nobody has said how old the
character it came from is), so it dresses in clothes and is refused underwear like
any undeclared avatar.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.conftest import job_request
from wardrobe.domain.jobs import CreateJobRequest, FailureReason, JobState
from wardrobe.library import AvatarLibrary
from wardrobe.policy.calibration import declared_adult
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.garment_inventory import garment_inventory
from wardrobe.vrm.inspect import inspect_document

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "gallery"))
from looks import CHARACTER_PARTS, dress_form  # noqa: E402

LIBRARY = AvatarLibrary.from_directory(ROOT / "assets" / "library")
SAMPLE = LIBRARY.get("avatar-sample-a")
pytestmark = pytest.mark.skipif(SAMPLE is None or SAMPLE.path is None,
                                reason="the avatar library is not fetched (tools/fetch_library.py)")


@pytest.fixture(scope="module")
def form() -> bytes:
    return dress_form(SAMPLE.path.read_bytes())


def test_the_form_is_her_body_without_the_character(form):
    assert form == dress_form(SAMPLE.path.read_bytes())  # deterministic
    doc = GltfDocument.from_bytes(form)
    assert len(inspect_document(doc).humanoid_bones) >= 15
    drawn = {doc.materials[p["material"]].get("name", "") for n in doc.nodes if "mesh" in n
             for p in doc.meshes[n["mesh"]]["primitives"] if p.get("material") is not None}
    assert not any(part in name for name in drawn for part in CHARACTER_PARTS)
    skin = [m for m in doc.materials if "SKIN" in m.get("name", "")]
    assert skin and all("baseColorTexture" not in m.get("pbrMetallicRoughness", {}) for m in skin)
    assert {g.slot for g in garment_inventory(doc)} == {"tops", "bottoms", "shoes"}


def test_the_form_is_not_declared_adult():
    assert not declared_adult("dress-form-a")


async def _dress(orchestrator, store, form, prompt, **options):
    await store.put("sources/form.vrm", form)
    payload = job_request("sources/form.vrm", prompt, **options)
    payload["avatar"] = {**{k: v for k, v in SAMPLE.avatar_input().items() if k not in ("storageKey", "sha256")},
                         "storageKey": "sources/form.vrm", "avatarId": "dress-form-a"}
    return await orchestrator.run_now(CreateJobRequest.model_validate(payload))


async def test_clothes_take_her_own_off_and_fit(orchestrator, store, form):
    record = await _dress(orchestrator, store, form, "black fitted crop top + blue straight jeans")
    assert record.state is JobState.COMPLETED, record.error
    assert sorted(record.fit_report.replaced_garments) == ["bottoms", "tops"]
    assert record.fit_report.passed


async def test_underwear_on_the_undeclared_form_is_refused(orchestrator, store, form):
    record = await _dress(orchestrator, store, form, "white bra + white thong", baseBody="underwear-base")
    assert record.state is JobState.REJECTED and record.reason is FailureReason.ADULT_DECLARATION_REQUIRED
